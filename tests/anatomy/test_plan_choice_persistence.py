"""Anatomy CI gate — plan-choice / coexistence state-machine schema + link writes
(Phase B / B1 schema, B3 repos+API).

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

…and the B3 repos+API link writes (§3.1/§5):

  - UpgradeRepository::planUpgradeWithMode stamps upgrades_planned.plan_mode and,
    for the coexist branch, writes coexistence_planned.parent_upgrade_id + the
    back-link upgrades_planned.coexistence_planned_id.
  - CoexistenceRepository::planCoexistence carries the trailing parentUpgradeId /
    dataCopy and persists them.
  - Api\\UpgradesPresenter::actionPlanChoice defaults dry_run TRUE and rejects a
    body-supplied identity (anti-spoof).
  - the routes for plan-choice / promote / deactivate / cancel / migrations
    authored are registered.

Static source assertions catch a regression even where php is unavailable; the
functional fresh-DB build (skipped if php/sqlite3 is missing) proves the columns,
table, and partial-index invariant actually materialize AND that the link columns
round-trip a coexist plan-choice.
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
MODEL = REPO / "files/anatomy/wing/app/Model"
API = REPO / "files/anatomy/wing/app/Presenters/Api"
ROUTER = REPO / "files/anatomy/wing/app/Core/RouterFactory.php"

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


# ── B3: repos + API link writes ────────────────────────────────────────────

def test_plan_upgrade_with_mode_writes_links():
    """UpgradeRepository::planUpgradeWithMode stamps plan_mode and, for coexist,
    writes parent_upgrade_id into coexistence_planned AND back-links
    coexistence_planned_id onto upgrades_planned."""
    src = (MODEL / "UpgradeRepository.php").read_text()
    assert "function planUpgradeWithMode" in src, "planUpgradeWithMode missing"
    # The coexist branch hands off to the coexistence queue with the parent id.
    assert "planCoexistence" in src, "coexist branch must call planCoexistence"
    assert "'plan_mode'" in src and "$mode" in src, "must stamp plan_mode"
    assert "'coexistence_planned_id'" in src, "must back-link coexistence_planned_id"
    # Reuses planUpgrade (keeps the recipeMismatch guard) rather than re-inserting.
    assert "$this->planUpgrade(" in src, "must reuse planUpgrade (mismatch guard intact)"


def test_plan_coexistence_carries_parent_upgrade_id():
    """CoexistenceRepository::planCoexistence accepts the trailing
    parentUpgradeId + dataCopy and persists parent_upgrade_id + data_copy."""
    src = (MODEL / "CoexistenceRepository.php").read_text()
    assert "?int $parentUpgradeId" in src, "planCoexistence must accept parentUpgradeId"
    assert "'parent_upgrade_id'" in src, "must persist parent_upgrade_id"
    assert "'data_copy'" in src, "must persist data_copy"
    # cancelPlanned writes the never-before-written 'cancelled' status.
    assert "function cancelPlanned" in src, "cancelPlanned (the missing dequeue) missing"
    assert "'cancelled'" in src and "'cancelled_at'" in src, "cancel must stamp cancelled + cancelled_at"


def test_coexistence_repo_promote_deactivate_passthroughs():
    """promote/deactivate are BoxAPI passthroughs to the B2 Bone routes."""
    src = (MODEL / "CoexistenceRepository.php").read_text()
    assert "function promote" in src and "/promote/" in src, "promote passthrough missing"
    assert "function deactivate" in src and "/deactivate/" in src, "deactivate passthrough missing"


def test_upgrade_repo_injects_coexistence_repository():
    """UpgradeRepository wires CoexistenceRepository via the constructor (Nette
    DI), and both repos are registered in common.neon (autowired by type)."""
    src = (MODEL / "UpgradeRepository.php").read_text()
    assert "private CoexistenceRepository $coexistence" in src, "must inject CoexistenceRepository"
    neon = (REPO / "files/anatomy/wing/app/config/common.neon").read_text()
    assert "App\\Model\\CoexistenceRepository" in neon
    assert "App\\Model\\MigrationAuthoredRepository" in neon, "new repo must be DI-registered"


def test_migration_authored_repo_review_status_gate():
    """MigrationAuthoredRepository exists and setReviewStatus REFUSES 'merged' —
    merged is the forge-merge's exclusive write (GATE 2), never Wing's."""
    path = MODEL / "MigrationAuthoredRepository.php"
    assert path.is_file(), "MigrationAuthoredRepository missing"
    src = path.read_text()
    for m in ("function forService", "function listReviewable", "function setReviewStatus", "function insertAuthored"):
        assert m in src, f"MigrationAuthoredRepository missing {m}"
    # The gate: only in_review / rejected are settable by Wing.
    assert "['in_review', 'rejected']" in src, "Wing must only set in_review / rejected"
    assert "'draft'" in src, "insertAuthored must land at draft"


def test_plan_choice_api_dry_run_default_true_and_anti_spoof():
    """Api\\UpgradesPresenter::actionPlanChoice defaults dry_run TRUE and rejects
    a body-supplied planned_by (anti-spoof, bearer-derived identity)."""
    src = (API / "UpgradesPresenter.php").read_text()
    assert "function actionPlanChoice" in src, "actionPlanChoice missing"
    # dry_run defaults true: explicit cast of body['dry_run'] with a true fallback.
    assert "array_key_exists('dry_run', $body) ? (bool) $body['dry_run'] : true" in src, \
        "dry_run must default TRUE"
    assert "planned_by is derived from the bearer token identity" in src, "anti-spoof gate missing"
    assert "plan_choice_recorded" in src, "must emit plan_choice_recorded"


def test_coexistence_api_lifecycle_actions_anti_spoof():
    """Api\\CoexistencePresenter gains cancel/promote/deactivate; each rejects a
    body-supplied identity and (cancel) emits coexistence_cancel."""
    src = (API / "CoexistencePresenter.php").read_text()
    for m in ("function actionCancel", "function actionPromote", "function actionDeactivate"):
        assert m in src, f"CoexistencePresenter missing {m}"
    assert "cancelled_by is derived from the bearer token identity" in src
    assert "actor_id is derived from the bearer token identity" in src
    assert "coexistence_cancel" in src and "coexistence_promote" in src and "coexistence_demote" in src


def test_migrations_authored_producer_anti_spoof():
    """POST /api/v1/migrations/authored: author_agent/actor_id are bearer-derived,
    never body-supplied (same anti-spoof gate as actionQueue)."""
    src = (API / "MigrationsPresenter.php").read_text()
    assert "function actionAuthored" in src, "actionAuthored producer missing"
    assert "author_agent / actor_id are derived from the bearer token identity" in src
    assert "migration_authored" in src and "migration_pr_opened" in src


def test_b3_routes_registered():
    """The plan-choice / lifecycle / authored routes are registered, and the
    catch-all-swallowable ones come BEFORE their generic siblings."""
    src = ROUTER.read_text()
    assert "Upgrades:planChoice" in src
    assert "Coexistence:promote" in src and "Coexistence:deactivate" in src and "Coexistence:cancel" in src
    assert "Migrations:authored" in src
    # first-match-wins ordering: /authored before [/<id>]; promote/deactivate/cancel
    # before /cleanup/<tag>; plan-choice before the general /<service>/<recipe>.
    assert src.index("Migrations:authored") < src.index("api/v1/migrations[/<id>]")
    assert src.index("Coexistence:cancel") < src.index("Coexistence:cleanup")
    assert src.index("Upgrades:planChoice") < src.index("api/v1/upgrades/<service>/<recipe>'")


# ── Functional proof: a coexist plan-choice round-trips the link columns ────

@pytest.mark.skipif(
    shutil.which("php") is None, reason="php unavailable — skip live DB build"
)
def test_fresh_db_round_trips_plan_choice_links():
    """A fresh init-db'd wing.db persists the plan-choice link columns the way
    planUpgradeWithMode writes them: a coexist upgrades_planned row carrying
    plan_mode='coexist' + coexistence_planned_id, joined to a coexistence_planned
    row carrying the same parent_upgrade_id."""
    with tempfile.TemporaryDirectory(prefix="wing-b3-") as tmp:
        proc = subprocess.run(
            ["php", str(INITDB), f"--data-dir={tmp}"],
            capture_output=True, text=True,
        )
        assert proc.returncode == 0, f"init-db.php failed: {proc.stderr}"
        con = sqlite3.connect(str(pathlib.Path(tmp) / "wing.db"))
        try:
            # The upgrade-side row (mode b).
            cur = con.execute(
                "INSERT INTO upgrades_planned(service,recipe_id,status,plan_mode) "
                "VALUES('postgresql','16-to-17','planned','coexist')"
            )
            upgrade_id = cur.lastrowid
            # The coexistence-side row back-references the upgrade row.
            cur = con.execute(
                "INSERT INTO coexistence_planned"
                "(service,tag,status,parent_upgrade_id,data_copy) "
                "VALUES('postgresql','v17','planned',?,1)",
                (upgrade_id,),
            )
            coexist_id = cur.lastrowid
            # …and the upgrade row back-links the coexistence row.
            con.execute(
                "UPDATE upgrades_planned SET coexistence_planned_id=? WHERE id=?",
                (coexist_id, upgrade_id),
            )
            con.commit()

            # The join the matrix / consumer relies on must resolve both ways.
            row = con.execute(
                "SELECT u.plan_mode, u.coexistence_planned_id, c.parent_upgrade_id, c.data_copy "
                "FROM upgrades_planned u "
                "JOIN coexistence_planned c ON c.id = u.coexistence_planned_id "
                "WHERE u.id = ?",
                (upgrade_id,),
            ).fetchone()
            assert row is not None, "link join did not resolve"
            assert row[0] == "coexist", "plan_mode not persisted"
            assert row[1] == coexist_id, "coexistence_planned_id back-link wrong"
            assert row[2] == upgrade_id, "parent_upgrade_id not persisted"
            assert row[3] == 1, "data_copy not persisted"
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
