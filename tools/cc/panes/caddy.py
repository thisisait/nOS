"""tools/caddy-status.py — the caddy: can it answer, is it listening, what did it hear.

The pane an operator glances at before speaking to the estate. Blocked states
first, then the last turns — because "the caddy did not answer" and "the microphone
was refused" look identical from where you are standing, and only one of them
is fixable in System Settings.
"""
import os
import pathlib
import time

ID, LABEL, TITLE = "caddy", "Caddy", "the assistant, the ear, and what it heard"
READER = "tools/caddy-status.py"
# The fastest reader pane in the set: the transcript half moves in SECONDS, and
# a five-second-old answer to "did it hear me" is not an answer. Still a RE-RUN
# of the reader on every tick, never a tail — the rule the whole control centre
# is built on does not bend for latency.
REFRESH = 5
COLUMNS = ["state", "part", "detail"]
DEMO = {
    "halves": {
        "jeff": {"exists": True, "backend": "ollama", "armed": True,
                 "model": "qwen3:14b", "env_readable": True, "detail": ""},
        "jeff-cloud": {"exists": True, "backend": "minimax", "armed": True,
                       "model": "MiniMax-M2.7", "env_readable": True, "detail": ""},
    },
    "armed": ["ollama", "minimax"],
    "listener": {"loaded": True, "mic_ok": True, "armed": False, "turns_today": 3,
                 "heartbeat_age": 8, "stale": False, "retention_days": 90, "detail": "",
                 "segments": 41, "wake_misses": 38, "threshold": 660,
                 "last_segment_age": 12},
    "transcripts": {"readable": True, "files": 12, "oldest_days": 11.4, "detail": "",
                    "recent": [{"at": 1788130000, "turn": "kolik je otevrenych highs"}]},
    "settings": {"readable": True, "detail": "", "rows": [{"slug": "mode", "value": "local"}]},
    "sessions": {"readable": True, "detail": "", "count": 0, "recent": []},
    "ear": {"installed": True},
}


def build_rows(data):
    # The reader owns the verdict logic; importing it here would make the pane a
    # second implementation of it, and two spellings of "is Jeff ready" is
    # exactly the drift this estate keeps paying for. So re-derive nothing.
    import importlib.util
    import pathlib

    reader = pathlib.Path(__file__).resolve().parents[3] / "tools" / "caddy-status.py"
    spec = importlib.util.spec_from_file_location("caddy_status", reader)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.build_rows(data)


def detail(row, data):
    # KEYED ON WHAT build_rows ACTUALLY EMITS. The first version keyed the two
    # halves on "caddy"/"caddy-cloud" while the reader emits the PERSONA
    # (jeff/jeff-cloud), so both rows always showed "—": an act-map matching
    # nothing, which is the shape a reader is supposed to catch, not create.
    part = row.get("part", "")
    halves = set(data.get("halves") or {})
    out = dict(row)
    if part in halves:
        out["act"] = ("runs today — every turn it serves leaves the machine"
                      if part.endswith("-cloud")
                      else "arm ollama: ollama_enabled + ollama_model in config.yml, then --tags ears")
        return out
    if part_state := row.get("state"):
        if part_state in ("HEARD", "TURN"):
            # The row truncates at 110 characters; Enter is where the rest of
            # the sentence lives.
            out["act"] = ("addressed — this became a turn" if part_state == "TURN"
                          else "heard, not addressed to the caddy")
            return out
    out["act"] = {
        "listener": {
            "OFF": "set ears_always_listen: true in config.yml, then --tags jeff",
            "DENIED": "System Settings > Privacy & Security > Microphone, then --tags jeff",
            "BROKEN": "check ~/ears/log/launchd.err.log — the process stopped writing",
            "UNHEARD": "say the wake phrase; if it still misses, ears-listen --listen --verbose prints what it wrote",
        }.get(row.get("state"), "listening"),
        "transcripts": "~/ears/turns/*.jsonl · pruned by the listener at the horizon",
        "settings": "seeded by pazny.keap from state/fixtures/caddy.seed.yml",
        "sessions": "written by the caddy's runs; empty until the first one",
        "ear": "parakeet lives in ~/ears/venv — installed by a converge, probed there",
    }.get(row.get("part"), "—")
    return out


def meta(data):
    ear = data.get("listener", {})
    return {
        # The app paints a full-width red bar on this one.
        "recording": bool(ear.get("loaded") and ear.get("mic_ok") is not False),
        "armed_backends": data.get("armed", []),
        "retention_days": ear.get("retention_days"),
        "transcript_files": (data.get("transcripts") or {}).get("files"),
    }


LABEL_ID = "eu.thisisait.nos.ears-listen"
PAUSED = pathlib.Path.home() / "ears" / "paused"


def toggle(data):
    """`s` — stop or resume the microphone, NOW, without a converge.

    THE RUNTIME ONLY. `ears_always_listen` in config.yml is the DECLARATION and
    this does not touch it, so the next converge re-asserts whatever the
    operator declared. A marker file records that the pause was deliberate, so
    the reader can tell PAUSED apart from "never started" — two states that
    would otherwise both render as a job that is not loaded.

    Requiring a converge to stop being recorded would make the fastest way out
    of a private conversation an edit to YAML. That is the whole argument for
    the one action in this control centre.
    """
    import subprocess

    target = f"gui/{os.getuid()}"
    listening = bool((data.get("listener") or {}).get("loaded"))
    if listening:
        subprocess.run(["launchctl", "bootout", f"{target}/{LABEL_ID}"],
                       capture_output=True)
        PAUSED.parent.mkdir(parents=True, exist_ok=True)
        PAUSED.write_text(f"paused from nos-cc at {int(time.time())}\n")
        return "[b]microphone STOPPED[/] — a converge will start it again"
    plist = pathlib.Path.home() / f"Library/LaunchAgents/{LABEL_ID}.plist"
    if not plist.is_file():
        return f"[b red]no plist at {plist}[/] — converge with install_ears first"
    run = subprocess.run(["launchctl", "bootstrap", target, str(plist)],
                         capture_output=True, text=True)
    PAUSED.unlink(missing_ok=True)
    return ("[b]microphone STARTED[/]" if run.returncode == 0
            else f"[b red]launchctl: {run.stderr.strip()[:80]}[/]")
