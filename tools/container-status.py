#!/usr/bin/env python3
"""Which containers Docker keeps restarting — a crash loop reads `healthy` between deaths.

Measured 2026-10-29: Loki was OOM-killed (137) and restarted by its policy ~every 15 s from 03:40,
723 restarts since it was created, while its healthcheck said healthy and red-status said nothing.
Red here: a container restarting now, or one whose policy restarted it within the last hour (the
last death said: OOM or exit code). A converge's recreate does not count (RestartCount resets).
red-status reads collect()/summary(). An unreadable docker is UNKNOWN, never ok.

Usage:
    tools/container-status.py [--json]
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys

RECENT = dt.timedelta(hours=1)


def _run(args: list[str], timeout: int = 30) -> str | None:
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout if r.returncode == 0 else None


def inspect(docker: str = "docker") -> list[dict] | None:
    ids = _run([docker, "ps", "-aq"])
    if ids is None:
        return None
    ids = ids.split()
    if not ids:
        return []
    raw = _run([docker, "inspect", *ids], timeout=60)
    return json.loads(raw) if raw else None


def _started(s: str) -> dt.datetime | None:
    try:  # Docker's RFC 3339 with nanoseconds: keep microseconds
        head, _, frac = s.rstrip("Z").partition(".")
        return dt.datetime.fromisoformat(f"{head}.{(frac + '000000')[:6]}").replace(tzinfo=dt.timezone.utc)
    except ValueError:
        return None


def looping(containers: list[dict], now: dt.datetime) -> list[dict]:
    out = []
    for c in containers:
        st = c.get("State") or {}
        n = int(c.get("RestartCount") or 0)
        started = _started(st.get("StartedAt") or "")
        recent = n > 0 and started is not None and now - started < RECENT
        if st.get("Restarting") or recent:
            out.append({"name": (c.get("Name") or "?").lstrip("/"), "restarts": n,
                        "oom": bool(st.get("OOMKilled")), "exit": st.get("ExitCode"),
                        "health": ((st.get("Health") or {}).get("Status")), "started": st.get("StartedAt")})
    return out


def collect(docker: str = "docker", now: dt.datetime | None = None) -> dict:
    now = now or dt.datetime.now(dt.timezone.utc)
    cs = inspect(docker)
    if cs is None:
        return {"looping": [], "sources_missing": ["docker inspect (no answer)"]}
    return {"looping": looping(cs, now), "sources_missing": []}


def summary(report: dict) -> list[str]:
    return [f"{c['name']} restarted by Docker {c['restarts']}× (last start {c['started'][:19]}Z"
            f"{', OOM-killed' if c['oom'] else ''}; health says {c['health'] or 'none'}) — a crash loop"
            for c in report["looping"]]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--docker", default="docker")
    args = ap.parse_args()
    report = collect(args.docker)
    if args.json:
        print(json.dumps(report, indent=2))
    elif report["sources_missing"]:
        print("UNKNOWN — " + report["sources_missing"][0])
    else:
        print("\n".join(summary(report)) or "no container is being restarted")
    return 0


if __name__ == "__main__":
    sys.exit(main())
