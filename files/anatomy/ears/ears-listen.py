#!/usr/bin/env python3
"""The ear: speech in, transcript out. It sends nothing to any agent.

WHAT THIS IS FOR, IN ORDER. First, a measurement — `--file` transcribes a
recording so "how well does parakeet hear this operator's Czech" becomes a
number rather than a hope (roadmap: local-llm-voice-asr). Second, the turn
segmentation the always-listen row describes: a wake phrase opens a turn, a
submit phrase or a silence closes it. Third, as `--daemon`, it keeps doing that
until someone stops it, writing turns where a reader can find them.

WHAT IT DOES NOT DO, AND THIS IS THE LINE THAT MATTERS. It does not execute
anything. With --autorun it hands a finished turn to caddy, which asks an
agent for a PROPOSAL and has the cortex daemon typecheck it; execution stays
behind CortexBindingGate, exactly where it was. The listener never becomes the
thing that acts — it becomes the thing that asks, and it detaches the ask so a
slow answer cannot make it deaf.

SILENCE AND REFUSAL LOOK IDENTICAL, SO THEY ARE SEPARATED HERE. A launchd agent
has no window to raise a microphone prompt, so macOS can deny it and the
process keeps running perfectly, hearing nothing — the exact shape this estate
keeps paying for. Two mechanisms, because a denial can arrive two ways: ffmpeg
exits (caught at EOF), or the device streams pure silence (caught by
`heard_any`, which requires a NON-ZERO sample — a zero-filled buffer is not
evidence of a microphone). If neither has produced real audio within
MIC_GRACE_S, the daemon writes mic_ok=false and exits 3, and launchd's throttle
turns that into a visible slow restart loop rather than a healthy-looking deaf
process.

AUDIO IS NEVER STORED. A segment becomes a temporary wav inside one function
call and is deleted in the `finally`. Transcripts are kept for
EARS_RETENTION_DAYS (90) and pruned by this process — with the oldest surviving
file reported by tools/caddy-status.py, so a retention that stops firing is
visible rather than assumed.

ONE SWITCH, AND IT IS NOT HERE. Starting and stopping the always-listen agent
is `ears_always_listen` in config.yml plus a converge. This file deliberately
has no --on/--off: two ways to open a microphone means the next converge
silently closes one of them, and the estate's standing rule is that either the
playbook does it or the operator runs nos, with nothing in between.

    ears-listen --file recording.m4a         # transcribe a file, JSON out
    ears-listen --listen                     # foreground, turns on stdout
    ears-listen --daemon                     # what launchd runs
    ears-listen --listen --autorun           # ... and put each turn to the caddy
    ears-listen --devices                    # what ffmpeg can hear
    ears-listen --selfcheck                  # the segmentation logic, offline
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import re
import queue
import subprocess
import sys
import tempfile
import threading
import time
import wave

RATE = 16_000                 # parakeet's sample rate; ffmpeg resamples to it
CHUNK_MS = 30                 # one VAD decision per 30 ms, the usual granularity
CHUNK_BYTES = RATE * 2 * CHUNK_MS // 1000

HOME = pathlib.Path(os.environ.get("EARS_HOME", pathlib.Path.home() / "ears"))
TURNS_DIR = HOME / "turns"
STATE_FILE = HOME / "state.json"

DEFAULT_MODEL = os.environ.get("EARS_ASR_MODEL", "mlx-community/parakeet-tdt-0.6b-v3")
DEFAULT_WAKE = os.environ.get("EARS_WAKE_PHRASE", "hej jeffe")
DEFAULT_SUBMIT = os.environ.get("EARS_SUBMIT_PHRASE", "makej jeffe")
DEFAULT_SILENCE = float(os.environ.get("EARS_SILENCE_SECONDS", "7"))

#: A PHONETIC FALLBACK for the wake phrase, because exact spellings do not
#: survive this ASR. MEASURED 2026-08-31 across two recordings: the same spoken
#: "Hej Jeffe" came back as Hejče / Nej Jefem / Hej Gefan / Hejfem / He fe /
#: Hyčef / Hejče — seven spellings, none stable, so a variant list can only ever
#: chase them. Three candidate patterns were scored against 10 wake utterances
#: and 18 ordinary Czech and English lines; this one takes 8 of 10 and raises
#: ZERO false alarms. A looser rule reached 10 of 10 and armed on "Hej, počkej
#: chvilku" — a sentence said to a person in the room. That trade is not close:
#: a missed wake costs a repeat, a false wake starts an action.
#:
#: THE REAL FIX IS A DIFFERENT WORD. An English name is what Czech ASR mangles;
#: an ordinary Czech word is in-distribution and comes back the same every time.
#: This pattern is the bridge until the operator picks one.
WAKE_PATTERN = os.environ.get("EARS_WAKE_PATTERN", r"^[hn][eěy]\S*\s?\S*(ef|če|čef)")
RETENTION_DAYS = int(os.environ.get("EARS_RETENTION_DAYS", "90"))

# ponytail: energy VAD, not silero — silero is MIT and 2 MB but wants torch,
# ~2.5 GB of dependency for it. The ceiling that comment named was hit on day
# one: MEASURED on this operator's microphone, the noise floor sits at RMS 100+
# in EVERY chunk, the median is 300 and the peak 969 — so the fixed 500 crossed
# on 18 of 120 chunks and speech never formed a segment. A fixed threshold
# encodes one room; a floor-relative one calibrates to whatever room it is in,
# which is the knob the physical world needs. EARS_SPEECH_RMS still overrides it
# absolutely, for a room where the tracking itself misbehaves.
SPEECH_RMS = float(os.environ.get("EARS_SPEECH_RMS", "0")) or None
#: Speech is this many times the tracked noise floor. 2.2 sits between the
#: measured floor (300 median) and the measured peak (969) with room on both
#: sides; below ~1.6 the floor itself starts triggering.
SPEECH_OVER_FLOOR = float(os.environ.get("EARS_SPEECH_OVER_FLOOR", "2.2"))
#: The floor tracks the QUIET half of recent history, so a long sentence cannot
#: drag it up and deafen the listener mid-turn.
FLOOR_WINDOW = 200

#: CAPTURE GAIN, and it is the calibration knob a real microphone needs.
#:
#: MEASURED 2026-08-31 and it was the ROOT CAUSE of an ear that heard 14
#: segments and understood none of them: this USB microphone peaks at RMS 969
#: of 32768 — about -30 dBFS — and parakeet HALLUCINATES on near-silence. It
#: produced "Hello, hello, you're fine.", then "Hey Just Coal Kevin.", then a
#: fluent Spanish sentence, for Czech speech. None of that reads as a level
#: problem; it reads as a language-detection problem, and two fixes were aimed
#: at the wrong thing before the level was measured. At volume=8 the same voice
#: peaks at -6 dBFS and the same model writes correct Czech.
#:
#: A FIXED gain and not dynaudnorm: an auto-leveller raises the noise floor
#: during silence, which is exactly what the VAD reads. The threshold is
#: floor-relative, so it follows the gain without retuning.
INPUT_GAIN = float(os.environ.get("EARS_INPUT_GAIN", "8"))

#: How many recent segments the daemon keeps IN STATE for the operator to read.
#:
#: A ROLLING WINDOW, NOT RETENTION. These live only in state.json, are
#: overwritten as they age out, and never reach ~/ears/turns/ — which still
#: holds only ADDRESSED turns, for 90 days. The window exists because "the ear
#: heard 14 segments and none matched" told the operator the phrase was wrong
#: and could not tell them WHAT it wrote, and that gap cost three
#: fixes aimed at the wrong layer. Set 0 to keep nothing.
RECENT_SEGMENTS = int(os.environ.get("EARS_RECENT_SEGMENTS", "8"))

# How long the daemon waits for the FIRST audio byte before deciding the
# microphone is not actually reachable. Generous: launchd starts us before the
# login session is fully up.
MIC_GRACE_S = 20.0
HEARTBEAT_S = 15.0


def normalise(text: str) -> str:
    """Lowercase, punctuation-free, single-spaced — the form phrases match in."""
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", text.lower())).strip()


def rms(chunk: bytes) -> float:
    import numpy as np

    if not chunk:
        return 0.0
    samples = np.frombuffer(chunk, dtype=np.int16).astype(np.float32)
    return float(np.sqrt((samples * samples).mean())) if samples.size else 0.0


class Turn:
    """The state machine: idle -> armed -> submitted.

    Two submit triggers and one of them is a timer, so `silence_left()` exists
    to be DISPLAYED. A countdown nobody can see makes "it submitted" and "it
    never heard me" look the same.
    """

    def __init__(self, wake: str, submit: str, silence_s: float):
        # COMMA-SEPARATED VARIANTS, because the phrase is matched in what the
        # ASR WROTE and Czech transcription of an English name is not stable:
        # "Jeffe", "Jefe", "Džefe" are all the same word to the person saying
        # it. One spelling would make the whole feature fail silently and look
        # like a hearing problem.
        self.wakes = [normalise(w) for w in wake.split(",") if normalise(w)]
        self.submits = [normalise(s) for s in submit.split(",") if normalise(s)]
        self.silence_s = silence_s
        self.armed = False
        self.parts: list[str] = []
        self.last_speech = 0.0

    def feed(self, text: str, now: float) -> str | None:
        """A transcribed speech segment. Returns the finished turn, or None."""
        norm = normalise(text)
        if not norm:
            return None
        self.last_speech = now

        if not self.armed:
            hit = next((w for w in self.wakes if w in norm), None)
            if hit is None and WAKE_PATTERN:
                m = re.search(WAKE_PATTERN, norm)
                if m:
                    hit = norm[: m.end()]
            if hit is None:
                return None
            self.armed = True
            # Everything after the wake phrase is already part of the turn:
            # people say "Hej Jeffe, kolik..." in one breath.
            norm = norm.split(hit, 1)[1].strip()
            if not norm:
                return None

        stop = next((sp for sp in self.submits if sp in norm), None)
        if stop:
            self.parts.append(norm.split(stop, 1)[0].strip())
            return self._finish()

        # A REPEATED WAKE PHRASE IS NOT CONTENT. People re-address a machine
        # that did not visibly react ("hej jeffe... hej jeffe, kolik je hodin"),
        # and leaving it in puts the wake phrase into the transcript half of
        # every training pair.
        for wake in self.wakes:
            norm = norm.replace(wake, " ").strip()
        if norm:
            self.parts.append(norm)
        return None

    def silence_left(self, now: float) -> float:
        if not self.armed:
            return self.silence_s
        return max(0.0, self.silence_s - (now - self.last_speech))

    def tick(self, now: float) -> str | None:
        """Called between segments. Returns the turn when the silence expires."""
        if self.armed and self.silence_left(now) <= 0 and self.parts:
            return self._finish()
        return None

    def _finish(self) -> str:
        text = " ".join(p for p in self.parts if p).strip()
        self.armed = False
        self.parts = []
        return text


# ── retention ────────────────────────────────────────────────────────────────

def prune(days: int = RETENTION_DAYS, now: float | None = None,
          directory: pathlib.Path | None = None) -> list[str]:
    """Delete transcript files older than `days`. Returns what it removed.

    Enforced by the WRITER, deliberately: no second scheduler, no plist, no
    catalog token to lose. What keeps it honest is that a READER
    (tools/caddy-status.py) reports the age of the OLDEST surviving file, so
    retention that silently stops firing shows up as a number nobody likes
    rather than as nothing at all.
    """
    directory = directory or TURNS_DIR
    if not directory.is_dir():
        return []
    cutoff = (now or time.time()) - days * 86400
    removed = []
    for path in sorted(directory.glob("turns-*.jsonl")):
        if path.stat().st_mtime < cutoff:
            path.unlink()
            removed.append(path.name)
    return removed


def _write_state(**fields) -> None:
    """The daemon's heartbeat. A tailed log looks healthy after its writer dies;
    a timestamp does not."""
    HOME.mkdir(parents=True, exist_ok=True)
    state = {}
    if STATE_FILE.is_file():
        try:
            state = json.loads(STATE_FILE.read_text())
        except json.JSONDecodeError:
            state = {}
    state.update(fields)
    state["heartbeat"] = int(time.time())
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))


def _append_turn(text: str, now: float) -> None:
    TURNS_DIR.mkdir(parents=True, exist_ok=True)
    day = dt.datetime.fromtimestamp(now).strftime("%Y-%m-%d")
    line = json.dumps({"at": int(now), "turn": text}, ensure_ascii=False)
    with (TURNS_DIR / f"turns-{day}.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


# ── audio ────────────────────────────────────────────────────────────────────

def _hand_off(turn: str) -> None:
    """Give the turn to caddy, detached.

    DETACHED because the answer takes seconds and the microphone must not go
    deaf while it waits — a listener that stops hearing during every answer
    would lose the follow-up sentence, which is the one people actually say.
    Errors are the launcher's to report: it writes the session row and the gaps.
    """
    launcher = pathlib.Path(__file__).resolve().parent / "caddy.py"
    if not launcher.is_file():
        return
    subprocess.Popen([sys.executable, str(launcher), "--from-voice", "--turn", turn],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)


def _load_model(model_id: str):
    from parakeet_mlx import from_pretrained

    return from_pretrained(model_id)


def _transcribe_pcm(model, pcm: bytes) -> str:
    """PCM in, text out. The temp file lives inside this call and no longer."""
    fd, path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    try:
        with wave.open(path, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(RATE)
            wav.writeframes(pcm)
        return (model.transcribe(path).text or "").strip()
    finally:
        os.unlink(path)


def _drain(proc: subprocess.Popen, sink: "queue.Queue[bytes]") -> threading.Thread:
    """Keep reading ffmpeg while the model is busy.

    MEASURED 2026-08-31 and it overturned an earlier comment in this file: a
    3.6 s clip took 3.36 s to transcribe — roughly ONE times realtime for a
    short segment, not the 60x a long file gets from chunked decoding. The OS
    pipe holds about two seconds, so every transcription was deafening the
    listener for its own duration, and the sentence after "hej jeffe" is
    exactly what fell in that hole.
    """
    def pump() -> None:
        while True:
            chunk = proc.stdout.read(CHUNK_BYTES)
            if not chunk:
                sink.put(b"")
                return
            sink.put(chunk)

    t = threading.Thread(target=pump, daemon=True)
    t.start()
    return t


def _ffmpeg(args: list[str], gain: float = 0.0) -> subprocess.Popen:
    """`gain` applies to the MICROPHONE only — a file already carries its own
    level, and amplifying it would corrupt the one path used for measurement."""
    filt = ["-af", f"volume={gain}"] if gain and gain != 1.0 else []
    return subprocess.Popen(
        ["ffmpeg", "-loglevel", "error", "-nostats", *args, *filt,
         "-ac", "1", "-ar", str(RATE), "-f", "s16le", "-"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def cmd_file(args) -> int:
    model = _load_model(args.model)
    started = time.time()
    proc = _ffmpeg(["-i", args.file])
    pcm, err = proc.communicate()
    if proc.returncode != 0:
        print(f"ffmpeg could not read {args.file}: {err.decode()[:200]}", file=sys.stderr)
        return 2
    text = _transcribe_pcm(model, pcm)
    print(json.dumps({
        "file": args.file,
        "text": text,
        "audio_seconds": round(len(pcm) / (RATE * 2), 2),
        "wall_seconds": round(time.time() - started, 2),
        "model": args.model,
    }, ensure_ascii=False))
    return 0


def _run_loop(args, daemon: bool) -> int:
    removed = prune(args.retention)
    _write_state(mode="daemon" if daemon else "foreground", mic_ok=None,
                 started=int(time.time()), pruned=len(removed), turns_today=0,
                 model=args.model, wake=args.wake, retention_days=args.retention,
                 gain=args.gain)

    # ORDER IS LOAD-BEARING: the model (and its ~600 MB first-run download)
    # resolves BEFORE the microphone opens, so the wait costs no audio. Per
    # segment, transcription runs at roughly 60x realtime, so the ~2 s the pipe
    # buffers is ample. ponytail: if a slower model ever lands here, move the
    # read into a thread rather than growing the buffer.
    model = _load_model(args.model)
    turn = Turn(args.wake, args.submit, args.silence)
    proc = _ffmpeg(["-f", "avfoundation", "-i", args.input], gain=args.gain)
    if not daemon:
        print(f"listening — say '{args.wake}' to open a turn, "
              f"'{args.submit}' or {args.silence:.0f}s of silence to close it",
              file=sys.stderr)

    speech, quiet_chunks = b"", 0
    # 1.2 s, MEASURED, not chosen. At 0.6 s the same 10.6 s recording split into
    # three fragments — "Nej Jefem, tohle je první test." / "Relativně zdalky." /
    # "bych se tě zeptat, kolik." — and short fragments are where this model
    # hallucinates: a 0.3 s one came back "Mm-hmm." in English. At 1.2 s the
    # same audio became two whole clauses, and at 2.0 s one correct sentence.
    # Longer is better for accuracy and worse for latency; 1.2 is the knee.
    quiet_needed = int(float(os.environ.get("EARS_SILENCE_GAP", "1.2")) * 1000 / CHUNK_MS)
    started, heard_any = time.time(), False
    last_beat, last_prune, turns_today = 0.0, time.time(), 0
    floor: list[float] = []
    segments, wake_misses, last_segment_at = 0, 0, 0.0
    recent: list[dict] = []
    # INITIALISED BEFORE THE LOOP because the heartbeat reports it and fires on
    # a timer, not on a chunk: the first beat arrived 15 s in, read a threshold
    # the first chunk had not yet computed, and the daemon died with
    # UnboundLocalError. launchd's KeepAlive turned that into a visible restart
    # loop rather than a silent absence, which is the only reason it was cheap
    # to find — but a name used before assignment is not a thing a loop should
    # be discovering for us.
    threshold = 0.0

    audio: "queue.Queue[bytes]" = queue.Queue()
    _drain(proc, audio)

    try:
        while True:
            chunk = audio.get()
            now = time.time()

            if not chunk:
                # ffmpeg is gone. THE distinguishing case: no audio ever arrived,
                # which on macOS means the microphone was refused rather than
                # quiet — a launchd agent has no window to prompt in.
                err = (proc.stderr.read() or b"").decode()[:300]
                _write_state(mic_ok=False, stopped=int(now),
                             detail=("no audio from the input — microphone denied or absent"
                                     if not heard_any else "capture ended")
                                    + (f": {err.strip()}" if err.strip() else ""))
                return 3 if not heard_any else 0

            # A zero-filled buffer is not evidence of a microphone: a denied
            # device can stream perfect silence forever. Only a non-zero sample
            # proves something is actually being heard.
            if not heard_any and chunk.strip(b"\x00"):
                heard_any = True
                _write_state(mic_ok=True, detail="")

            if not heard_any and now - started > MIC_GRACE_S:
                _write_state(mic_ok=False, stopped=int(now),
                             detail=f"no audio in {MIC_GRACE_S:.0f}s — microphone "
                                    "denied or silent (a launchd agent cannot prompt "
                                    "for it; grant it in System Settings)")
                return 3

            if now - last_beat >= HEARTBEAT_S:
                _write_state(armed=turn.armed, turns_today=turns_today,
                             silence_left=round(turn.silence_left(now), 1),
                             recent=recent,
                             segments=segments, wake_misses=wake_misses,
                             threshold=round(threshold),
                             last_segment_age=(round(now - last_segment_at)
                                               if last_segment_at else None))
                last_beat = now
            if now - last_prune >= 3600:
                prune(args.retention)
                last_prune = now

            level = rms(chunk)
            floor.append(level)
            if len(floor) > FLOOR_WINDOW:
                floor.pop(0)
            # The quiet half of recent history IS the floor: a sentence occupies
            # the loud half and therefore cannot raise its own threshold.
            quiet = sorted(floor)[: max(1, len(floor) // 2)]
            threshold = SPEECH_RMS or max(
                60.0, (sum(quiet) / len(quiet)) * SPEECH_OVER_FLOOR)

            if level >= threshold:
                speech += chunk
                quiet_chunks = 0
                continue

            done = None
            if speech:
                quiet_chunks += 1
                if quiet_chunks < quiet_needed:
                    speech += chunk
                    continue
                speech_at_cut = speech
                text = _transcribe_pcm(model, speech)
                speech, quiet_chunks = b"", 0
                segments += 1
                last_segment_at = now
                if args.verbose and text:
                    print(f"  … {text}", file=sys.stderr)
                if RECENT_SEGMENTS:
                    # AN EMPTY TRANSCRIPTION IS INFORMATION, and dropping it
                    # emptied the window exactly when the operator most needed
                    # it: `segments: 1, recent: []` says the ear triggered and
                    # the model returned nothing, which is a different problem
                    # from not triggering. The DURATION comes along so a 0.2 s
                    # blip is not mistaken for a sentence.
                    recent.append({"at": int(now), "text": text,
                                   "secs": round(len(speech_at_cut) / (RATE * 2), 1)})
                    del recent[:-RECENT_SEGMENTS]
                was_armed = turn.armed
                done = turn.feed(text, now)
                if not was_armed and not turn.armed:
                    # HEARD AND NOT ADDRESSED. Counted, never stored: the count
                    # is what tells the operator "the ear works, the phrase did
                    # not match" instead of leaving silence to mean both. The
                    # words themselves are the room's, and stay unrecorded.
                    wake_misses += 1
            elif turn.armed:
                if not daemon:
                    print(f"\r  armed · submitting in {turn.silence_left(now):4.1f}s ",
                          end="", file=sys.stderr)
                done = turn.tick(now)

            if done:
                turns_today += 1
                _append_turn(done, now)
                if args.autorun:
                    _hand_off(done)
                _write_state(armed=False, turns_today=turns_today,
                             last_turn_at=int(now))
                if not daemon:
                    print("", file=sys.stderr)
                    print(json.dumps({"turn": done, "at": int(now)}, ensure_ascii=False),
                          flush=True)
    except KeyboardInterrupt:
        return 0
    finally:
        proc.terminate()
        _write_state(stopped=int(time.time()))
    return 0


def cmd_devices(_args) -> int:
    proc = subprocess.run(
        ["ffmpeg", "-f", "avfoundation", "-list_devices", "true", "-i", ""],
        capture_output=True, text=True)
    print(proc.stderr.strip())
    return 0


def cmd_selfcheck(_args) -> int:
    """Segmentation and retention, with no model, no microphone, no network."""
    t = Turn("hej jeffe", "makej jeffe", 7)
    assert t.feed("Kolik je hodin?", 0) is None, "unarmed speech must not open a turn"
    assert t.feed("Hej, Jeffe, kolik", 1) is None, "wake phrase alone does not submit"
    assert t.armed, "the wake phrase did not arm the turn"
    assert t.feed("je hodin, makej Jeffe!", 2) == "kolik je hodin", \
        "the submit phrase must close the turn and be stripped from it"
    assert not t.armed, "a submitted turn must disarm"

    t2 = Turn("hej jeffe", "makej jeffe", 7)
    t2.feed("hej jeffe zaloz partnera", 100)
    assert t2.tick(103) is None, "the timer fired early"
    assert t2.tick(108) == "zaloz partnera", "the silence timer did not submit"

    t5 = Turn("hej jeffe", "makej jeffe", 7)
    t5.feed("hej jeffe hej jeffe kolik je hodin", 0)
    assert t5.parts == ["kolik je hodin"], \
        f"a repeated wake phrase leaked into the turn: {t5.parts}"

    t3 = Turn("hej jeffe, hej jefe", "makej jeffe", 7)
    assert t3.feed("Hej, Jefe, uklid", 0) is None or t3.armed, \
        "a declared wake VARIANT must arm the turn"
    assert t3.armed, "the second wake spelling did not arm"

    t4 = Turn("hej jeffe", "makej jeffe", 7)
    assert t4.silence_left(0) == 7, "an idle turn must not report a countdown"
    assert not b"\x00\x00\x00".strip(b"\x00"), \
        "silence must not read as audio — this is the denied-microphone test"
    assert normalise("Hej, JEFFE!") == "hej jeffe", "normalisation drifted"

    # Retention, against real files in a throwaway directory: a horizon that is
    # only asserted in prose is the one this estate found never firing.
    with tempfile.TemporaryDirectory() as tmp:
        d = pathlib.Path(tmp)
        now = time.time()
        old, young = d / "turns-2026-01-01.jsonl", d / "turns-2026-08-31.jsonl"
        old.write_text("{}\n")
        young.write_text("{}\n")
        os.utime(old, (now - 91 * 86400, now - 91 * 86400))
        os.utime(young, (now - 3 * 86400, now - 3 * 86400))
        removed = prune(90, now=now, directory=d)
        assert removed == [old.name], f"retention removed {removed}, expected the 91-day file"
        assert young.exists(), "retention deleted a file inside the horizon"

    # THE ASR'S LANGUAGE GUESS, which produced zero turns from a working ear:
    # the same phrase written in English must still arm the turn.
    t6 = Turn("hej jeffe, hey jeff", "makej jeffe, makej jeff", 7)
    assert t6.feed("Hey, Jeff, how many open highs?", 0) is None
    assert t6.armed, "an English transliteration of the wake phrase did not arm"
    assert t6.feed("makej Jeff", 1) == "how many open highs", \
        "the English submit phrase did not close the turn"

    # The floor-relative threshold, against the measured room: floor 300,
    # peak 969. A fixed 500 crossed on 15 percent of chunks and never formed a
    # segment; 300 * 2.2 = 660 must still admit the peak and refuse the floor.
    quiet_mean, peak = 300.0, 969.0
    threshold = max(60.0, quiet_mean * SPEECH_OVER_FLOOR)
    assert threshold < peak, f"the tracked threshold {threshold} deafens the measured peak {peak}"
    assert threshold > quiet_mean, f"the threshold {threshold} sits under the noise floor"

    # THE PHONETIC FALLBACK, against the very spellings this ASR produced and
    # the ordinary sentences it must NOT arm on. Both lists are measured, not
    # imagined — they are transcripts from the two test recordings.
    heard_as = ["hejče tohle je první test", "nej jefem tohle je test",
                "hej gefan tohle je test", "hyčef tohle je test",
                "hejče tohle je test", "hej jeffe kolik je hodin"]
    must_not = ["hele to je jedno", "hej počkej chvilku", "nejde to",
                "kolik je hodin v brně", "chtěl bych se tě zeptat",
                "tohle je první test relativně z dálky", "nevím co s tím"]
    for said in heard_as:
        t = Turn("hej jeffe", "makej jeffe", 7)
        t.feed(said, 0)
        assert t.armed, f"the phonetic fallback missed a real wake: {said!r}"
    for said in must_not:
        t = Turn("hej jeffe", "makej jeffe", 7)
        t.feed(said, 0)
        assert not t.armed, f"FALSE WAKE on ordinary speech: {said!r}"

    print("selfcheck OK — 4 turns, 6 wake spellings, 7 refusals, "
          "1 retention sweep, 1 threshold")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--file", help="transcribe an audio file and exit")
    ap.add_argument("--listen", action="store_true", help="listen in the foreground")
    ap.add_argument("--daemon", action="store_true", help="listen as the launchd agent does")
    ap.add_argument("--devices", action="store_true", help="list ffmpeg capture devices")
    ap.add_argument("--selfcheck", action="store_true", help="exercise the logic offline")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--wake", default=DEFAULT_WAKE)
    ap.add_argument("--submit", default=DEFAULT_SUBMIT)
    ap.add_argument("--silence", type=float, default=DEFAULT_SILENCE)
    ap.add_argument("--retention", type=int, default=RETENTION_DAYS)
    ap.add_argument("--input", default=os.environ.get("EARS_INPUT", ":0"),
                    help="avfoundation input spec (default :0, the system input)")
    ap.add_argument("--gain", type=float, default=INPUT_GAIN,
                    help="capture gain; a quiet mic makes the ASR hallucinate")
    ap.add_argument("--verbose", action="store_true", help="print every segment heard")
    ap.add_argument("--autorun", action="store_true",
                    default=os.environ.get("EARS_AUTORUN", "") == "1",
                    help="hand each finished turn to caddy (default: EARS_AUTORUN)")
    args = ap.parse_args()

    if args.selfcheck:
        return cmd_selfcheck(args)
    if args.devices:
        return cmd_devices(args)
    if args.file:
        return cmd_file(args)
    if args.listen or args.daemon:
        return _run_loop(args, daemon=args.daemon)
    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
