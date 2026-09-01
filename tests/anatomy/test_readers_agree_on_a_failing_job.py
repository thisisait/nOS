"""Two readers, one column, and they must not differ by a job.

`pulse_jobs.findings_exit_codes` is read by Wing
(`PulseRepository::failingJobs()`) and by `tools/red-status.py::failing_jobs`.
Wing collapses a fired_at tie (`GROUP BY r.job_id HAVING r.run_id =
MAX(r.run_id)`); red-status did not, so two runs stamped in the same second
made one reader say N and the other N+1 about the same estate. That is the
shape of "the hub says 10, the DB says 11" — and a reader that disagrees with
the page is one the operator learns to discount.

Also pinned: `loop:review` declares NO findings code. loop-review.py's exit
contract is 0 decided / 1 half-done / 2 configuration it will not guess at —
neither non-zero means "ran correctly, found something", so rc=2 must stay red.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sqlite3
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]


def _red_status():
    spec = importlib.util.spec_from_file_location("_red_status", REPO / "tools" / "red-status.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_red_status"] = mod
    spec.loader.exec_module(mod)
    return mod


RS = _red_status()

SCHEMA = """
CREATE TABLE pulse_jobs (id TEXT PRIMARY KEY, findings_exit_codes TEXT);
CREATE TABLE pulse_runs (run_id TEXT PRIMARY KEY, job_id TEXT, fired_at TEXT,
                         exit_code INT, duration_ms INT, stdout_tail TEXT);
"""


def _ledger(runs, jobs=()):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.executemany("INSERT INTO pulse_jobs VALUES (?,?)", jobs)
    conn.executemany(
        "INSERT INTO pulse_runs VALUES (?,?,?,?,?,?)",
        [(rid, jid, at, rc, 1, "boom") for rid, jid, at, rc in runs],
    )
    return conn


def test_a_fired_at_tie_reports_one_job_not_two():
    """The divergence: Wing's query yields one row here, red-status yielded two."""
    conn = _ledger([("a", "loop:review", "2026-09-01T06:50:53+00:00", 2),
                    ("b", "loop:review", "2026-09-01T06:50:53+00:00", 2)])
    jobs = [r["job"] for r in RS.failing_jobs(conn)]
    assert jobs == ["loop:review"], (
        f"a fired_at tie produced {jobs} — red-status counts a job twice where "
        f"Wing's failingJobs() counts it once"
    )


def test_a_declared_findings_code_is_still_not_a_failure():
    """The dedupe must not resurrect a job the findings declaration excuses."""
    conn = _ledger(
        [("a", "gitleaks:nightly-scan", "2026-09-01T02:00:00+00:00", 1),
         ("b", "gitleaks:nightly-scan", "2026-09-01T02:00:00+00:00", 1)],
        jobs=[("gitleaks:nightly-scan", "[1]")],
    )
    assert RS.failing_jobs(conn) == []


def test_a_genuinely_failing_job_is_still_reported():
    """Positive control — the dedupe must not swallow the last row standing."""
    conn = _ledger([("a", "loop:review", "2026-09-01T06:50:53+00:00", 2)])
    assert [r["job"] for r in RS.failing_jobs(conn)] == ["loop:review"]


def test_loop_review_declares_no_findings_exit_code():
    """rc=1 half-done and rc=2 refused-config are both failures, so red is right."""
    doc = yaml.safe_load((REPO / "files/anatomy/plugins/loop-base/plugin.yml")
                         .read_text(encoding="utf-8"))
    jobs = {j["name"]: j for j in doc["pulse"]["jobs"]}
    assert "findings_exit_codes" not in jobs["review"], (
        "loop:review declared a findings code. tools/loop-review.py returns "
        "1 only for a half-done promotion and 2 only for a refusal it will not "
        "guess at; declaring either mutes a real failure."
    )
    assert jobs["propose"]["findings_exit_codes"] == [1, 3], (
        "the [1,3] belongs to propose alone — it is per JOB, not per plugin"
    )
