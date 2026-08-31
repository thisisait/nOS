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
#: The tmux window the listener runs in, inside the control centre's own
#: session. NOT launchd, and the reason is measured (2026-08-31):
#:
#: ffmpeg is the process that opens the microphone, and macOS attributes the
#: TCC grant to the RESPONSIBLE process. Started from a terminal, that is
#: Terminal, which has the grant. Started by launchd, ffmpeg is responsible for
#: itself, has no grant — and macOS does not deny it. It hands over a stream
#: with no speech in it. Measured with identical arguments: terminal peak
#: 19898 and correct Czech; launchd, a flat noise floor and empty transcripts,
#: while the daemon reported `mic_ok: true` because hiss is not silence.
#:
#: So the ear runs where the grant already is. The .app bundle that would give
#: launchd its own grantable identity is roadmap row `ears-app-bundle`.
WINDOW = "ears"


def _tmux(*args, session=None):
    import os as _os
    import subprocess
    sess = session or _os.environ.get("NOS_CC_SESSION", "nos-cc")
    return subprocess.run(["tmux", *[a.replace("{s}", sess) for a in args]],
                          capture_output=True, text=True)


def toggle(data):
    """`s` — stop or start the microphone, NOW, without a converge.

    It runs the listener in a tmux window of this control centre's session,
    because that is where the microphone grant lives (see WINDOW above). The
    window survives the terminal that opened it, and it is VISIBLE — a live
    microphone should be something you can look at, not only infer.

    Requiring a converge to stop being recorded would make the fastest way out
    of a private conversation an edit to YAML. That is the whole argument for
    the one action in this control centre.
    """
    running = bool((data.get("listener") or {}).get("loaded"))
    if running:
        _tmux("kill-window", "-t", "={s}:" + WINDOW)
        return "[b]microphone STOPPED[/] — the ears window is gone"

    if _tmux("has-session", "-t", "={s}").returncode != 0:
        return ("[b red]no nos-cc session[/] — the ear runs inside it, "
                "because that is where the microphone grant is")
    cmd = str(pathlib.Path.home() / "ears/venv/bin/python") + " " + \
        str(pathlib.Path.home() / "ears/ears-listen.py") + " --listen --autorun --verbose"
    run = _tmux("new-window", "-d", "-t", "={s}", "-n", WINDOW, cmd)
    return ("[b]microphone STARTED[/] in the `ears` window" if run.returncode == 0
            else f"[b red]tmux: {run.stderr.strip()[:80]}[/]")
