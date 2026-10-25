"""Exit 3 reads as the maintenance pause only when the run says it was paused.

2026-10-25: loop:vision-bench exited 3 (its declared finding: pooled accuracy
below floor; net/payable/vat 0.000) with no pause in force, and red-status
showed "last run skipped — loops paused (maintenance)". A held run carries
"PAUSED: ..." in stderr (pulse daemon, agent-run-lock.sh, pulse-run-agent.sh).
"""
from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _red():
    spec = importlib.util.spec_from_file_location("_red_pause", REPO / "tools" / "red-status.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _conn(tmp_path):
    db = tmp_path / "wing.db"
    with sqlite3.connect(db) as s:
        s.execute("CREATE TABLE pulse_runs (job_id TEXT, fired_at TEXT, exit_code INT, duration_ms INT, "
                  "stdout_tail TEXT, stderr_tail TEXT)")
        s.execute("CREATE TABLE pulse_jobs (id TEXT, findings_exit_codes TEXT, removed_at TEXT)")
        s.executemany("INSERT INTO pulse_runs VALUES (?,?,?,?,?,?)", [
            ("loop:vision-bench", "2026-10-25T05:35:27+00:00", 3, 21000, "net 0.000", ""),
            ("loop:held", "2026-10-25T05:35:27+00:00", 3, 0, "", "PAUSED: SERE loops paused (x) — loop:held held"),
            ("loop:undeclared", "2026-10-25T05:35:27+00:00", 3, 900, "boom", ""),
        ])
        s.executemany("INSERT INTO pulse_jobs (id, findings_exit_codes) VALUES (?,?)", [
            ("loop:vision-bench", "[3]"), ("loop:held", None), ("loop:undeclared", None)])
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    return c


def test_only_a_marked_run_is_a_pause(tmp_path):
    red, conn = _red(), _conn(tmp_path)
    try:
        held = {r["job"] for r in red.paused_runs(conn)}
        failing = {r["job"] for r in red.failing_jobs(conn)}
    finally:
        conn.close()
    assert held == {"loop:held"}, held
    assert "loop:vision-bench" not in failing, "a declared finding is the job working, not a failure"
    assert "loop:undeclared" in failing, "an unmarked, undeclared exit 3 is a failure, not a pause"
