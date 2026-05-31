"""Anatomy gate: tamper-evident audit hash-chain is default-OFF, gov-local opt-in.

Pins (a) default.config.yml ships wing_audit_chain_enabled: false (normal run
inert), (b) profiles/gov-local.yml opts it in alongside enforce_mfa +
require_disk_encryption, (c) the gov-local header no longer describes the audit
log as un-togglable (structural invariant, not exact marketing wording), and
(d) post.yml has a wing_audit_chain_enabled-gated backfill-event-chain.php task.

Pure file-read / yaml-parse — runs in standing pytest CI, never in a playbook.
"""
from __future__ import annotations

import pathlib

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
GOV = REPO / "profiles" / "gov-local.yml"
CFG = REPO / "default.config.yml"
POST = REPO / "roles" / "pazny.wing" / "tasks" / "post.yml"


def test_default_config_ships_chain_off():
    assert "wing_audit_chain_enabled: false" in CFG.read_text(), \
        "default.config.yml must keep the audit chain OFF (normal run inert)"


def test_gov_local_opts_in():
    assert "wing_audit_chain_enabled: true" in GOV.read_text()


def test_gov_local_three_gov_controls_all_true():
    doc = yaml.safe_load(GOV.read_text())
    assert doc.get("wing_audit_chain_enabled") is True
    assert doc.get("enforce_mfa") is True
    assert doc.get("require_disk_encryption") is True


def test_gov_local_no_longer_calls_audit_untogglable():
    # Structural invariant: no single line both says "not yet togglable" AND
    # mentions "audit" — the chain is now a real toggle. Avoids pinning exact
    # header wording (which is free to evolve).
    for line in GOV.read_text().splitlines():
        low = line.lower()
        assert not ("not yet togglable" in low and "audit" in low), \
            f"gov-local still describes the audit chain as un-togglable: {line!r}"


def test_post_yml_has_chain_gated_anchor_task():
    src = POST.read_text()
    assert "backfill-event-chain.php" in src, "post.yml must run the chain anchor backfill"
    assert "wing_audit_chain_enabled" in src, "the anchor task must be gated on the chain flag"
