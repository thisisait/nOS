"""A reader must leave the directory exactly as it found it.

MEASURED 2026-08-04. `sqlite3 <path> "SELECT value FROM setting …"` creates
<path> as an empty database when the path does not exist. The role's disableAuth
probe did precisely that, and the live estate carried the evidence: a 0-byte
`/app/data/kuma.db` timestamped eighty minutes AFTER the container booted —
written by our converge, not by Kuma.

That file is not a harmless artefact. Kuma 2's `setup-database.js` branches on
whether kuma.db is FOUND, so a file left behind by a reader is an input to the
code being read. An observation created its own subject.

This gate runs the real script — the only way to prove "creates nothing" is to
point it at a path that does not exist and then look at the directory. That is
also why the read is a FILE and not a quoted string inside a YAML task: the
inline version was untestable in isolation, which is the reason it went four
months without anyone noticing what it did.
"""

from __future__ import annotations

import shutil
import sqlite3
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
READER = REPO / "roles/pazny.uptime_kuma/files/read-setting.sh"


def _run(db_path: Path, key: str = "disableAuth") -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(READER), str(db_path), key],
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_the_reader_ships_and_is_executable():
    assert READER.is_file(), f"{READER} is missing — the role deploys it by name"


def test_a_missing_database_is_answered_without_creating_one(tmp_path):
    """The defect, stated as the thing that must stay false."""
    db = tmp_path / "kuma.db"
    before = set(tmp_path.iterdir())

    result = _run(db)

    assert result.returncode == 0, (
        f"a missing database is not an error — it is 'no setting'. "
        f"stderr: {result.stderr!r}"
    )
    assert result.stdout.strip() == "", (
        f"a missing database must yield no value, got {result.stdout!r}"
    )
    assert not db.exists(), (
        "the reader CREATED the database it was asked to read. That is the "
        "original defect: a 0-byte kuma.db then convinces Kuma 2 that a "
        "database already exists, and it never makes a real one."
    )
    assert set(tmp_path.iterdir()) == before, (
        f"the reader left files behind: {set(tmp_path.iterdir()) - before}"
    )


def test_a_zero_byte_database_is_treated_as_no_database(tmp_path):
    """The exact live state — and it must not be made worse by reading it."""
    db = tmp_path / "kuma.db"
    db.touch()
    assert db.stat().st_size == 0

    result = _run(db)

    assert result.returncode == 0
    assert result.stdout.strip() == ""
    assert db.stat().st_size == 0, (
        "reading a zero-byte file initialised it into a real database — the "
        "reader must not write a schema, a header, or a journal"
    )


@pytest.mark.skipif(shutil.which("sqlite3") is None, reason="sqlite3 CLI not installed")
def test_a_real_setting_is_actually_returned(tmp_path):
    """The other half: a guard that never answers is not a reader.

    Without this, every assertion above is satisfied by a script that does
    nothing at all — which is the failure mode of a gate written only against
    the bug it was born from.
    """
    db = tmp_path / "kuma.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE setting (key TEXT, value TEXT, type TEXT)")
    con.execute("INSERT INTO setting VALUES ('disableAuth', 'true', 'general')")
    con.commit()
    con.close()

    result = _run(db)

    assert result.returncode == 0, f"stderr: {result.stderr!r}"
    assert result.stdout.strip() == "true", (
        f"the reader did not return a value that is plainly there: "
        f"{result.stdout!r}"
    )


@pytest.mark.skipif(shutil.which("sqlite3") is None, reason="sqlite3 CLI not installed")
def test_a_database_without_the_setting_table_is_not_an_error(tmp_path):
    """Kuma before its first migration: the file is real, the table is not."""
    db = tmp_path / "kuma.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE unrelated (x INTEGER)")
    con.commit()
    con.close()

    result = _run(db)

    assert result.returncode == 0, (
        f"a missing table is 'no setting', not a failure. stderr: {result.stderr!r}"
    )
    assert result.stdout.strip() == ""
