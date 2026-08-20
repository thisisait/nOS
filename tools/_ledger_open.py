"""One way to open the Wing ledger read-only, for readers that must not write.

THE MEASUREMENT (2026-08-20). After a converge restarted Wing, every read-only
reader in the estate died with the same traceback:

    sqlite3.OperationalError: unable to open database file

The file was there, 882 MB, `pragma quick_check` ok, owned by the caller,
readable, in a traversable directory. `red-status.py`, `loop-status.py`,
`loop-review.py` and `identity-status.py` all fell over, and they fell over as
UNCAUGHT TRACEBACKS — which is the second defect, because `red-status.py`'s own
docstring promises the opposite: "If a source is missing it says so rather than
treating absence as health."

THE CAUSE. `wing.db` is in **WAL** mode. A WAL reader needs the `-shm` shared
index, and a connection opened `mode=ro` may not CREATE it. Wing does not hold
the database open between requests, so whenever no writer is attached the two
sidecars are absent and every `mode=ro` open fails. The readers appeared to work
all day only because a Pulse job or a Wing request happened to be holding the
database at the moments they ran — the failure was always one quiet minute away.
It is not intermittent; it is conditional, on a condition nobody controls.

THE FIX, AND WHY NOT THE OBVIOUS ONE. Opening `mode=rw` would work and is what
most code does. It is refused here: these readers exist BECAUSE they cannot
write — `red-status.py` says so where it opens the file ("this tool must not be
able to write even by accident"), and a reader that could repair would
eventually be asked to certify its own repair.

So: `mode=ro` first. If that fails and there is no live WAL — no `-wal` file, or
an empty one, meaning no writer has uncommitted frames — retry with
`immutable=1`, which reads without the shared index. That fallback is a
SNAPSHOT and it is labelled as one, because `immutable=1` on a database somebody
IS writing can return torn pages. When a live WAL is present the fallback is
refused rather than risked, and the caller gets None.

None means UNREADABLE, which every caller must render as UNKNOWN. Never green.
"""

from __future__ import annotations

import pathlib
import sqlite3

WING_DB = pathlib.Path.home() / "wing" / "app" / "data" / "wing.db"


class LedgerUnreadable(Exception):
    """Raised only by `open_or_raise`; carries the reason for a report."""


def _live_wal(db: pathlib.Path) -> bool:
    """Is a writer mid-flight? An empty -wal is a checkpointed one, not a live one."""
    wal = db.with_name(db.name + "-wal")
    try:
        return wal.is_file() and wal.stat().st_size > 0
    except OSError:
        return True          # cannot tell → assume live → refuse the snapshot


def open_ledger_ro(db: pathlib.Path | None = None) -> tuple[sqlite3.Connection | None, str]:
    """Return (connection, how). `how` is "" on the normal path.

    `how` is not decoration: a caller that read a snapshot should be able to say
    so, and a caller that got None must say UNKNOWN rather than nothing.
    """
    path = pathlib.Path(db or WING_DB)
    if not path.is_file():
        return None, f"no ledger at {path}"

    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        conn.execute("SELECT 1").fetchone()      # force the real open
        conn.row_factory = sqlite3.Row
        return conn, ""
    except sqlite3.Error as first:
        if _live_wal(path):
            return None, (
                f"{path.name} is WAL-mode with a live write-ahead log and no "
                f"shared index this reader may create ({first}); a snapshot "
                f"read could return torn pages, so nothing is reported"
            )
        try:
            conn = sqlite3.connect(f"file:{path}?immutable=1", uri=True)
            conn.execute("SELECT 1").fetchone()
            conn.row_factory = sqlite3.Row
            return conn, "snapshot (WAL sidecars absent; read as immutable)"
        except sqlite3.Error as second:
            return None, f"{path.name} unreadable: {first}; snapshot also failed: {second}"


def open_or_raise(db: pathlib.Path | None = None) -> sqlite3.Connection:
    """For callers that would rather fail loudly than report a partial truth."""
    conn, how = open_ledger_ro(db)
    if conn is None:
        raise LedgerUnreadable(how)
    return conn
