"""Art. 6(1)(f) gate — LIA + Art. 14 data_source on legitimate_interests.

Mirrors consent_capture_satisfied: N/A for every other basis (device-digest
family stays on consent; this row is not a blocker for that family). Live
digest importers that already claim 6f must carry both fields.
"""
from __future__ import annotations

import pathlib
import textwrap

import pytest
import yaml

from module_utils.nos_app_parser import (
    DATA_SOURCE_FLAGS,
    AppParseError,
    consent_capture_satisfied,
    legitimate_interests_satisfied,
    validate,
)
from module_utils import nos_gdpr
from module_utils.nos_digest import device_family_basis_satisfied

REPO = pathlib.Path(__file__).resolve().parents[2]
IMPORTERS_DIR = REPO / "state" / "digest-importers"


def _load_yml(text: str) -> dict:
    return yaml.safe_load(textwrap.dedent(text)) or {}


def test_broken_importer_fixture_is_refused(tmp_path: pathlib.Path):
    """The red case: 6f with no LIA and no data_source fails the gate."""
    path = tmp_path / "broken.importer.yml"
    path.write_text(
        textwrap.dedent(
            """\
            name: fixture-broken-6f
            gdpr:
              purpose: ingest counterparties from a local CSV
              legal_basis: legitimate_interests
              data_categories: ["legal name"]
              data_subjects: ["counterparties"]
              processors: []
              transfers_outside_eu: false
              retention_days: 3650
            """
        ),
        encoding="utf-8",
    )
    rec = yaml.safe_load(path.read_text(encoding="utf-8"))
    ok, reason = legitimate_interests_satisfied(rec)
    assert ok is False
    assert "balancing_test" in reason


def test_complete_importer_fixture_passes(tmp_path: pathlib.Path):
    path = tmp_path / "ok.importer.yml"
    path.write_text(
        textwrap.dedent(
            """\
            name: fixture-ok-6f
            gdpr:
              purpose: ingest counterparties from a local CSV
              legal_basis: legitimate_interests
              balancing_test: >-
                Controller interest is a single accurate party spine for its
                own accounts. Processing is limited to identifiers already in
                the controller's file; no marketing; erasable.
              data_source: not_from_subject
              data_categories: ["legal name"]
              data_subjects: ["counterparties"]
              processors: []
              transfers_outside_eu: false
              retention_days: 3650
            """
        ),
        encoding="utf-8",
    )
    rec = yaml.safe_load(path.read_text(encoding="utf-8"))
    ok, reason = legitimate_interests_satisfied(rec)
    assert ok is True and reason == ""


def test_lia_without_data_source_is_refused():
    rec = _load_yml(
        """\
        gdpr:
          legal_basis: legitimate_interests
          balancing_test: a real LIA sentence that is non-empty
        """
    )
    ok, reason = legitimate_interests_satisfied(rec)
    assert ok is False
    assert "data_source" in reason


def test_blank_balancing_test_is_refused():
    rec = {
        "gdpr": {
            "legal_basis": "legitimate_interests",
            "balancing_test": "   ",
            "data_source": "not_from_subject",
        }
    }
    ok, reason = legitimate_interests_satisfied(rec)
    assert ok is False
    assert "balancing_test" in reason


def test_consent_importer_is_not_forced_onto_6f():
    """Device-digest family: Art. 6(1)(a). Missing LIA must not fail this gate."""
    rec = _load_yml(
        """\
        name: device
        gdpr:
          legal_basis: consent
          retention_days: -1
        """
    )
    ok, reason = legitimate_interests_satisfied(rec)
    assert ok is True and reason == ""
    # Consent capture is a different predicate — this gate stays out of it.
    cap_ok, _ = consent_capture_satisfied(rec)
    assert cap_ok is False


def test_data_source_flags_exported():
    assert DATA_SOURCE_FLAGS == ("from_subject", "not_from_subject")


@pytest.mark.parametrize(
    "path",
    sorted(IMPORTERS_DIR.glob("*.importer.yml")),
    ids=lambda p: p.name,
)
def test_live_6f_importers_declare_lia_and_origin(path: pathlib.Path):
    rec = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    ok, reason = legitimate_interests_satisfied(rec)
    assert ok is True, f"{path.name}: {reason}"

# ── Wave-2 gate: device-family legal basis (importer not yet built) ──
# digest-device-doctrine §2: the device family is Art. 6(1)(a) consent + retention
# -1, NEVER 6(1)(f). The 6f gate accepts a consent basis as N/A and would also
# wave through a device importer CLONED from csv-party — so it cannot catch this.


def _device_importer(**gdpr_extra) -> dict:
    gdpr = {"legal_basis": "consent", "retention_days": -1}
    gdpr.update(gdpr_extra)
    return {"name": "device", "gdpr": gdpr}


def test_device_importer_cloned_from_csv_party_is_refused():
    """The exact clone the doctrine names: legitimate_interests + 3650, with a
    real LIA so the 6f gate is GREEN. device_family_basis_satisfied must refuse."""
    clone = _device_importer(
        legal_basis="legitimate_interests",
        retention_days=3650,
        balancing_test="a real LIA sentence that is non-empty",
        data_source="not_from_subject",
    )
    # The hole: the 6f gate is satisfied by the clone.
    assert legitimate_interests_satisfied(clone) == (True, "")
    # The new gate closes it.
    ok, reason = device_family_basis_satisfied(clone)
    assert ok is False
    assert "consent" in reason


def test_device_importer_with_wrong_retention_is_refused():
    ok, reason = device_family_basis_satisfied(_device_importer(retention_days=3650))
    assert ok is False
    assert "retention_days" in reason


def test_consented_device_importer_passes():
    assert device_family_basis_satisfied(_device_importer()) == (True, "")


def test_non_device_importer_is_not_forced_onto_consent():
    rec = {"name": "csv-party",
           "gdpr": {"legal_basis": "legitimate_interests", "retention_days": 3650}}
    assert device_family_basis_satisfied(rec) == (True, "")


@pytest.mark.parametrize(
    "path",
    sorted(IMPORTERS_DIR.glob("*.importer.yml")),
    ids=lambda p: p.name,
)
def test_live_device_importers_are_consent_and_lifetime(path: pathlib.Path):
    """When a builder lands state/digest-importers/device.importer.yml, this pins
    it to §2. Non-device importers are N/A (True)."""
    rec = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    ok, reason = device_family_basis_satisfied(rec)
    assert ok is True, f"{path.name}: {reason}"


def _app_record(**gdpr_extra):
    rec = {
        "meta": {"name": "demo", "version": "1.0", "summary": "demo"},
        "gdpr": {
            "purpose": "demo processing",
            "legal_basis": "legitimate_interests",
            "data_categories": ["email"],
            "data_subjects": ["partners"],
            "retention_days": 90,
            "processors": [],
            "transfers_outside_eu": False,
        },
        "compose": {"services": {"app": {"image": "ghcr.io/demo/app:1"}}},
    }
    rec["gdpr"].update(gdpr_extra)
    return rec


def test_validate_refuses_6f_without_lia():
    """Live parse path: validate() must refuse 6f with no LIA (runner uses this)."""
    with pytest.raises(AppParseError) as exc:
        validate(_app_record())
    assert any("balancing_test" in v for v in exc.value.violations)


def test_validate_accepts_complete_6f():
    validate(_app_record(
        balancing_test="Controller interest is a local demo index; limited to partners already on file; erasable.",
        data_source="not_from_subject",
    ))


def test_art30_forwards_balancing_test():
    """Art-30 mapper must not drop LIA / origin when the source declared them."""
    rec = nos_gdpr.gdpr_block_to_record(
        {
            "purpose": "ingest counterparties",
            "legal_basis": "legitimate_interests",
            "balancing_test": "a real LIA sentence that is non-empty",
            "data_source": "not_from_subject",
            "data_categories": ["legal name"],
            "data_subjects": ["counterparties"],
            "processors": [],
            "transfers_outside_eu": False,
            "retention_days": 3650,
        },
        record_id="imp_fixture",
        slug="fixture",
        tier="importer",
    )
    assert rec.get("balancing_test", "").strip()
    assert rec.get("data_source") == "not_from_subject"

