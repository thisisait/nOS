"""Anatomy CI gate — a `mode=ro` reader of wing.db opens even after the sidecars went.

Measured 2026-10-03/04: wing.db is WAL. Wing's PHP closes its PDO each request,
and SQLite's last close checkpoints and DELETES `-wal` and `-shm`. A `mode=ro`
connection may not create them, so every read-only reader (Grafana's
`pathOptions: mode=ro` over a `:ro` mount, the host readers) then dies with
SQLITE_CANTOPEN (14). Writable directory or not — measured both.

The fix lives on the writer side, where all readers share it: Bone holds one
idle connection for its lifetime (`clients.wing.anchor_wal`), so the last close
never happens while Bone runs, and that connection sets NO_CKPT_ON_CLOSE so its
own close leaves the sidecars behind. An idle connection blocks no checkpoint.
"""
from __future__ import annotations

import ast
import importlib
import sqlite3
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
BONE = REPO / "files/anatomy/bone"


def _wal_db_without_sidecars(tmp_path: Path) -> Path:
    db = tmp_path / "wing.db"
    c = sqlite3.connect(db)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("CREATE TABLE events(id INTEGER PRIMARY KEY, t TEXT)")
    c.execute("INSERT INTO events(t) VALUES ('a')")
    c.commit()
    c.close()
    for s in ("-wal", "-shm"):          # what a PHP last-close leaves behind
        db.with_name(db.name + s).unlink(missing_ok=True)
    return db


def _ro_count(db: Path) -> int:
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return c.execute("SELECT count(*) FROM events").fetchone()[0]
    finally:
        c.close()


@pytest.fixture
def wing(tmp_path, monkeypatch):
    db = _wal_db_without_sidecars(tmp_path)
    monkeypatch.setenv("WING_DB_PATH", str(db))
    monkeypatch.syspath_prepend(str(BONE))
    for name in [m for m in list(sys.modules) if m.startswith("clients")]:
        del sys.modules[name]
    return db, importlib.import_module("clients.wing")


def test_the_trap_is_real(tmp_path):
    """Without an anchor a `mode=ro` open of a sidecar-less WAL db fails."""
    db = _wal_db_without_sidecars(tmp_path)
    with pytest.raises(sqlite3.OperationalError, match="unable to open"):
        _ro_count(db)


def test_anchor_keeps_ro_readers_open(wing):
    db, w = wing
    anchor = w.anchor_wal()
    try:
        assert _ro_count(db) == 1
        # A Wing request: open, write, close. Not the last close any more.
        c = sqlite3.connect(db)
        c.execute("INSERT INTO events(t) VALUES ('b')")
        c.commit()
        c.close()
        assert _ro_count(db) == 2
        assert anchor.getconfig(sqlite3.SQLITE_DBCONFIG_NO_CKPT_ON_CLOSE)
    finally:
        anchor.close()
    assert db.with_name("wing.db-shm").exists(), "the anchor's close removed -shm"
    assert _ro_count(db) == 2


def test_bone_holds_the_anchor_at_module_level():
    """The anchor is useless unless Bone takes it at import and keeps it."""
    tree = ast.parse((BONE / "main.py").read_text(encoding="utf-8"))
    held = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Assign)
        and isinstance(n.value, ast.Call)
        and isinstance(n.value.func, ast.Attribute)
        and n.value.func.attr == "anchor_wal"
        and all(isinstance(t, ast.Name) and t.id.isupper() for t in n.targets)
    ]
    assert held, "bone/main.py no longer holds clients.wing.anchor_wal() in a global"
