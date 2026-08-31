#!/usr/bin/env python3
"""The caddy — the operator's master-session assistant, and whether either half can actually run.

WHY A READER AND NOT A NOTE IN A DOC. The caddy has two halves that fail in opposite
directions, and neither failure is visible from the repo: the local half is
refuses when ollama is disarmed or its model id is blank; its cloud twin sends
the operator's sentence abroad and works precisely when the operator would
most want to be reminded of that. A file in git says what was DECLARED. This
says what the deployed daemon was handed.

THE FIVE SOURCES, and each is read rather than inferred:

  * `files/anatomy/agents/<caddy>/agent.yml`  — the DECLARED backend (git)
  * the deployed wing launchd plist        — NOS_ARMED_BACKENDS and the model
                                             ids the RUNTIME holds, which is the
                                             only place arming is a fact
  * the live KEAP tables                   — whether the definitions were
                                             applied, and what Jeff has run
  * `launchctl` + `~/ears/state.json`      — whether the ear is loaded, and
                                             whether it is HEARING anything;
                                             a denied microphone leaves a
                                             perfectly healthy-looking process
  * `~/ears/turns/`                        — the last turns, and the age of the
                                             OLDEST file, which is the only
                                             thing that proves the 90-day
                                             retention sweep still fires

It acts on nothing: no seeding, no arming, no session. Exit 0 always, including
when everything is unknown — reporting IS its job, and an unreadable source is
reported as UNKNOWN, never as green.

Usage:
    tools/caddy-status.py            # the rows
    tools/caddy-status.py --json     # for the pane
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import plistlib
import subprocess
import sys
import time
import urllib.error
import urllib.request

REPO = pathlib.Path(__file__).resolve().parents[1]
KEAP = "http://127.0.0.1:8091/api/tables"
HEADERS = {
    "X-Authentik-Username": "akadmin",
    "X-Authentik-Groups": "nos-providers,nos-admins",
    "Content-Type": "application/json",
}
PLIST = pathlib.Path.home() / "Library/LaunchAgents/eu.thisisait.nos.wing.plist"
AGENTS = REPO / "files/anatomy/agents"


def _get(url: str):
    req = urllib.request.Request(url, headers=HEADERS, method="GET")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def _table_rows(table_id: str):
    """(rows, detail). rows is None when the table could not be read at all."""
    try:
        return _get(f"{KEAP}/{table_id}/rows?limit=200")["data"]["rows"], ""
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None, "declared in git, not applied to KEAP"
        return None, f"HTTP {exc.code}"
    except Exception as exc:                                    # noqa: BLE001
        return None, f"{type(exc).__name__}: {exc}"[:90]


def _runtime_env() -> tuple[dict, str]:
    """What the DEPLOYED wing daemon was handed. Not what the repo declares."""
    if not PLIST.is_file():
        return {}, f"no plist at {PLIST}"
    try:
        env = plistlib.loads(PLIST.read_bytes()).get("EnvironmentVariables", {})
    except Exception as exc:                                    # noqa: BLE001
        return {}, f"unreadable plist: {type(exc).__name__}"
    keep = ("NOS_ARMED_BACKENDS", "NOS_LOCAL_MODEL", "NOS_MINIMAX_MODEL")
    return {k: (env.get(k) or "") for k in keep}, ""


def _declared_backend(agent: str) -> str:
    """The agent's own `model.backend`, read from the file, not remembered."""
    path = AGENTS / agent / "agent.yml"
    if not path.is_file():
        return ""
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if stripped.startswith("backend:"):
            return stripped.split(":", 1)[1].strip()
    return ""


#: The listener's runtime tree. Read, never written — this file only reports.
EARS_HOME = pathlib.Path.home() / "ears"
TURNS_DIR = EARS_HOME / "turns"
STATE_FILE = EARS_HOME / "state.json"
LISTENER_LABEL = "eu.thisisait.nos.ears-listen"
#: A heartbeat older than this means the process is gone or wedged. The daemon
#: writes one every 15 s, so three minutes is not a race — it is a verdict.
HEARTBEAT_STALE_S = 180


def _persona() -> str:
    """Whose caddy this is. The settings table when it answers, else the
    committed fixture default — never a name baked into the reader."""
    fixture = REPO / "state/fixtures/caddy.seed.yml"
    try:
        rows = _get(f"{KEAP}/caddy/rows?limit=50")["data"]["rows"]
        for row in rows:
            if row["values"].get("slug") == "agent" and row["values"].get("value"):
                return row["values"]["value"]
    except Exception:                                           # noqa: BLE001
        pass
    for line in fixture.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith('value: "') and "jeff" in line:
            return line.split('"')[1]
    return "jeff"


def _ear() -> dict:
    """Is parakeet installed WHERE THE LISTENER RUNS.

    The first version asked `importlib.util.find_spec` in THIS interpreter,
    which is not the one that matters: the role installs parakeet into
    ~/ears/venv, so a perfectly converged estate reported `ear: ABSENT` for
    ever. The estate's own rule, inverted — the detector was reading the wrong
    artifact — and it would have declared the converge's main deliverable
    missing on the day it landed.
    """
    python = EARS_HOME / "venv" / "bin" / "python"
    if not python.is_file():
        return {"installed": False, "detail": f"no venv at {python.parent.parent}"}
    probe = subprocess.run([str(python), "-c", "import parakeet_mlx"],
                           capture_output=True, text=True)
    return {"installed": probe.returncode == 0,
            "detail": "" if probe.returncode == 0
                      else (probe.stderr.strip().splitlines() or [""])[-1][:90]}


def _listener() -> dict:
    """Is the ear actually listening — and if not, is that OFF or DENIED?

    Three sources, because each can lie alone: launchctl says whether a job is
    LOADED (a loaded job can still be exiting 3 in a loop), state.json says what
    the process last knew, and its heartbeat says whether that knowledge is
    current. A tailed log would have said "healthy" for all three cases.
    """
    # WHERE THE EAR ACTUALLY RUNS, and it is two places for one measured
    # reason: launchd gets a TCC-silent microphone (see the pane module), so
    # the listener lives in a tmux window where the grant already is. A launchd
    # job that IS loaded is reported, and reported as deaf.
    session = os.environ.get("NOS_CC_SESSION", "nos-cc")
    in_tmux = subprocess.run(
        ["tmux", "list-windows", "-t", f"={session}", "-F", "#{window_name}"],
        capture_output=True, text=True)
    windowed = in_tmux.returncode == 0 and "ears" in in_tmux.stdout.split()
    daemonised = subprocess.run(
        ["launchctl", "print", f"gui/{os.getuid()}/{LISTENER_LABEL}"],
        capture_output=True, text=True).returncode == 0
    loaded = windowed or daemonised

    state, detail = {}, ""
    if STATE_FILE.is_file():
        try:
            state = json.loads(STATE_FILE.read_text())
        except json.JSONDecodeError as exc:
            detail = f"state.json unreadable: {exc}"
    elif loaded:
        detail = "loaded, but it has never written state.json"

    beat = state.get("heartbeat")
    return {
        "loaded": loaded,
        "mic_ok": state.get("mic_ok"),
        "armed": bool(state.get("armed")),
        "turns_today": state.get("turns_today", 0),
        "segments": state.get("segments", 0),
        "wake_misses": state.get("wake_misses", 0),
        "threshold": state.get("threshold"),
        "last_segment_age": state.get("last_segment_age"),
        "recent": state.get("recent") or [],
        "heartbeat_age": int(time.time() - beat) if beat else None,
        "stale": bool(beat) and (time.time() - beat) > HEARTBEAT_STALE_S,
        "retention_days": state.get("retention_days"),
        "detail": detail or state.get("detail", ""),
        "paused": (EARS_HOME / "paused").is_file(),
        "where": "tmux" if windowed else ("launchd" if daemonised else ""),
    }


def _transcripts(limit: int = 5) -> dict:
    """Recent turns, and the age of the OLDEST file — which is what proves the
    retention sweep is still running. A horizon nobody reads back is how this
    estate ended up with one measured in days that could never fire."""
    if not TURNS_DIR.is_dir():
        return {"readable": False, "detail": f"no {TURNS_DIR}", "recent": [], "files": 0}
    files = sorted(TURNS_DIR.glob("turns-*.jsonl"))
    recent: list[dict] = []
    for path in reversed(files[-3:]):
        for line in reversed(path.read_text(encoding="utf-8").splitlines()):
            try:
                recent.append(json.loads(line))
            except json.JSONDecodeError:
                continue
            if len(recent) >= limit:
                break
        if len(recent) >= limit:
            break
    oldest = min((p.stat().st_mtime for p in files), default=None)
    return {
        "readable": True,
        "files": len(files),
        "oldest_days": round((time.time() - oldest) / 86400, 1) if oldest else None,
        "recent": recent,
        "detail": "",
    }


def collect() -> dict:
    env, env_detail = _runtime_env()
    armed = [b for b in (env.get("NOS_ARMED_BACKENDS") or "").split() if b]

    halves = {}
    # The persona this estate ships. Read from the settings table the day a
    # second tenant needs a different one; hardcoded here would be the same
    # defect the rename fixed one storey down.
    for agent, model_key in ((_persona(), "NOS_LOCAL_MODEL"),
                             (_persona() + "-cloud", "NOS_MINIMAX_MODEL")):
        backend = _declared_backend(agent)
        halves[agent] = {
            "exists": (AGENTS / agent / "agent.yml").is_file(),
            "backend": backend,
            "armed": backend in armed if backend else None,
            "model": env.get(model_key, ""),
            "env_readable": not env_detail,
            "detail": env_detail,
        }

    settings, settings_detail = _table_rows("caddy")
    sessions, sessions_detail = _table_rows("caddy-sessions")

    return {
        "halves": halves,
        "armed": armed,
        "listener": _listener(),
        "transcripts": _transcripts(),
        "settings": {
            "readable": settings is not None,
            "detail": settings_detail,
            "rows": [r["values"] for r in settings or []],
        },
        "sessions": {
            "readable": sessions is not None,
            "detail": sessions_detail,
            "count": len(sessions or []),
            "recent": [r["values"] for r in (sessions or [])[-5:]],
        },
        "ear": _ear(),
    }


def build_rows(data: dict) -> list[dict]:
    rows = []

    for agent, half in data["halves"].items():
        if not half["exists"]:
            rows.append({"state": "ABSENT", "part": agent, "detail": "no agent.yml"})
            continue
        if not half["env_readable"]:
            rows.append({"state": "UNKNOWN", "part": agent,
                         "detail": f"backend {half['backend']} — {half['detail']}"})
            continue
        if not half["armed"]:
            rows.append({"state": "DISARMED", "part": agent,
                         "detail": f"backend `{half['backend']}` not in NOS_ARMED_BACKENDS "
                                   f"({', '.join(data['armed']) or 'none armed'})"})
        elif not half["model"]:
            rows.append({"state": "BROKEN", "part": agent,
                         "detail": f"backend `{half['backend']}` armed with a BLANK model id "
                                   f"— resolution refuses rather than sending it"})
        else:
            rows.append({"state": "READY", "part": agent,
                         "detail": f"backend `{half['backend']}` -> {half['model']}"})

    settings = data["settings"]
    if not settings["readable"]:
        rows.append({"state": "UNKNOWN", "part": "settings",
                     "detail": settings["detail"] or "unreadable"})
    else:
        mode = next((r.get("value") for r in settings["rows"]
                     if r.get("slug") == "mode"), None)
        rows.append({"state": "READY" if mode else "UNKNOWN", "part": "settings",
                     "detail": f"{len(settings['rows'])} row(s)"
                               + (f", mode={mode}" if mode else ", no `mode` row")})

    sessions = data["sessions"]
    if not sessions["readable"]:
        rows.append({"state": "UNKNOWN", "part": "sessions",
                     "detail": sessions["detail"] or "unreadable"})
    else:
        last = sessions["recent"][-1] if sessions["recent"] else None
        rows.append({"state": "READY", "part": "sessions",
                     "detail": f"{sessions['count']} session(s)"
                               + (f" · last {last.get('mode')}/{last.get('status')}"
                                  if last else " — none yet")})

    rows.append({
        "state": "READY" if data["ear"]["installed"] else "ABSENT",
        "part": "ear",
        "detail": "parakeet-mlx importable in ~/ears/venv" if data["ear"]["installed"]
        else (data["ear"].get("detail")
              or "parakeet-mlx not importable in ~/ears/venv")
             + " — dictation cannot run (install belongs to a converge)",
    })

    # The listener, and the four ways it can be not-listening. They are told
    # apart deliberately: OFF is a decision, DENIED is macOS refusing a
    # microphone a launchd agent cannot prompt for, STALE is a process that
    # stopped writing, and LISTENING is the only one that means it works.
    ear = data["listener"]
    if not ear["loaded"] and ear.get("paused"):
        # STOPPED ON PURPOSE, from the pane, and the declaration still says
        # listen — so a converge brings it back. Two states that would both
        # render as "not loaded" if the marker did not exist.
        rows.append({"state": "PAUSED", "part": "listener",
                     "detail": "stopped from nos-cc — press s to resume; "
                               "a converge resumes it too (config.yml still declares it)"})
    elif not ear["loaded"]:
        rows.append({"state": "OFF", "part": "listener",
                     "detail": "not running — press s in nos-cc to start it in the ears "
                               "window (launchd cannot hear: TCC)"})
    elif ear["mic_ok"] is False:
        rows.append({"state": "DENIED", "part": "listener",
                     "detail": f"loaded and hearing NOTHING — {ear['detail'] or 'microphone refused'}. "
                               "System Settings > Privacy & Security > Microphone"})
    elif ear["stale"]:
        rows.append({"state": "BROKEN", "part": "listener",
                     "detail": f"no heartbeat for {ear['heartbeat_age']}s — the process is gone or wedged"})
    elif ear["mic_ok"] is None:
        rows.append({"state": "UNKNOWN", "part": "listener",
                     "detail": ear["detail"] or "loaded; no audio seen yet (starting up)"})
    elif ear["segments"] and not ear["turns_today"]:
        # THE STATE THAT USED TO LOOK LIKE SUCCESS. The ear hears, transcribes,
        # and nothing it heard was addressed to it — which is a working mic and
        # a phrase that does not match, not "waiting for you to speak".
        rows.append({"state": "UNHEARD", "part": "listener",
                     "detail": f"heard {ear['segments']} speech segment(s), "
                               f"NONE matched the wake phrase "
                               f"(last {ear['last_segment_age']}s ago, "
                               f"threshold {ear['threshold']})"})
    elif ear["segments"] >= 3 and not any((s.get("text") or "").strip()
                                          for s in (ear.get("recent") or [])):
        # DEAF: it is running, the stream is not zeros, and NOTHING it heard
        # became words. That is what an ungranted microphone looks like on
        # macOS — silence substituted for a refusal — and `mic_ok` cannot see
        # it, because hiss is not silence. The check that matters asks whether
        # SPEECH arrived, not whether samples did.
        rows.append({"state": "DEAF", "part": "listener",
                     "detail": f"running, {ear['segments']} segment(s), NOT ONE became "
                               "words — the microphone grant is missing. System Settings "
                               "> Privacy & Security > Microphone > nOS Ears"})
    else:
        rows.append({"state": "LISTENING", "part": "listener",
                     "detail": f"{'ARMED · ' if ear['armed'] else ''}"
                               f"{ear['turns_today']} turn(s), "
                               f"{ear['segments']} segment(s) heard, "
                               f"heartbeat {ear['heartbeat_age']}s ago"})

    tr = data["transcripts"]
    if not tr["readable"]:
        rows.append({"state": "UNKNOWN", "part": "transcripts", "detail": tr["detail"]})
    else:
        horizon = ear.get("retention_days") or 90
        # The oldest file IS the retention check: the writer prunes, and this is
        # the reader that would notice if it stopped.
        over = tr["oldest_days"] is not None and tr["oldest_days"] > horizon + 1
        rows.append({
            "state": "BROKEN" if over else "READY",
            "part": "transcripts",
            "detail": f"{tr['files']} day-file(s), oldest {tr['oldest_days']}d"
                      f" (horizon {horizon}d)"
                      + (" — RETENTION IS NOT FIRING" if over else ""),
        })
        for turn in tr["recent"]:
            when = time.strftime("%H:%M", time.localtime(turn.get("at", 0)))
            rows.append({"state": "TURN", "part": when,
                         "detail": (turn.get("turn") or "")[:110]})

    # A RULE between the state and the speech. Appending transcript lines
    # straight under the verdicts made both harder to read — the operator said
    # so — and the two halves answer different questions.
    heard = ear.get("recent") or []
    if heard:
        rows.append({"state": "───", "part": "─── heard ───",
                     "detail": "─" * 60 + f"  (last {len(heard)}, newest first)"})

    # WHAT THE EAR IS HEARING RIGHT NOW, addressed or not — the rolling window
    # the daemon keeps in state.json. Newest first, because the reason to look
    # is always the last thing said.
    for seg in reversed(ear.get("recent") or []):
        when = time.strftime("%H:%M:%S", time.localtime(seg.get("at", 0)))
        text = (seg.get("text") or "").strip()
        secs = seg.get("secs")
        rows.append({
            "state": "HEARD", "part": when,
            # A segment the model returned nothing for says so — silence in
            # this column would read as "not heard", which is a different fact.
            "detail": (text[:110] if text
                       else f"(transcribed to nothing — {secs}s of sound)"),
        })

    # Worst first, and HEARD last in arrival order — a transcript is not a
    # verdict, so it must never sort above one.
    rank = {"BROKEN": 0, "DENIED": 1, "ABSENT": 2, "UNHEARD": 3, "DISARMED": 4,
            "UNKNOWN": 5, "OFF": 6, "READY": 7, "LISTENING": 7, "HEARD": 9}
    rows.sort(key=lambda r: (rank.get(r["state"], 8),
                             "" if r["state"] in ("HEARD", "TURN", "───") else r["part"]))
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    data = collect()
    if args.json:
        print(json.dumps(data, indent=2))
        return 0

    rows = build_rows(data)
    print(f"caddy — {sum(1 for r in rows if r['state'] == 'READY')}/{len(rows)} ready")
    for r in rows:
        print(f"  [{r['state']:<8}] {r['part']:<12} {r['detail']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
