"""tools/ci-tier-status.py reds a stack not green in 7 days and is never green on absence.

Offline: a fake `gh` on PATH serves the run list and job views from tmp files.
A missing file makes the fake exit 1, which is what an unreadable gh looks like.
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
from datetime import datetime, timezone

REPO = pathlib.Path(__file__).resolve().parents[2]
READER = REPO / "tools" / "ci-tier-status.py"
FAKE_GH = """#!/usr/bin/env python3
import os, pathlib, sys
a = sys.argv[1:]
name = "list.json" if a[:2] == ["run", "list"] else f"view-{a[2]}.json"
p = pathlib.Path(os.environ["FAKE_GH_DIR"]) / name
sys.exit(1) if not p.exists() else print(p.read_text())
"""


def _run(tmp_path: pathlib.Path, files: dict) -> dict:
    (tmp_path / "gh").write_text(FAKE_GH)
    (tmp_path / "gh").chmod(0o755)
    for name, body in files.items():
        (tmp_path / name).write_text(json.dumps(body))
    env = {**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}", "FAKE_GH_DIR": str(tmp_path)}
    r = subprocess.run([sys.executable, str(READER), "--json"], capture_output=True, text=True, env=env, timeout=120)
    assert r.returncode == 0, r.stderr
    return {k: v["status"] for k, v in json.loads(r.stdout)["lanes"].items()}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _jobs(**conclusions) -> dict:
    return {"jobs": [{"name": f"Bonus ({k})", "conclusion": v, "completedAt": _now()} for k, v in conclusions.items()]}


def test_unreadable_gh_is_unknown_never_green(tmp_path):
    lanes = _run(tmp_path, {})
    assert lanes and set(lanes.values()) == {"UNKNOWN"}


def test_green_needs_a_success_and_absence_is_red(tmp_path):
    runs = [{"databaseId": 1, "headSha": "a" * 40, "createdAt": _now()},
            {"databaseId": 2, "headSha": "b" * 40, "createdAt": _now()}]
    lanes = _run(tmp_path, {"list.json": runs, "view-1.json": _jobs(devops="success", b2b="failure"),
                            "view-2.json": _jobs(b2b="cancelled")})
    assert lanes.pop("devops") == "GREEN"
    assert lanes.pop("b2b") == "RED"
    assert set(lanes.values()) == {"RED"}, f"a lane with no run must be red: {lanes}"


def test_a_run_it_could_not_read_makes_red_unknown(tmp_path):
    runs = [{"databaseId": 1, "headSha": "a" * 40, "createdAt": _now()},
            {"databaseId": 2, "headSha": "b" * 40, "createdAt": _now()}]
    lanes = _run(tmp_path, {"list.json": runs, "view-1.json": _jobs(devops="success")})
    assert lanes.pop("devops") == "GREEN"
    assert set(lanes.values()) == {"UNKNOWN"}
