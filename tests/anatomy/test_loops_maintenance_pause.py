"""Anatomy CI gate — the SERE loops have a live maintenance-pause switch.

The operator needs to hold the agent loops before a converge (instead of
hand-unloading the resident model) and resume after, WITHOUT a converge. The
switch lives at the one chokepoint every agent run already goes through —
agent-run-lock.sh — so it covers the Pulse agents and the 02:00 vuln scan
alike, and it is neither a lock-refusal (2) nor a false success (0): a paused
run is a HOLD (return 3).

This gate must FAIL on a tree with no pause mechanism (agent-run-lock returns 0
with the sentinel present; red-status calls an exit-3 run red) and PASS once the
switch is wired end to end.
"""

from __future__ import annotations

import importlib.util
import os
import pathlib
import sqlite3
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
LOCK = REPO / "files/anatomy/scripts/agent-run-lock.sh"
PULSE = REPO / "files/anatomy/scripts/pulse-run-agent.sh"
SCAN = REPO / "files/vuln-scan/scan-runner.sh"
RED = REPO / "tools/red-status.py"
NOS = REPO / "tools/nos"

if sys.platform not in ("darwin", "linux"):  # pragma: no cover
    pytest.skip("bash lock probe is POSIX-only", allow_module_level=True)


# ── The chokepoint returns a distinct paused disposition (3) ─────────────────

def _acquire_rc(paused_file: pathlib.Path | None, lock_dir: pathlib.Path) -> str:
    probe = lock_dir.parent / "probe.sh"
    probe.write_text(
        f'source "{LOCK}"\n'
        'nos_agent_lock_acquire probe 0 cli; echo "rc=$?"\n',
        encoding="utf-8",
    )
    env = dict(os.environ, NOS_AGENT_LOCK_DIR=str(lock_dir))
    if paused_file is not None:
        env["NOS_LOOPS_PAUSED_FILE"] = str(paused_file)
    out = subprocess.run(["bash", str(probe)], env=env,
                         capture_output=True, text=True, timeout=30)
    return out.stdout


def test_paused_sentinel_makes_acquire_return_three(tmp_path):
    sentinel = tmp_path / "loops-paused"
    sentinel.write_text("since: 2026-09-19T00:00:00Z\n", encoding="utf-8")
    assert "rc=3" in _acquire_rc(sentinel, tmp_path / "agent-run.lock"), (
        "with the pause sentinel present, nos_agent_lock_acquire must return 3 "
        "(a hold) BEFORE taking a slot — not 0 (false success) and not 2 (refusal)"
    )


def test_no_sentinel_runs_the_normal_path(tmp_path):
    sentinel = tmp_path / "loops-paused"  # deliberately not created
    assert "rc=0" in _acquire_rc(sentinel, tmp_path / "agent-run.lock"), (
        "with no sentinel the normal acquire path must run and take the lock"
    )


def test_the_paused_run_no_ops_as_paused(tmp_path):
    """A loop run using the acquire-then-run pattern must SKIP when paused."""
    sentinel = tmp_path / "loops-paused"
    sentinel.write_text("since: 2026-09-19T00:00:00Z\n", encoding="utf-8")
    runner = tmp_path / "run.sh"
    runner.write_text(
        f'source "{LOCK}"\n'
        '_rc=0\n'
        'nos_agent_lock_acquire probe 0 cli || _rc=$?\n'
        '[ "$_rc" -eq 3 ] && { echo PAUSED; exit 3; }\n'
        'echo RAN\n',
        encoding="utf-8",
    )
    out = subprocess.run(
        ["bash", str(runner)],
        env=dict(os.environ, NOS_AGENT_LOCK_DIR=str(tmp_path / "l.lock"),
                 NOS_LOOPS_PAUSED_FILE=str(sentinel)),
        capture_output=True, text=True, timeout=30)
    assert out.returncode == 3 and "PAUSED" in out.stdout and "RAN" not in out.stdout


def test_both_runners_carry_the_paused_hold(tmp_path):
    """Both claude spawners must map the lock's 3 to an intentional skip."""
    for path in (PULSE, SCAN):
        body = path.read_text(encoding="utf-8")
        block = body[body.find("nos_agent_lock_acquire"):]
        block = block[:900]
        assert '-eq 3' in block, (
            f"{path.name} does not distinguish the paused disposition (3) from "
            "a lock refusal (2) — a pause would read as breakage")
        # And the refusal path must still exit 2 (the surviving contract).
        assert "exit 2" in block, f"{path.name} lost the lock-refusal exit 2"


def test_header_documents_return_three():
    assert "return 3" in LOCK.read_text() or "= MAINTENANCE PAUSE" in LOCK.read_text(), (
        "the paused disposition (3) is undocumented in the lock header")


# ── red-status renders a paused run as a hold, not red and not green ──────────

def _load_red(paused_file: pathlib.Path | None):
    # Set the module attribute directly rather than os.environ — mutating the
    # parent env leaks NOS_LOOPS_PAUSED_FILE into sibling tests' subprocesses.
    spec = importlib.util.spec_from_file_location("_red_pause", RED)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if paused_file is not None:
        mod.LOOPS_PAUSED_FILE = pathlib.Path(paused_file)
    return mod


def test_a_paused_run_is_a_hold_not_a_failure(tmp_path):
    db = tmp_path / "wing.db"
    with sqlite3.connect(db) as seed:
        seed.execute("CREATE TABLE pulse_runs (job_id TEXT, fired_at TEXT, "
                     "exit_code INT, duration_ms INT, stdout_tail TEXT)")
        seed.execute("CREATE TABLE pulse_jobs (id TEXT, findings_exit_codes TEXT)")
        seed.executemany("INSERT INTO pulse_runs VALUES (?,?,?,?,?)", [
            ("agent:surveyor", "2026-09-19T02:00:00+00:00", 3, 10, "PAUSED: loops paused"),
            ("broken:job", "2026-09-19T02:00:00+00:00", 1, 10, "ERROR: it broke"),
        ])
        seed.executemany("INSERT INTO pulse_jobs VALUES (?,?)",
                         [("agent:surveyor", None), ("broken:job", None)])

    mod = _load_red(None)
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        failing = {j["job"] for j in mod.failing_jobs(conn)}
        paused = {p["job"] for p in mod.paused_runs(conn)}
    finally:
        conn.close()
    assert "agent:surveyor" not in failing, (
        "a paused run (exit 3) was reported as failing — a hold is not red")
    assert "agent:surveyor" in paused, "the paused run was not surfaced as a hold"
    assert "broken:job" in failing, "a genuine failure was swallowed by the pause path"


def test_loops_paused_reader_reflects_the_sentinel(tmp_path):
    sentinel = tmp_path / "loops-paused"
    mod = _load_red(sentinel)
    assert mod.loops_paused() is None, "no sentinel must read as running, not paused"
    sentinel.write_text("since: 2026-09-19T00:00:00Z\nreason: converge\n", encoding="utf-8")
    got = mod.loops_paused()
    assert got and got["paused"] and got["reason"] == "converge"
    holds = mod.hold_lines({"loops_paused": got, "paused_runs": []})
    assert any("loops paused (maintenance)" in h for h in holds), (
        "a paused estate must render a distinct hold line")


# ── the nos CLI toggles the sentinel ─────────────────────────────────────────

def test_nos_cli_pause_resume_status_toggle_the_sentinel(tmp_path):
    sentinel = tmp_path / "loops-paused"
    env = dict(os.environ, NOS_LOOPS_PAUSED_FILE=str(sentinel), HOME=str(tmp_path))

    def run(*args):
        return subprocess.run(["bash", str(NOS), "loops", *args],
                              env=env, capture_output=True, text=True, timeout=30)

    assert "running" in run("status").stdout
    p = run("pause", "--reason", "converge")
    assert p.returncode == 0 and sentinel.is_file()
    assert "reason: converge" in sentinel.read_text()
    assert "PAUSED" in run("status").stdout
    r = run("resume")
    assert r.returncode == 0 and not sentinel.is_file()
    assert "running" in run("status").stdout
