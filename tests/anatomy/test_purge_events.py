"""Anatomy CI gate — bin/purge-events.php (GDPR storage-limitation purge).

Runs the real CLI against a throwaway SQLite DB: dry-run must count without
deleting; a live run must delete only rows past the horizon; bad args must
fail. Skipped when php is unavailable (e.g. a minimal CI image).
"""

from __future__ import annotations

import pathlib
import shutil
import sqlite3
import subprocess
from datetime import datetime, timedelta, timezone

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
CLI = REPO / "files" / "anatomy" / "wing" / "bin" / "purge-events.php"

pytestmark = pytest.mark.skipif(shutil.which("php") is None, reason="php not installed")


def _seed_db(path: pathlib.Path) -> None:
    con = sqlite3.connect(path)
    con.execute(
        "CREATE TABLE events (id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "ts TEXT NOT NULL, run_id TEXT NOT NULL, type TEXT NOT NULL)"
    )
    old = (datetime.now(timezone.utc) - timedelta(days=400)).strftime("%Y-%m-%dT%H:%M:%SZ")
    recent = (datetime.now(timezone.utc) - timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
    con.executemany(
        "INSERT INTO events (ts, run_id, type) VALUES (?, 'r', 'task_ok')",
        [(old,), (old,), (recent,)],  # 2 stale, 1 fresh
    )
    con.commit()
    con.close()


def _run(*args: str):
    return subprocess.run(["php", str(CLI), *args], capture_output=True, text=True)


def _count(path: pathlib.Path) -> int:
    con = sqlite3.connect(path)
    n = con.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    con.close()
    return n


def test_dry_run_counts_without_deleting(tmp_path):
    db = tmp_path / "wing.db"
    _seed_db(db)
    r = _run(f"--db={db}", "--older-than-days=365", "--dry-run")
    assert r.returncode == 0, r.stderr
    assert "would purge 2 events" in r.stdout
    assert _count(db) == 3, "dry-run must not delete"


def test_live_run_deletes_only_stale(tmp_path):
    db = tmp_path / "wing.db"
    _seed_db(db)
    r = _run(f"--db={db}", "--older-than-days=365")
    assert r.returncode == 0, r.stderr
    assert "Purged 2 events" in r.stdout
    assert _count(db) == 1, "only the fresh row survives"


def test_rejects_non_positive_days(tmp_path):
    db = tmp_path / "wing.db"
    _seed_db(db)
    assert _run(f"--db={db}", "--older-than-days=0").returncode == 1
    assert _run(f"--db={db}", "--older-than-days=abc").returncode == 1


def test_missing_args_fail(tmp_path):
    assert _run("--older-than-days=365").returncode == 1
