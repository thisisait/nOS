"""Anatomy CI gate — plan-choice / coexistence state-machine schema (Phase B / B1).

Pins the B1 data-model surface from
docs/plans/agentic-upgrade-migration-coexistence-design.md §2:

  - NEW table `migrations_authored` lives in schema-extensions.sql
    (CREATE TABLE IF NOT EXISTS — a new table, NOT a column on an existing one).
  - NEW columns on the EXISTING coexistence/upgrade tables land via the
    init-db.php `$addMissingColumns` ALTER sweep — never in schema-extensions.sql
    (where CREATE TABLE IF NOT EXISTS is a no-op on a pre-existing wing.db).
  - the `uq_coexist_one_primary` partial index references the ALTER-added `role`
    column, so it is created AFTER the sweep (same ordering rule as
    idx_events_row_hash / idx_gdpr_consent_active).

Static source assertions catch a regression even where php is unavailable; the
functional fresh-DB build (skipped if php/sqlite3 is missing) proves the columns,
table, and partial-index invariant actually materialize.
"""
from __future__ import annotations

import pathlib
import shutil
import sqlite3
import subprocess
import tempfile

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
SCHEMA = REPO / "files/anatomy/wing/db/schema-extensions.sql"
INITDB = REPO / "files/anatomy/wing/bin/init-db.php"

# migrations_authored — the recipe→migration promotion record (NEW table).
MIG_AUTHORED_COLS = [
    "uuid", "service", "recipe_id", "migration_id", "plan_mode",
    "from_version", "to_version", "severity", "title", "artifact_kind",
    "artifact_path", "forge", "mr_url", "forge_branch", "committed_sha",
    "review_status", "rejected_reason", "author_agent", "session_uuid",
    "actor_id", "actor_action_id", "applied_migration_id",
    "created_at", "updated_at",
]

# ALTER-sweep columns on the existing tables (§2.2-2.4).
COEXIST_TRACKS_NEW = [
    "role", "lifecycle", "source_migration_id", "promoted_at", "deactivated_at",
]
COEXIST_PLANNED_NEW = [
    "parent_upgrade_id", "source_migration_uuid", "data_copy",
    "cancelled_at", "cancelled_by",
]
UPGRADES_PLANNED_NEW = [
    "plan_mode", "coexistence_planned_id", "migration_uuid", "plan_choice_at",
]


# ── New TABLE lives in schema-extensions.sql ───────────────────────────────

def test_migrations_authored_table_in_schema_extensions():
    src = SCHEMA.read_text()
    assert "CREATE TABLE IF NOT EXISTS migrations_authored" in src, (
        "migrations_authored is a NEW table — it must be declared in "
        "schema-extensions.sql, not in the init-db.php ALTER sweep"
    )
    for col in MIG_AUTHORED_COLS:
        assert col in src, f"migrations_authored column missing in schema: {col}"
    # The delete-prior flip key mirrors upgrades_planned.UNIQUE(service,recipe_id,status).
    assert "UNIQUE (service, recipe_id, review_status)" in src
    for idx in (
        "idx_mig_authored_service",
        "idx_mig_authored_status",
        "idx_mig_authored_session",
    ):
        assert idx in src, f"migrations_authored index missing: {idx}"


def test_migrations_authored_not_in_alter_sweep():
    """A new table must NOT be ALTER-swept (it's created whole in the DDL)."""
    src = INITDB.read_text()
    assert "$addMissingColumns($db, 'migrations_authored'" not in src, (
        "migrations_authored is a NEW table — CREATE it in schema-extensions.sql, "
        "do not ALTER-sweep it"
    )


# ── New COLUMNS on existing tables land in the init-db.php ALTER sweep ──────

def test_coexistence_tracks_columns_in_alter_sweep():
    src = INITDB.read_text()
    assert "$addMissingColumns($db, 'coexistence_tracks'" in src
    sweep = _sweep_block(src, "coexistence_tracks")
    for col in COEXIST_TRACKS_NEW:
        assert f"'{col}'" in sweep, f"coexistence_tracks ALTER sweep missing {col}"


def test_coexistence_planned_columns_in_alter_sweep():
    src = INITDB.read_text()
    # The table is swept twice (the legacy target_version sweep + the B1 sweep);
    # assert the B1 columns are present somewhere in the file.
    for col in COEXIST_PLANNED_NEW:
        assert f"'{col}'" in src, f"coexistence_planned ALTER sweep missing {col}"


def test_upgrades_planned_columns_in_alter_sweep():
    src = INITDB.read_text()
    assert "$addMissingColumns($db, 'upgrades_planned'" in src
    sweep = _sweep_block(src, "upgrades_planned")
    for col in UPGRADES_PLANNED_NEW:
        assert f"'{col}'" in sweep, f"upgrades_planned ALTER sweep missing {col}"


def test_new_columns_not_in_schema_extensions_create_table():
    """The ALTER-added columns must NOT appear in the existing CREATE TABLE bodies
    in schema-extensions.sql (CREATE TABLE IF NOT EXISTS is a no-op on an existing
    DB, so adding them there would silently never apply on upgrade)."""
    src = SCHEMA.read_text()
    create_block = _create_table_block(src, "coexistence_tracks")
    for col in COEXIST_TRACKS_NEW:
        assert col not in create_block, (
            f"{col} must be ALTER-swept in init-db.php, not added to the "
            "coexistence_tracks CREATE TABLE (no-op on existing DBs)"
        )
    create_block = _create_table_block(src, "upgrades_planned")
    for col in UPGRADES_PLANNED_NEW:
        assert col not in create_block, (
            f"{col} must be ALTER-swept in init-db.php, not added to the "
            "upgrades_planned CREATE TABLE"
        )


# ── Single-primary partial index, created AFTER the sweep ──────────────────

def test_one_primary_index_after_sweep_and_not_in_schema():
    """uq_coexist_one_primary references the ALTER-added `role` column, so it
    lives in init-db.php AFTER the coexistence_tracks sweep, never in
    schema-extensions.sql (would fail 'no such column: role' on existing DBs)."""
    assert "uq_coexist_one_primary" not in SCHEMA.read_text(), (
        "uq_coexist_one_primary references ALTER-added role — must be created "
        "in init-db.php after the sweep, not in schema-extensions.sql"
    )
    src = INITDB.read_text()
    assert "uq_coexist_one_primary" in src
    assert "WHERE role = 'primary'" in src
    sweep_at = src.index("$addMissingColumns($db, 'coexistence_tracks'")
    index_at = src.index("uq_coexist_one_primary")
    assert index_at > sweep_at, (
        "uq_coexist_one_primary must be created AFTER the coexistence_tracks "
        "ALTER sweep (role must exist first)"
    )


# ── Functional proof: a fresh init-db'd wing.db carries it all ─────────────

@pytest.mark.skipif(
    shutil.which("php") is None, reason="php unavailable — skip live DB build"
)
def test_fresh_db_materializes_schema_and_enforces_one_primary():
    with tempfile.TemporaryDirectory(prefix="wing-b1-") as tmp:
        proc = subprocess.run(
            ["php", str(INITDB), f"--data-dir={tmp}"],
            capture_output=True, text=True,
        )
        assert proc.returncode == 0, f"init-db.php failed: {proc.stderr}"
        db = pathlib.Path(tmp) / "wing.db"
        assert db.is_file(), "init-db.php produced no wing.db"

        con = sqlite3.connect(str(db))
        try:
            def cols(table: str) -> set[str]:
                return {r[1] for r in con.execute(f"PRAGMA table_info({table})")}

            assert set(MIG_AUTHORED_COLS) <= cols("migrations_authored")
            assert set(COEXIST_TRACKS_NEW) <= cols("coexistence_tracks")
            assert set(COEXIST_PLANNED_NEW) <= cols("coexistence_planned")
            assert set(UPGRADES_PLANNED_NEW) <= cols("upgrades_planned")

            # The single-primary invariant must actually reject two primaries
            # for one service (a legitimate toggle demotes the old one first).
            con.execute(
                "INSERT INTO coexistence_tracks(service,tag,role) "
                "VALUES('pg','v16','primary')"
            )
            with pytest.raises(sqlite3.IntegrityError):
                con.execute(
                    "INSERT INTO coexistence_tracks(service,tag,role) "
                    "VALUES('pg','v17','primary')"
                )
            # Two SECONDARIES for one service is fine (index is partial).
            con.execute(
                "INSERT INTO coexistence_tracks(service,tag,role) "
                "VALUES('pg','v17','secondary')"
            )
        finally:
            con.close()


# ── helpers ────────────────────────────────────────────────────────────────

def _sweep_block(src: str, table: str) -> str:
    """The text of the FIRST $addMissingColumns(...) sweep for `table`."""
    start = src.index(f"$addMissingColumns($db, '{table}'")
    end = src.index("]);", start) + 3
    return src[start:end]


def _create_table_block(src: str, table: str) -> str:
    """The CREATE TABLE ... ( ... ) body for `table` in the DDL."""
    start = src.index(f"CREATE TABLE IF NOT EXISTS {table}")
    # body ends at the first ');' after the open paren
    open_paren = src.index("(", start)
    end = src.index(");", open_paren)
    return src[open_paren:end]
