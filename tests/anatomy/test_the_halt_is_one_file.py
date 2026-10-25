"""The emergency halt is one file every scheduler obeys, and it needs no Wing.

Operator ruling 2026-10-25 (row medulla-admin-halt): the halt moves out of
Wing's database. Before, `nos halt` asked Wing's PHP API to set
pulse_jobs.paused on every job, so a halt needed Wing up and made Wing a
second writer of the scheduler's table. Now ~/.nos/halt (NOS_HALT_FILE) IS
the halt: `nos halt` writes it first, Pulse holds every due job while it
exists, and Wing only records the event. A manual pause in the database is
neither set nor lifted by a halt.
"""
from __future__ import annotations

import importlib
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
NOS = REPO / "tools" / "nos"
sys.path.insert(0, str(REPO / "files" / "anatomy" / "pulse"))


def _daemon():
    return importlib.import_module("pulse.daemon")  # a package: relative imports


def test_pulse_holds_every_job_while_the_file_exists(tmp_path, monkeypatch):
    halt = tmp_path / "halt"
    monkeypatch.setenv("NOS_HALT_FILE", str(halt))
    monkeypatch.setenv("NOS_LOOPS_PAUSED_FILE", str(tmp_path / "no-loops-pause"))
    d = _daemon()
    assert d.paused_hold("backup:nightly") is None
    halt.write_text(json.dumps({"by": "operator", "at": "2026-10-25T10:00:00Z"}))
    for job in ("backup:nightly", "loop:repo-check", "advisory-patrol:nightly"):
        held = d.paused_hold(job)
        assert held and held.exit_code == 3 and "PAUSED:" in held.stderr_tail and "halt" in held.stderr_tail, job


def _nos(tmp_path, *args, port=9):
    env = {"HOME": str(tmp_path), "PATH": "/usr/bin:/bin:/opt/homebrew/bin", "NOS_HALT_FILE": str(tmp_path / "halt"),
           "WING_HALT_TOKEN": "f" * 64, "NOS_WING_URL": f"http://127.0.0.1:{port}"}
    return subprocess.run(["bash", str(NOS), *args], env=env, capture_output=True, text=True, timeout=30)


def test_nos_halt_needs_no_wing(tmp_path):
    r = _nos(tmp_path, "halt")  # port 9: nothing listens
    assert r.returncode == 0, r.stdout + r.stderr
    rec = json.loads((tmp_path / "halt").read_text())
    assert rec["at"] and rec["by"], rec
    assert "NOT recorded" in r.stderr, "the missing event must be said, not hidden"
    s = _nos(tmp_path, "halt", "--status")
    assert "halt in force" in s.stdout, s.stdout + s.stderr
    r = _nos(tmp_path, "resume")
    assert r.returncode == 0 and not (tmp_path / "halt").exists(), r.stdout + r.stderr
    assert "no halt" in _nos(tmp_path, "halt", "--status").stdout
