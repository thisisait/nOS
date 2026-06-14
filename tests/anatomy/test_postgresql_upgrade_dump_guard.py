"""Gate: every PostgreSQL major-upgrade recipe's logical-dump step is idempotent.

The cutover apply phase WIPES the data dir (``rm -rf {{ postgresql_data_dir }}/*``)
after taking a ``pg_dumpall`` into ``~/.nos/backups/<upgrade_id>/pgdumpall.sql``.
That dump is the ONLY logical copy of the pre-cutover cluster. If the operator
re-runs ``--tags upgrade -e upgrade_service=postgresql`` after a mid-apply hiccup,
a ``sql_dump_all`` step WITHOUT a ``creates:`` guard re-fires ``pg_dumpall`` —
against an already-wiped / freshly-restored cluster — and CLOBBERS the good
pre-cutover dump with an empty (or post-restore) one. Silent data loss.

The ``15-to-16`` recipe carried the ``creates:`` guard; the ``16-to-17`` recipe
shipped without it (operator cutover path was never exercised). This gate pins
the guard on EVERY ``sql_dump_all`` step so no current or future major-bump
recipe can ship the dump-before-wipe without idempotency parity.
"""
from __future__ import annotations

import pathlib

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
RECIPE = REPO / "upgrades" / "postgresql.yml"

# Steps that perform the destructive pre-cutover logical dump. Any step with
# this id, in any recipe's `pre` phase, must be re-run-safe.
DUMP_STEP_ID = "sql_dump_all"


def _recipes():
    doc = yaml.safe_load(RECIPE.read_text())
    return doc.get("recipes", [])


def test_recipe_file_parses_and_has_recipes():
    recipes = _recipes()
    assert recipes, "upgrades/postgresql.yml declares no recipes"


def test_every_sql_dump_all_step_has_creates_guard():
    offenders = []
    seen = 0
    for recipe in _recipes():
        for step in recipe.get("pre", []) or []:
            if step.get("id") != DUMP_STEP_ID:
                continue
            seen += 1
            creates = step.get("creates")
            if not (isinstance(creates, str) and "pgdumpall.sql" in creates):
                offenders.append(recipe.get("id", "<no-id>"))
    assert seen, (
        "no %r step found in any PostgreSQL recipe — has the dump step been "
        "renamed? Update this gate." % DUMP_STEP_ID)
    assert not offenders, (
        "PostgreSQL cutover recipe(s) %r have a %r step with NO `creates:` "
        "idempotency guard. A re-run re-fires pg_dumpall and overwrites the "
        "good pre-cutover dump with an empty one (silent data loss). Add "
        "`creates: \"~/.nos/backups/{{ upgrade_id }}/pgdumpall.sql\"`."
        % (offenders, DUMP_STEP_ID))
