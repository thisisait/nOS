"""red-status names a job fired by both schedulers in 24 h (row medulla-scheduler, two_schedulers()).

The split (pulse_medulla_jobs) gives each job one scheduler: the Python daemon (its runs carry
actor_id ansible-provisioned) or the medulla (actor_id medulla). A job with runs from both in a
day is fired twice; the reader reads pulse_runs, the record, not the config that meant to split it.
"""

from __future__ import annotations

import importlib.util
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _red():
    spec = importlib.util.spec_from_file_location("_red_two_schedulers", REPO / "tools/red-status.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_a_job_fired_by_both_is_red_and_the_split_is_shown(tmp_path):
    now = datetime.now(timezone.utc)
    at = lambda h: (now - timedelta(hours=h)).isoformat(timespec="seconds")  # noqa: E731
    db = tmp_path / "wing.db"
    with sqlite3.connect(db) as seed:
        seed.execute("CREATE TABLE pulse_runs (job_id TEXT, fired_at TEXT, actor_id TEXT)")
        seed.executemany("INSERT INTO pulse_runs VALUES (?,?,?)", [
            ("loop:repo-check", at(1), "medulla"),
            ("loop:repo-check", at(5), "ansible-provisioned"),   # both, within 24 h: red
            ("wing:inbox-reconcile", at(2), "medulla"),           # the medulla's alone
            ("keap:keap-lint", at(3), "ansible-provisioned"),     # Python's alone
            ("gitea:trunk-sync", at(2), "medulla"),
            ("gitea:trunk-sync", at(30), "ansible-provisioned"),  # handed over yesterday: not red
        ])
    red = _red()
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        split = red.schedulers(conn)
    finally:
        conn.close()
    assert split["both"] == ["loop:repo-check"], split
    assert split["medulla"] == ["gitea:trunk-sync", "loop:repo-check", "wing:inbox-reconcile"], split
    lines = red.reds({"schedulers": split})
    assert any("loop:repo-check" in line and "both schedulers" in line for line in lines), lines
    assert not any("gitea:trunk-sync" in line for line in lines), lines
