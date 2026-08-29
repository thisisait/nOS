"""Anatomy gate — agent memory stays deleted (Q8=c, 2026-08-28).

KEAP is the estate's memory. A second memory beside the cortex is a second
truth, so the Dreams subsystem — Dreamer, MemoryStore, the
AgentMemoryStoreRepository, bin/dream-agent.php, Runner::loadMemoryContext()
and the agent_memory_stores table — was deleted rather than parked.

A deletion with no gate against the return is a deletion that gets undone,
usually by a well-meaning re-read of a stale doc. This gate reads the
artifacts themselves: the schema DDL that a converge applies, and the class
tree the autoloader serves. It does not read prose about them.
"""

from __future__ import annotations

import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
WING = REPO / "files" / "anatomy" / "wing"
SCHEMA = WING / "db" / "schema-extensions.sql"
AGENTKIT = WING / "app" / "AgentKit"
MODEL = WING / "app" / "Model"
NEON = WING / "app" / "config" / "common.neon"

FORBIDDEN_IDENTIFIERS = ("loadMemoryContext", "Dreamer", "MemoryStore", "AgentMemoryStoreRepository")


def test_agent_memory_stores_table_is_gone():
    """The table must not be creatable — no CREATE, no ALTER, no INDEX.

    Substring match on the table name, because every DDL form that could
    resurrect it (CREATE TABLE, CREATE INDEX ... ON, ALTER TABLE) names it.
    """
    sql = SCHEMA.read_text(encoding="utf-8")
    assert "agent_memory_stores" not in sql, (
        "agent_memory_stores is back in schema-extensions.sql. Agent memory was "
        "deleted deliberately (Q8=c): KEAP is the estate's memory. If a durable "
        "agent-side store is genuinely needed, that is an operator decision, not "
        "a schema edit."
    )


@pytest.mark.parametrize("ident", FORBIDDEN_IDENTIFIERS)
def test_memory_machinery_does_not_reappear_in_agentkit(ident: str):
    """No AgentKit source may name the deleted memory machinery.

    Walks the real class tree — a file that exists is a file the PSR-4
    autoloader will serve, so its presence is the fact this asserts on.
    """
    hits = [
        p.relative_to(REPO)
        for p in AGENTKIT.rglob("*.php")
        if ident in p.read_text(encoding="utf-8")
    ]
    assert not hits, f"{ident} reappeared under app/AgentKit/: {hits}"


def test_memory_classes_are_absent_from_the_tree():
    """The Memory/ namespace and the repository file must not exist."""
    for path in (
        AGENTKIT / "Memory",
        AGENTKIT / "Memory" / "Dreamer.php",
        AGENTKIT / "Memory" / "MemoryStore.php",
        MODEL / "AgentMemoryStoreRepository.php",
        WING / "bin" / "dream-agent.php",
    ):
        assert not path.exists(), f"{path.relative_to(REPO)} is back — see Q8=c."


@pytest.mark.parametrize("ident", FORBIDDEN_IDENTIFIERS)
def test_memory_machinery_is_not_wired_in_di(ident: str):
    """A class nobody can construct is a class nobody resurrects by accident."""
    assert ident not in NEON.read_text(encoding="utf-8"), (
        f"{ident} is registered in common.neon — the DI container would "
        "instantiate memory machinery that no longer exists."
    )


# ── The half that reads the ESTATE, not the repo ─────────────────────────────
#
# Added 2026-08-29. Everything above reads committed files, and on the day the
# deletion shipped every one of those checks was green while `agent_memory_stores`
# was still sitting in `~/wing/app/data/wing.db`. Removing a CREATE from
# schema-extensions.sql does nothing to a database that already ran it, and this
# file's subject — "no agent memory, EVER" — is a claim about the estate, not
# about the SQL. So the claim gets a reader pointed at the estate.
#
# UNKNOWN where there is no database: CI has no wing.db, and a skip there is the
# honest answer. It is the operator's machine that can settle this one.

import sqlite3

WING_DB = pathlib.Path.home() / "wing" / "app" / "data" / "wing.db"


@pytest.mark.skipif(not WING_DB.is_file(),
                    reason="no wing.db on this host — the live half is UNKNOWN, not green")
def test_the_table_is_gone_from_the_live_database() -> None:
    conn = sqlite3.connect(f"file:{WING_DB}?mode=ro&immutable=1", uri=True)
    try:
        found = conn.execute(
            "SELECT name FROM sqlite_master WHERE name = 'agent_memory_stores'"
        ).fetchall()
    finally:
        conn.close()
    assert not found, (
        "agent_memory_stores still exists in wing.db. The CREATE is gone from "
        "schema-extensions.sql, which is why every offline check above passes — "
        "but a table nothing writes is still a second place an answer can live. "
        "bin/init-db.php drops it; closing this needs a converge (--tags wing)."
    )
