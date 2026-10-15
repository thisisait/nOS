#!/usr/bin/env python3
"""Has every bonus CI lane (one manifest stack each) been green in the last 7 days?

Lanes come from tools/test-tiers.py; runs from `gh run list` / `gh run view` on ci.yml
(read-only). GREEN: a `Bonus (<stack>)` job succeeded within 7 days. RED: none did, and
that includes no run at all. UNKNOWN: gh could not be read. Never green on absence.

Reads only. Exit 0 always.

Usage:
    tools/ci-tier-status.py            # table
    tools/ci-tier-status.py --json
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import pathlib
import subprocess
import sys
from datetime import datetime, timedelta, timezone

REPO = pathlib.Path(__file__).resolve().parents[1]
STALE_DAYS = 7


def _lanes() -> list[str]:
    spec = importlib.util.spec_from_file_location("_nos_test_tiers", REPO / "tools" / "test-tiers.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return list(mod.derive()["lanes"])


def _gh(*args: str):
    try:
        r = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=60, cwd=REPO)
        return json.loads(r.stdout) if r.returncode == 0 else None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def collect(now: datetime | None = None) -> dict:
    now = now or datetime.now(tz=timezone.utc)
    since = (now - timedelta(days=STALE_DAYS)).strftime("%Y-%m-%d")
    lanes = {n: {"status": "UNKNOWN", "detail": "gh run list unreadable"} for n in _lanes()}
    runs = _gh("run", "list", "--workflow", "ci.yml", "--created", f">={since}", "--limit", "200",
               "--json", "databaseId,headSha,createdAt")
    if runs is None:
        return {"lanes": lanes}
    blind = False
    for name in lanes:
        lanes[name] = {"status": "RED", "detail": f"no green Bonus ({name}) since {since}"}
    for run in sorted(runs, key=lambda r: r["createdAt"], reverse=True):
        if all(v["status"] == "GREEN" for v in lanes.values()):
            break
        view = _gh("run", "view", str(run["databaseId"]), "--json", "jobs")
        if view is None:
            blind = True
            continue
        for job in view.get("jobs", []):
            name = job.get("name", "")[len("Bonus ("):-1] if job.get("name", "").startswith("Bonus (") else None
            if name in lanes and lanes[name]["status"] != "GREEN" and job.get("conclusion") == "success":
                lanes[name] = {"status": "GREEN", "detail": f"{job.get('completedAt')} {run['headSha'][:10]}"}
    for v in lanes.values():
        if blind and v["status"] == "RED":
            v.update(status="UNKNOWN", detail=v["detail"] + "; some runs unreadable")
    return {"lanes": lanes}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true")
    report = collect()
    if ap.parse_args().json:
        print(json.dumps(report, indent=1))
    else:
        for name, v in report["lanes"].items():
            print(f"{v['status']:8} {name:20} {v['detail']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
