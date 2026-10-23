"""Anatomy CI gate — the count of NULL-scope Wing tokens may only go DOWN.

Ruling 4 (operator, 2026-09-02, docs/doctrine/agentkit.md §6): the grandfathered incumbents
(`api_tokens.scopes` NULL = unrestricted, kept because closing them at
introduction would have 403'd the estate) are narrowed one at a time from
MEASURED `agent_tool_use` history, with manual loop runs simulating the night
before each narrowing sticks. "Later" without a mechanism is never — this gate
IS the mechanism: a ratchet, the same shape as workflows.md's retro-red ratchet.

CEILING below is the recorded high-water mark. Lower it as tokens narrow;
raising it is the one edit this gate exists to make loud. Skips (never passes)
off-estate — a missing wing.db is UNKNOWN, not zero.
"""

from __future__ import annotations

import os
import pathlib
import sqlite3

import pytest

#: 2026-09-02: 7. 2026-09-03 morning: 1. 2026-09-03: 0 — ansible-provisioned
#: declared wing.write (every consumer writes; permits() grants reads to
#: writers), agent mints now DERIVE scopes from their agent.yml (ruling 3).
#: Zero is the floor: any new NULL row is a regression, not a backlog.
CEILING = 0

COUNT = "SELECT COUNT(*), group_concat(name) FROM api_tokens WHERE scopes IS NULL AND active = 1"


def _open(db: pathlib.Path) -> sqlite3.Connection:
    """The live count: Wing writes in WAL mode, so a read must see the -wal file too."""
    return sqlite3.connect(f"file:{db}?immutable=1", uri=True)


def test_the_unrestricted_count_never_grows():
    db = pathlib.Path(os.environ.get(
        "WING_DB_PATH", str(pathlib.Path.home() / "wing/app/data/wing.db")))
    if not db.is_file():
        pytest.skip("no wing.db on this host — the live count is UNKNOWN here")
    conn = _open(db)
    try:
        n, names = conn.execute(COUNT).fetchone()
    except sqlite3.OperationalError as exc:
        pytest.skip(f"wing.db could not be read: {exc}")
    finally:
        conn.close()
    assert n <= CEILING, (
        f"{n} active unrestricted tokens ({names}) — above the recorded "
        f"ceiling of {CEILING}. A NEW NULL-scope token was minted; new tokens "
        "are never NULL (ruling 4). If this is a deliberate exception, raising "
        "the ceiling is the loud act this gate exists to demand")


def test_the_count_reads_what_the_wal_holds(tmp_path):
    """spark1 2026-10-22: testers torn down (active=0 in the WAL, not yet checkpointed) still
    counted 5 through immutable=1, which reads the main file alone. The gate reads the live rows."""
    db = tmp_path / "wing.db"
    w = sqlite3.connect(db)
    w.execute("PRAGMA journal_mode=WAL")
    w.execute("PRAGMA wal_autocheckpoint=0")
    w.execute("CREATE TABLE api_tokens (name TEXT, scopes TEXT, active INTEGER)")
    w.execute("INSERT INTO api_tokens VALUES ('tester', NULL, 1)")
    w.commit()
    w.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    w.execute("UPDATE api_tokens SET active = 0")  # the teardown, still only in the WAL
    w.commit()
    try:
        r = _open(db)
        try:
            assert r.execute(COUNT).fetchone()[0] == 0, "the read missed the WAL: a torn-down token still counts"
        finally:
            r.close()
    finally:
        w.close()
