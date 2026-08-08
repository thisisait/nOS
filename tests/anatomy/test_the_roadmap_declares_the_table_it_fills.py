"""The roadmap's definition and the script that fills it must describe one table.

WHAT WAS FOUND, 2026-08-07, reviewing the roadmap. Two artifacts claim to
specify the `nOS Roadmap` DataTable and had never been compared:

  state/keap-tables/roadmap.table.yml   the definition — ~20 columns, and a
                                        long header arguing that separating a
                                        CLAIM (`status`) from an OBSERVATION
                                        (`verified`) is the point of the table
  tools/roadmap-seed.py                 the writer — fills 60 live rows

They disagree, and the disagreement was total rather than marginal:

  * the writer stores three `status` values the definition does not list
    (`active`, `next`, `parked`), so applying the definition to a table KEAP
    validates would reject every row the writer produces;
  * the writer stores a column (`when`) the definition had dropped in favour of
    the `target` / `occurred_at` split;
  * the live table has NINE columns. `verified`, `verified_by`, `verified_at`,
    `evidence`, `kind`, `severity`, `effort`, `source`, `embedding`, `ordinal`
    and `anchor` exist only in the YAML. Measured against the running estate:

        GET /agent/v1/tables -> nOS Roadmap
        columns: slug title parent when status track release refs body
        60 rows · kind=None on 60 · verified=None on 60

The definition has never been applied. Nothing applies it: the playbook seeds
only the three `face-*` tables (`roles/pazny.keap/tasks/seed-face-tables.yml`),
and the roadmap is carved out of that gate's coverage by `UNSEEDED` in
`test_keap_table_concepts.py:130-133` — whose stated reason is about ROWS
("rows come from tools/roadmap-seed.py"), while what is actually unapplied is
the DEFINITION. The carve-out was doing more work than its reason claimed.

WHY THIS IS THE ESTATE'S RECURRING SHAPE AND NOT A TYPO. Two representations of
one fact, in different places, with nothing comparing them — the same defect as
the security tally copied into prose, the pin declared twice, the four meanings
of "tier". Here it cost the table its whole thesis: the column that was supposed
to let a row say "someone claims this shipped and a probe disagrees" does not
exist in the database, so no row can say it.

WHAT THIS GATE DOES AND DOES NOT COVER. It compares the two GIT artifacts, which
is all a test with no network can do. It cannot see the live table — that
remains the reader's job (`tools/roadmap-status.py`, which reports the applied
column set and says so plainly when the definition and the live table differ).
So a green run here means "the writer and the definition agree", never "the
definition is applied".
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
DEF = REPO / "state/keap-tables/roadmap.table.yml"
SEEDER = REPO / "tools/roadmap-seed.py"


def declared_columns() -> dict[str, dict]:
    spec = yaml.safe_load(DEF.read_text(encoding="utf-8"))
    return {c["key"]: c for c in spec["schema"]["columns"]}


def seeder_source() -> str:
    return SEEDER.read_text(encoding="utf-8")


def seeder_written_columns() -> set[str]:
    """The keys `row()` puts into a row dict.

    Read from the AST rather than by regex: the point of this gate is that the
    two artifacts are compared by something that cannot be fooled by a comment.
    """
    tree = ast.parse(seeder_source())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "row":
            for call in ast.walk(node):
                if (
                    isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Name)
                    and call.func.id == "dict"
                ):
                    return {kw.arg for kw in call.keywords if kw.arg}
    pytest.fail("tools/roadmap-seed.py no longer defines row() as a dict(...) — "
                "update this gate to read the new shape rather than deleting it.")


def seeder_written_statuses() -> set[str]:
    """Every string literal passed as `row(..., status=...)`, positional or not."""
    tree = ast.parse(seeder_source())
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "row":
            if len(node.args) >= 4 and isinstance(node.args[3], ast.Constant):
                found.add(node.args[3].value)
            for kw in node.keywords:
                if kw.arg == "status" and isinstance(kw.value, ast.Constant):
                    found.add(kw.value.value)
    if not found:
        pytest.fail("no row() status literals found — the seeder's shape changed; "
                    "teach this gate the new one.")
    return found


def test_every_status_the_seeder_writes_is_declared():
    """A value the writer stores that the definition forbids is a row that would
    be rejected the day the definition is applied — i.e. a failure deferred to
    the worst possible moment."""
    declared = set(declared_columns()["status"]["options"])
    written = seeder_written_statuses()
    undeclared = sorted(written - declared)
    assert not undeclared, (
        f"tools/roadmap-seed.py writes status values that "
        f"state/keap-tables/roadmap.table.yml does not declare: {undeclared}.\n"
        f"Declared: {sorted(declared)}\n"
        "Either declare them, or change the writer — but do not leave the board's "
        "vocabulary split across two files that never meet."
    )


def test_every_column_the_seeder_writes_is_declared():
    """Same law, one level down. A column the writer fills and the definition
    omits cannot survive the definition being applied."""
    declared = set(declared_columns())
    written = seeder_written_columns()
    undeclared = sorted(written - declared)
    assert not undeclared, (
        f"tools/roadmap-seed.py writes columns absent from "
        f"state/keap-tables/roadmap.table.yml: {undeclared}.\n"
        "Declare them (deprecating one is fine and honest) or migrate the writer."
    )


def test_the_deprecated_when_column_names_its_successors():
    """`when` survives only as a migration waypoint.

    The definition splits an intention (`target`) from a fact (`occurred_at`)
    precisely so the table can answer "did this land when we said it would",
    which one date column cannot. `when` is kept so the definition describes the
    table that EXISTS — but a deprecated column with no stated successor is how
    a temporary compromise becomes permanent, so the deprecation must say what
    replaces it and both successors must be declared.
    """
    cols = declared_columns()
    if "when" not in cols:
        pytest.skip("`when` is gone — the migration completed; nothing left to pin.")
    for successor in ("target", "occurred_at"):
        assert successor in cols, (
            f"`when` is declared deprecated but `{successor}` is not declared — "
            "a deprecation pointing at a column that does not exist is not a plan."
        )
    src = DEF.read_text(encoding="utf-8")
    block = src[max(0, src.find("key: when") - 800):src.find("key: when") + 200]
    assert "DEPRECATED" in block, (
        "state/keap-tables/roadmap.table.yml declares `when` without marking it "
        "DEPRECATED. It exists only because the live table has it and the "
        "target/occurred_at migration has not run; an unmarked column reads as a "
        "design choice."
    )


def test_the_seeder_still_records_that_the_migration_is_owed():
    """The one thing that must not quietly disappear.

    `roadmap-seed.py` documents the owed `when` -> `target`/`occurred_at`
    migration in its own docstring and deliberately does not perform it, because
    doing it inside a seeding pass would rewrite dates nobody asked to have
    rewritten. If that paragraph is deleted while `when` is still the column
    being written, the debt becomes invisible — which is how it stayed invisible
    for the five days between the definition landing and this review.
    """
    if "when" not in declared_columns():
        pytest.skip("`when` is gone — the migration completed.")
    doc = ast.get_docstring(ast.parse(seeder_source())) or ""
    assert re.search(r"occurred_at", doc), (
        "tools/roadmap-seed.py no longer documents the owed target/occurred_at "
        "migration, but still writes `when`. Restore the paragraph, or do the "
        "migration and drop `when` from the definition."
    )
