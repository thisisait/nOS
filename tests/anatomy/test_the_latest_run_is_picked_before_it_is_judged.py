"""Anatomy CI gate — `failingJobs` picks the latest run, then asks if it failed.

MEASURED 2026-09-02. The query filtered `exit_code != 0` in the WHERE, i.e.
BEFORE `GROUP BY job_id HAVING run_id = MAX(run_id)`, so the tie-break ranged
over the surviving failures only. A job whose latest run succeeded still
reported failing whenever an earlier run shared its `fired_at` — and the
comment above it claimed the tie-break was deterministic.

Dormant on this host (no ties in `pulse_runs` today), which is exactly why a
live cross-check cannot be the only guard. This extracts the SQL from the PHP
and runs it against a synthetic tie in sqlite, so the shape is judged by what
it returns rather than by how it reads.
"""

from __future__ import annotations

import pathlib
import re
import sqlite3

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
PHP = REPO / "files/anatomy/wing/app/Model/PulseRepository.php"


def _sql() -> str:
    src = PHP.read_text(encoding="utf-8")
    body = re.search(r"public function failingJobs\(\).*?\n\t\}", src, re.S)
    assert body, "failingJobs is gone from PulseRepository"
    q = re.search(r"query\(\s*'(.*?)',", body.group(0), re.S)
    assert q, "failingJobs no longer issues a literal query"
    return q.group(1)


def _rows(sql: str, runs: list[tuple]) -> set[str]:
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE pulse_runs "
                 "(run_id TEXT, job_id TEXT, fired_at TEXT, exit_code INT)")
    conn.executemany("INSERT INTO pulse_runs VALUES (?,?,?,?)", runs)
    try:
        return {r[0] for r in conn.execute(sql)}
    finally:
        conn.close()


def test_a_tie_resolves_to_the_later_run():
    """Two runs at the same fired_at: the later one succeeded, so the job is
    green. The old shape dropped the success in the WHERE and then called the
    surviving failure the maximum."""
    if sqlite3.sqlite_version_info < (3, 25):
        pytest.skip(f"no window functions in sqlite {sqlite3.sqlite_version}")
    rows = [("r1", "nightly", "2026-09-02T03:00:00+02:00", 1),
            ("r2", "nightly", "2026-09-02T03:00:00+02:00", 0)]
    assert _rows(_sql(), rows) == set(), (
        "a job whose latest run succeeded is reported as failing. The exit_code "
        "test runs before the latest-run selection, so the tie-break ranges "
        "over the failures it already filtered down to")


def test_a_genuinely_failing_job_is_still_reported():
    """The population guard — a query returning nothing would pass the test
    above for the wrong reason."""
    if sqlite3.sqlite_version_info < (3, 25):
        pytest.skip(f"no window functions in sqlite {sqlite3.sqlite_version}")
    rows = [("r1", "nightly", "2026-09-01T03:00:00+02:00", 0),
            ("r2", "nightly", "2026-09-02T03:00:00+02:00", 2)]
    assert _rows(_sql(), rows) == {"nightly"}, (
        "the query reports no failure for a job whose latest run exited 2")


def test_an_unfinished_latest_run_is_not_a_failure():
    """exit_code NULL means still running. Counting it red would light the tile
    for every job mid-flight."""
    if sqlite3.sqlite_version_info < (3, 25):
        pytest.skip(f"no window functions in sqlite {sqlite3.sqlite_version}")
    rows = [("r1", "nightly", "2026-09-01T03:00:00+02:00", 1),
            ("r2", "nightly", "2026-09-02T03:00:00+02:00", None)]
    assert _rows(_sql(), rows) == set(), (
        "a job whose latest run has not finished is reported as failing")
