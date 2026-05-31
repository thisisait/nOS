"""Anatomy gate: GDPR Art-17 DSAR status is honest (no false 'completed').

Pins the Batch-3 Art-17 correctness fix. The right-to-erasure run used to stamp
gdpr_dsar.status='completed' on ANY confirmed run even when 19/22 services were
only REPORTED (method:manual, not erased) — a legally false record (Art. 12(3)
requires the record to reflect what actually happened). The fix:

  1. intake INSERTs status='received' (proof the request landed),
  2. after executors, the SAME row is --update'd to a terminal status that is
     'completed' ONLY when zero manual steps remain (else 'in-progress').

Also guards bug #2: the Vaultwarden plugin must not advertise the non-existent
`wing-cli vault-erase` command.

Static/text assertions — no Docker, no Wing boot.
"""
from __future__ import annotations

import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]
FORGET = REPO / "tasks/gdpr-forget.yml"
RECORD = REPO / "files/anatomy/wing/bin/record-dsar.php"
REPOSITORY = REPO / "files/anatomy/wing/app/Model/GdprRepository.php"
VW_PLUGIN = REPO / "files/anatomy/plugins/vaultwarden-base/plugin.yml"


def test_intake_records_received_not_completed():
    src = FORGET.read_text()
    # intake row is always 'received' — the request is real before deletion
    assert "'status': 'received'" in src
    # the false-completed footgun must be gone: no ternary that stamps
    # 'completed' at intake based on the confirm flag
    assert "ternary('completed'" not in src, \
        "intake must not pre-stamp 'completed' — that is the bug this gate pins"


def test_terminal_status_gated_on_zero_manual():
    src = FORGET.read_text()
    assert "_forget_terminal" in src, "terminal-status computation must exist"
    # 'completed' is only reachable when manual count == 0 (the decisive guard)
    assert "selectattr('method', 'eq', 'manual') | list | length) == 0" in src
    assert "'in-progress'" in src, "non-complete runs must record 'in-progress'"


def test_terminal_update_invokes_record_dsar_update():
    src = FORGET.read_text()
    assert "--update=" in src and "record-dsar.php" in src, \
        "terminal status must be written via record-dsar.php --update"
    # update only on a confirmed run (dry-run leaves the row at 'received')
    assert "_dsar_id" in src


def test_record_dsar_supports_update_mode():
    src = RECORD.read_text()
    assert "--update=" in src
    assert "updateDsarStatus" in src


def test_repository_has_update_dsar_status():
    src = REPOSITORY.read_text()
    assert "public function updateDsarStatus(" in src
    # 'completed' transition stamps completed_at (lifecycle column)
    assert "completed_at" in src


def test_vaultwarden_dsar_endpoint_is_honest():
    """Bug #2: the dsar_endpoint VALUE is not the non-existent wing-cli command.

    Explanatory prose (comments / the README reason cell) may still NAME the
    command to explain it does not exist — only the live value must be honest.
    """
    for line in VW_PLUGIN.read_text().splitlines():
        stripped = line.strip()
        if stripped.startswith("dsar_endpoint:"):
            assert "wing-cli" not in stripped, \
                "dsar_endpoint must not be set to the non-existent wing-cli vault-erase"
            assert "manual" in stripped.lower(), \
                "dsar_endpoint should state the honest manual mechanism"
            break
    else:
        raise AssertionError("no dsar_endpoint: line found in vaultwarden plugin")


def test_dsar_id_capture_is_scalar_not_backref_list():
    """regex_search with a backref arg ('\\1') returns a LIST (['42']); rendered
    into --update=['42'] it casts to 0 -> the terminal-status update silently
    no-ops and the gdpr_dsar row stays 'received' (the whole honest-status point
    is lost). Both DSAR tasks must capture the id as a SCALAR via the lookbehind
    form. Functional-bug regression guard (the static wiring tests missed it)."""
    for rel in ("tasks/gdpr-forget.yml", "tasks/gdpr-export.yml"):
        src = (REPO / rel).read_text()
        assert "regex_search('(?<=#)[0-9]+')" in src, \
            f"{rel}: capture the DSAR id as a scalar (lookbehind), not a backref list"
