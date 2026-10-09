"""red-status says a missing need ONCE, not once per job it holds.

MEASURED 2026-10-09 on a clean client machine: red-status listed eight failing
pulse jobs where there were three missing needs — no claude CLI, no armed
backend, no vision model. Eight lines hide three decisions. A held run (exit
78, tools/job_readiness.py) carries its need on a `HELD:` stdout line; the
reader groups by that line. A job that was ready and still failed stays red.
"""

from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


MINIMAX = "minimax backend not armed — set minimax_enabled: true and minimax_model"
CLAUDE = "claude CLI missing (set install_claude_cli_vendor: true, or install it)"


def _report(tmp_path):
    db = tmp_path / "wing.db"
    with sqlite3.connect(db) as seed:
        seed.execute("CREATE TABLE pulse_runs (job_id TEXT, fired_at TEXT, "
                     "exit_code INT, duration_ms INT, stdout_tail TEXT)")
        seed.execute("CREATE TABLE pulse_jobs (id TEXT, findings_exit_codes TEXT, removed_at TEXT)")
        rows = [
            ("librarian:judge-lint-queue", 78, f"HELD: {MINIMAX}\n"),
            ("librarian:brief-taxonomy", 78, f"INFO: x\nHELD: {MINIMAX}\n"),
            ("surveyor:surface-survey", 78, f"HELD: {MINIMAX}\n"),
            ("conductor:vulnerability-scan", 78, f"HELD: {CLAUDE}\n[t] HELD: scan not dispatched\n"),
            ("broken:job", 1, "ERROR: it broke"),
        ]
        seed.executemany("INSERT INTO pulse_runs VALUES (?,?,?,?,?)",
                         [(j, "2026-10-09T02:00:00+00:00", rc, 10, out) for j, rc, out in rows])
        seed.executemany("INSERT INTO pulse_jobs (id, findings_exit_codes) VALUES (?, NULL)",
                         [(j,) for j, _, _ in rows])
    red = _load("_red_need_once", "tools/red-status.py")
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        report = {"failing_jobs": red.failing_jobs(conn), "held_needs": red.held_needs(conn)}
    finally:
        conn.close()
    return red, report


def test_a_held_run_is_not_a_failing_job(tmp_path):
    _, report = _report(tmp_path)
    assert [j["job"] for j in report["failing_jobs"]] == ["broken:job"], (
        "a held run (exit 78) was counted as failing, or a real failure was swallowed")


def test_one_line_per_need(tmp_path):
    red, report = _report(tmp_path)
    lines = red.reds(report)
    minimax = [ln for ln in lines if MINIMAX in ln]
    claude = [ln for ln in lines if CLAUDE in ln]
    assert len(minimax) == 1 and minimax[0].startswith("3 job(s) held: "), lines
    assert len(claude) == 1 and claude[0].startswith("1 job(s) held: "), lines
    assert any(ln.startswith("broken:job failing rc=1") for ln in lines), lines
    assert not any("scan not dispatched" in ln for ln in lines), (
        "only the judge's own HELD lines are needs — a runner's echo is not")


def test_the_hold_code_is_one_number():
    red = _load("_red_code", "tools/red-status.py")
    judge = _load("_judge_code", "tools/job_readiness.py")
    assert red.HOLD_EXIT == judge.HOLD_EXIT, "red-status and the judge disagree on the hold code"
    assert red.HOLD_EXIT != red.PAUSED_EXIT
