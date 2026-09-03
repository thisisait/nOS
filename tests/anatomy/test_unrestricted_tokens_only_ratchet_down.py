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


def test_the_unrestricted_count_never_grows():
    db = pathlib.Path(os.environ.get(
        "WING_DB_PATH", str(pathlib.Path.home() / "wing/app/data/wing.db")))
    if not db.is_file():
        pytest.skip("no wing.db on this host — the live count is UNKNOWN here")
    conn = sqlite3.connect(f"file:{db}?immutable=1", uri=True)
    try:
        n, names = conn.execute(
            "SELECT COUNT(*), group_concat(name) FROM api_tokens "
            "WHERE scopes IS NULL AND active = 1").fetchone()
    except sqlite3.OperationalError as exc:
        pytest.skip(f"wing.db could not be read: {exc}")
    finally:
        conn.close()
    assert n <= CEILING, (
        f"{n} active unrestricted tokens ({names}) — above the recorded "
        f"ceiling of {CEILING}. A NEW NULL-scope token was minted; new tokens "
        "are never NULL (ruling 4). If this is a deliberate exception, raising "
        "the ceiling is the loud act this gate exists to demand")
