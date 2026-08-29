"""The wing.db contract must describe the whole file, not one organ's half.

FOUND 2026-08-29 by `tools/wing-status.py`, which buckets a table that exists in
the database and in no committed schema as UNDECLARED and found four:
`loop_proposals`, `loop_judge_runs`, `loop_verdicts`, `loop_forgets`.

Bone creates them. They live in Wing's file — deliberately, so a proposal can
name the `agent_sessions` row that authored it — but only Wing ran an exporter,
so the artifact named "the wing.db schema" described 41 of the 45 tables that
exist. The cost was already being paid: three gates that build fixtures from the
contract had to import `ledger._DDL` themselves to get a database their subject
could run against, and each carried a paragraph explaining why.

`bin/export-schema.php` now applies Bone's `ensure_schema()` to the temp build
and exits non-zero if it cannot — half a contract that still calls itself the
contract is worse than none.

This gate compares the two artifacts directly rather than trusting the exporter
ran: CI regenerates and diffs, which catches a stale file, but would happily
diff two equally incomplete ones.
"""

from __future__ import annotations

import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
CONTRACT = REPO / "files/anatomy/skills/contracts/wing.db-schema.sql"
EXPORTER = REPO / "files/anatomy/wing/bin/export-schema.php"

sys.path.insert(0, str(REPO / "files/anatomy/bone"))
import ledger  # noqa: E402 — imported for its DDL, not its behaviour


def _tables(sql: str) -> set[str]:
    return set(re.findall(r"CREATE TABLE (?:IF NOT EXISTS )?(\w+)", sql))


def test_every_table_bone_creates_is_in_the_contract() -> None:
    missing = sorted(_tables(ledger._DDL) - _tables(CONTRACT.read_text(encoding="utf-8")))
    assert not missing, (
        f"{missing} are created by Bone in wing.db and absent from the "
        "committed contract. Regenerate with `php files/anatomy/wing/bin/"
        "export-schema.php --db=/nonexistent/wing.db`; if that does not add "
        "them, the exporter stopped applying Bone's DDL.")


def test_the_columns_bone_adds_later_are_in_the_contract() -> None:
    """`_ADDED_COLUMNS` are ALTERs applied after the first cut of the DDL, so a
    contract built from `_DDL` alone would name the tables and miss the columns
    — `session_uuid` among them, which is the join the loop dashboard is."""
    body = CONTRACT.read_text(encoding="utf-8")
    for table, column, _ in ledger._ADDED_COLUMNS:
        block = re.search(rf"CREATE TABLE (?:IF NOT EXISTS )?{table}\b.*?\n\);",
                          body, re.S)
        assert block, f"{table} missing from the contract entirely"
        assert re.search(rf"\b{column}\b", block.group(0)), (
            f"{table}.{column} is added by Bone at open time and is not in the "
            "contract — a fixture built from it would fail on that column only")


def test_the_exporter_refuses_a_partial_artifact() -> None:
    """The failure mode this replaces is silent: a missing python3, or a Bone
    import error, and the exporter carries on and writes Wing's half under the
    old name."""
    src = EXPORTER.read_text(encoding="utf-8")
    assert "ledger.ensure_schema" in src, "the exporter no longer applies Bone's DDL"
    assert "refusing to export a partial" in src and "exit(1)" in src
