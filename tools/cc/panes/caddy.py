"""tools/caddy-status.py — the caddy: can it answer, is it listening, what did it hear.

The pane an operator glances at before speaking to the estate. Blocked states
first, then the last turns — because "the caddy did not answer" and "the microphone
was refused" look identical from where you are standing, and only one of them
is fixable in System Settings.
"""
ID, LABEL, TITLE = "caddy", "Caddy", "the assistant, the ear, and what it heard"
READER = "tools/caddy-status.py"
# The transcript half moves in seconds, so this is the fastest reader pane in
# the set. It is still a RE-RUN of the reader, never a tail.
REFRESH = 20
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
                 "heartbeat_age": 8, "stale": False, "retention_days": 90, "detail": ""},
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
    out["act"] = {
        "listener": {
            "OFF": "set ears_always_listen: true in config.yml, then --tags jeff",
            "DENIED": "System Settings > Privacy & Security > Microphone, then --tags jeff",
            "BROKEN": "check ~/ears/log/launchd.err.log — the process stopped writing",
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
        "armed_backends": data.get("armed", []),
        "retention_days": ear.get("retention_days"),
        "transcript_files": (data.get("transcripts") or {}).get("files"),
    }
