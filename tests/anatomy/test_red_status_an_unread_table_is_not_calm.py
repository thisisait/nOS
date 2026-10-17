"""red-status: Wing's agent_sessions unreadable is UNKNOWN, never "no orphans".

orphaned_sessions() caught sqlite3.Error and returned [] under a comment saying "an older schema
is an UNKNOWN, never a green" - and [] is the green: collect() then counted wing.db as read and the
reader could print "nothing red - every source read" with no session table at all (audit 2026-10-17).
"""

from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _red():
    spec = importlib.util.spec_from_file_location("_red_unread_table", REPO / "tools/red-status.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_no_session_table_is_not_no_orphans(tmp_path):
    db = tmp_path / "wing.db"
    with sqlite3.connect(db) as seed:
        seed.execute("CREATE TABLE pulse_runs (job_id TEXT)")
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        assert _red().orphaned_sessions(conn) is None
    finally:
        conn.close()
