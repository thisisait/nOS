"""red-status names a job fired by both schedulers in 24 h (row medulla-scheduler, two_schedulers()).

The split (pulse_medulla_jobs) gives each job one scheduler: the Python daemon (its runs carry
actor_id ansible-provisioned) or the medulla (actor_id medulla). A job with runs from both in a
day is fired twice; the reader reads pulse_runs, the record, not the config that meant to split it.

A HANDOVER IS NOT TWICE (measured live 2026-10-25): Python fired loop:repo-check at 16:22, the split
moved it, the medulla fired it at 20:20 and red-status called it "fired by both". Red is a Python
run AFTER the medulla's first one in the window; Python before the medulla is the handover, info.
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
            ("loop:repo-check", at(5), "medulla"),
            ("loop:repo-check", at(1), "ansible-provisioned"),   # Python AFTER the medulla: red
            ("cortex:cortex-fs-sync", at(1), "medulla"),
            ("cortex:cortex-fs-sync", at(5), "ansible-provisioned"),  # Python, then the medulla: a handover
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
    assert split["handed"] == ["cortex:cortex-fs-sync"], split
    assert split["medulla"] == ["cortex:cortex-fs-sync", "gitea:trunk-sync", "loop:repo-check", "wing:inbox-reconcile"], split
    lines = red.reds({"schedulers": split})
    assert any("loop:repo-check" in line and "both schedulers" in line for line in lines), lines
    assert not any("gitea:trunk-sync" in line or "cortex:cortex-fs-sync" in line for line in lines), lines
