"""A WAL database with no writer attached is unreadable to `mode=ro`.

THE MEASUREMENT (2026-08-20). A converge restarted Wing. Every read-only reader
in the estate then died with the same uncaught traceback:

    sqlite3.OperationalError: unable to open database file

`red-status.py`, `loop-status.py`, `loop-review.py`, `identity-status.py`. The
file was present, 882 MB, `pragma quick_check` ok, owned by the caller, mode
0644, in a traversable directory, and a read-WRITE open worked immediately.

THE CAUSE, and it is not intermittency. `wing.db` is in WAL mode. A WAL reader
needs the `-shm` shared index and a `mode=ro` connection may not create one.
Wing does not hold the database open between requests, so whenever no writer is
attached the sidecars simply do not exist. The readers had appeared to work all
day only because a Pulse job or an HTTP request happened to be holding the
database at the moments they ran. The failure was always one quiet minute away
and a converge is what made the minute quiet.

TWO DEFECTS, NOT ONE. The second is worse: they failed as TRACEBACKS.
`red-status.py`'s own docstring promises "If a source is missing it says so
rather than treating absence as health" — and a stack trace is neither saying so
nor treating it as health; it is the tool declining to answer at all, which on a
morning check reads as "the tool is broken" rather than "the estate is unknown".

WHAT THIS FILE PINS
  1. The opener tries `mode=ro` FIRST. Opening rw would fix the symptom and
     destroy the property these readers exist for — `red-status.py` says so
     where it connects ("must not be able to write even by accident").
  2. The snapshot fallback is REFUSED while a live `-wal` exists, because
     `immutable=1` against an active writer can return torn pages.
  3. A snapshot read SAYS it was a snapshot. A caller that cannot tell which
     kind of read it got will quote a stale answer as a current one.
  4. Unreadable resolves to None — the caller's UNKNOWN — never to an empty
     result, which would render as "nothing is wrong".

CI-safe: builds its own WAL database in tmp_path. No estate, no network.
"""

from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
OPENER = REPO / "tools" / "_ledger_open.py"


@pytest.fixture(scope="module")
def opener():
    spec = importlib.util.spec_from_file_location("_ledger_open_gate", OPENER)
    assert spec and spec.loader, f"cannot load {OPENER}"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def wal_db(tmp_path) -> Path:
    """A WAL database with NO writer attached — the exact live condition."""
    db = tmp_path / "wing.db"
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE pulse_jobs (id TEXT)")
    conn.execute("INSERT INTO pulse_jobs VALUES ('x')")
    conn.commit()
    conn.close()
    # SQLite removes the sidecars when the LAST connection detaches; macOS does
    # not always do it promptly, so the observed live state is reproduced
    # explicitly rather than waited for.
    for suffix in ("-wal", "-shm"):
        db.with_name(db.name + suffix).unlink(missing_ok=True)
    assert not db.with_name(db.name + "-shm").exists(), "fixture did not reproduce the state"
    return db


def test_the_opener_exists():
    """Positive control."""
    assert OPENER.is_file()


def test_a_closed_wal_database_is_still_readable(opener, wal_db):
    conn, how = opener.open_ledger_ro(wal_db)
    assert conn is not None, (
        f"a WAL database with no writer was reported unreadable ({how}); this is "
        f"the state every reader is in after a converge"
    )
    assert conn.execute("SELECT COUNT(*) FROM pulse_jobs").fetchone()[0] == 1


def test_a_snapshot_read_says_it_is_one(opener, wal_db):
    _conn, how = opener.open_ledger_ro(wal_db)
    assert "snapshot" in how.lower(), (
        f"the fallback read did not announce itself ({how!r}); a caller cannot "
        f"then tell a current answer from a possibly-stale one"
    )


def test_a_live_wal_is_recognised_as_live(opener, wal_db):
    """The guard that refuses the snapshot, tested where it is decidable.

    HONEST LIMIT, and it is why this asserts the predicate rather than the
    end-to-end refusal: a synthetic `-wal` beside a scratch database does NOT
    reproduce the live failure — `mode=ro` succeeds there, because SQLite will
    create the shared index when it may. On the estate it did not, and the
    precise trigger is not yet pinned. What IS established: the fallback fixes
    the live symptom (all three readers recovered), and the guard below is the
    thing standing between that fallback and a torn read. Claiming a
    reproduction here would be claiming an explanation this file does not have.
    """
    assert opener._live_wal(wal_db) is False, "an absent -wal read as live"
    wal_db.with_name(wal_db.name + "-wal").write_bytes(b"\x00" * 4096)
    assert opener._live_wal(wal_db) is True, (
        "a non-empty write-ahead log was not recognised as live; the snapshot "
        "fallback would then run against an active writer"
    )
    wal_db.with_name(wal_db.name + "-wal").write_bytes(b"")
    assert opener._live_wal(wal_db) is False, (
        "an EMPTY -wal is a checkpointed one, not a live writer — refusing on it "
        "would make the fallback useless exactly when it is needed"
    )


def test_a_missing_file_is_none_and_says_so(opener, tmp_path):
    conn, how = opener.open_ledger_ro(tmp_path / "absent.db")
    assert conn is None and "no ledger" in how


def test_read_only_is_attempted_first(opener):
    """rw would work and would destroy the property the readers exist for."""
    src = OPENER.read_text(encoding="utf-8")
    ro = src.index("mode=ro")
    imm = src.index("immutable=1", ro)
    assert ro < imm, "the immutable fallback is attempted before the read-only open"
    # Prose may DISCUSS rw (this file's own docstring does); code may not use it.
    code = "\n".join(
        ln for ln in src.splitlines()
        if "sqlite3.connect" in ln or "?mode=" in ln or "immutable=" in ln
    )
    assert "mode=rw" not in code, (
        "the opener reaches for a writable connection; these readers exist "
        "because they cannot write"
    )


@pytest.mark.parametrize("reader", ["red-status.py", "loop-status.py", "loop-review.py"])
def test_every_reader_routes_through_the_shared_opener(reader):
    """A reader that opens sqlite itself is one converge from a traceback."""
    src = (REPO / "tools" / reader).read_text(encoding="utf-8")
    assert "_ledger_open" in src, (
        f"{reader} does not use tools/_ledger_open.py; a bare "
        f"sqlite3.connect(...mode=ro) there dies whenever no writer holds the "
        f"WAL sidecars, which is most of the time"
    )
    assert 'f"file:{WING_DB}?mode=ro"' not in src and 'f"file:{LEDGER}?mode=ro"' not in src, (
        f"{reader} still opens the ledger directly"
    )
