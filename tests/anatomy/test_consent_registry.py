"""Anatomy CI gate — GDPR consent registry (Art. 6(1)(a) + Art. 7).

Pins, statically (no Docker, no Wing boot — mirrors test_gdpr_dsar_status.py):
  - the gdpr_consent table + columns exist in schema-extensions.sql with NO
    active-consent partial index there (it references the ALTER-added
    withdrawn_at -> must live in init-db.php post-sweep);
  - init-db.php ALTER-sweeps gdpr_consent and creates idx_gdpr_consent_active
    AFTER the sweep (the schema-ordering lesson);
  - the init-db updated_at ALTER is the portable plain-'TEXT' variant (no
    parenthesised non-constant default ambiguity);
  - GdprRepository has recordConsent / withdrawConsent / listConsent /
    pseudonymiseSubject with the by-id OR subject+activity withdrawal contract +
    the refuse-mass-withdraw guard;
  - record-consent.php mirrors record-dsar.php (--json grant, --withdraw=<id>,
    --withdraw-subject + --activity, same exit-code contract);
  - consent_granted / consent_withdrawn are whitelisted on BOTH event sides;
  - the SSO gate is NOT advertised as consent (decoupling docstring landed) and
    consent_capture_satisfied exists but is NOT called by the runner.
"""
from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
SCHEMA = REPO / "files/anatomy/wing/db/schema-extensions.sql"
INITDB = REPO / "files/anatomy/wing/bin/init-db.php"
REPOSITORY = REPO / "files/anatomy/wing/app/Model/GdprRepository.php"
RECORD = REPO / "files/anatomy/wing/bin/record-consent.php"
BONE = REPO / "files/anatomy/bone/events.py"
WING_EVENTS = REPO / "files/anatomy/wing/app/Model/EventRepository.php"
PARSER = REPO / "files/anatomy/module_utils/nos_app_parser.py"
RUNNER = REPO / "files/anatomy/library/nos_apps_render.py"

CONSENT_COLS = [
    "subject_email", "processing_id", "activity", "lawful_basis",
    "tos_version_hash", "source", "granted_at", "withdrawn_at",
    "notes", "created_at", "updated_at",
]


def test_schema_declares_consent_table_and_columns():
    src = SCHEMA.read_text()
    assert "CREATE TABLE IF NOT EXISTS gdpr_consent" in src
    for col in CONSENT_COLS:
        assert col in src, f"gdpr_consent column missing in schema: {col}"


def test_active_index_not_in_schema_extensions():
    """The active-consent partial index references withdrawn_at (ALTER-added),
    so it must NOT live in schema-extensions.sql (would fail on a pre-existing
    DB) — same rule as idx_events_row_hash + the WORM triggers."""
    assert "idx_gdpr_consent_active" not in SCHEMA.read_text(), (
        "idx_gdpr_consent_active references the ALTER-added withdrawn_at column "
        "and MUST be created in init-db.php AFTER the ALTER sweep, not here"
    )


def test_initdb_sweeps_consent_and_creates_active_index_post_sweep():
    src = INITDB.read_text()
    assert "$addMissingColumns($db, 'gdpr_consent'" in src
    assert "idx_gdpr_consent_active" in src
    assert "WHERE withdrawn_at IS NULL" in src
    sweep_at = src.index("$addMissingColumns($db, 'gdpr_consent'")
    index_at = src.index("idx_gdpr_consent_active")
    assert index_at > sweep_at, (
        "idx_gdpr_consent_active must be created AFTER the gdpr_consent ALTER "
        "sweep (the schema-ordering lesson)"
    )


def test_initdb_updated_at_alter_is_portable_plain_text():
    """The ambiguity all three reviewers flagged: the updated_at ALTER must be
    plain 'TEXT' (portable), NOT a parenthesised non-constant default. There
    must be exactly ONE shipped variant."""
    src = INITDB.read_text()
    sweep = src[src.index("$addMissingColumns($db, 'gdpr_consent'"):]
    sweep = sweep[: sweep.index("]);") + 3]
    assert re.search(r"'updated_at'\s*=>\s*'TEXT'", sweep), (
        "the gdpr_consent updated_at ALTER must be plain 'TEXT'"
    )
    assert "datetime('now')" not in sweep, (
        "no non-constant default in the gdpr_consent ALTER sweep (portability)"
    )


def test_repository_has_consent_methods():
    src = REPOSITORY.read_text()
    assert "public function recordConsent(" in src
    assert "public function withdrawConsent(" in src
    assert "public function listConsent(" in src
    assert "public function pseudonymiseSubject(" in src
    assert "subjectEmail" in src and "activity" in src
    # refuse-to-mass-withdraw guard (no addressing -> 0 rows)
    assert "return 0;" in src
    # grant inserts an ACTIVE row (withdrawn_at NULL) — whitespace-tolerant
    assert re.search(r"'withdrawn_at'\s*=>\s*null", src), (
        "recordConsent must insert withdrawn_at => null (active row)"
    )


def test_record_consent_cli_mirrors_dsar_shape():
    src = RECORD.read_text()
    assert "--json=" in src
    assert "--withdraw=" in src
    assert "--withdraw-subject=" in src
    assert "--activity=" in src
    assert "recordConsent" in src and "withdrawConsent" in src
    assert "Booting::boot()->createContainer()" in src
    assert "exit(2)" in src and "exit(3)" in src


def test_consent_events_whitelisted_both_sides():
    bone = BONE.read_text()
    wing = WING_EVENTS.read_text()
    for ev in ("consent_granted", "consent_withdrawn"):
        assert f'"{ev}"' in bone, f"{ev} missing from Bone VALID_TYPES"
        assert f"'{ev}'" in wing, f"{ev} missing from Wing EventRepository::VALID_TYPES"


def test_sso_gate_decoupled_and_predicate_not_wired():
    """The decoupling landed AND the predicate is honestly inert: the SSO gate
    docstring no longer equates SSO with consent, consent_capture_satisfied
    exists, and the runner does NOT call it (no phantom enforcement)."""
    parser = PARSER.read_text()
    assert "def consent_capture_satisfied(" in parser
    assert "CONSENT_CAPTURE_MECHANISMS" in parser
    assert 'SSO is AUTHENTICATION' in parser or "SSO == consent" in parser
    runner = RUNNER.read_text()
    assert "consent_capture_satisfied" not in runner, (
        "consent_capture_satisfied must NOT be wired into the runner — it is "
        "pure additive forward-ready metadata (no phantom enforcement gate)"
    )
    assert "app_require_consent_capture" not in runner, (
        "the phantom app_require_consent_capture var must not exist"
    )
