"""Anatomy CI gate — GDPR consent-activity map well-formedness.

Mirrors test_gdpr_erasure_map.py in spirit, but the consent map keys on the
SEEDED Art-30 register slugs (db/gdpr-seed.sql: tenant-vault / collab-docs /
project-knowledge), NOT the plugin-derived svc_<slug> convention — so it does
NOT assert a svc_ prefix. It pins: shape, real-register membership, the
capture_wired honesty flag, and that EVERY seeded legal_basis=consent activity
appears in the map (so a future consent row can't silently escape the registry).
"""
from __future__ import annotations

import pathlib
import re

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
MAP_PATH = REPO / "state" / "gdpr-consent-map.yml"
SEED = REPO / "files" / "anatomy" / "wing" / "db" / "gdpr-seed.sql"

VALID_METHODS = {"record-consent", "external", "manual"}


def _entries() -> list[dict]:
    data = yaml.safe_load(MAP_PATH.read_text()) or {}
    return data.get("activities") or []


def _seeded_consent_ids() -> set[str]:
    """Parse db/gdpr-seed.sql VALUES tuples: the id is the first quoted field of
    each tuple; collect those whose legal_basis (the 4th field) is 'consent'."""
    src = SEED.read_text()
    ids: set[str] = set()
    # each VALUES tuple opens with "(\n    'id',\n    'name',\n    'purpose',\n    'legal_basis',"
    for m in re.finditer(
        r"\(\s*'([^']+)',\s*'[^']*',\s*'(?:[^']|'')*',\s*'([^']+)',",
        src,
    ):
        rec_id, legal_basis = m.group(1), m.group(2)
        if legal_basis == "consent":
            ids.add(rec_id)
    return ids


def test_map_loads_with_activities():
    data = yaml.safe_load(MAP_PATH.read_text()) or {}
    assert "activities" in data
    assert isinstance(data["activities"], list)


def test_entries_well_formed():
    for e in _entries():
        assert e.get("id"), "each entry needs an id (Art-30 register slug)"
        assert e.get("activity"), "each entry needs the gdpr_consent.activity slug"
        assert e["method"] in VALID_METHODS, e["method"]
        assert e.get("flag"), "each entry needs a gate flag (or 'always')"
        assert e.get("note", "").strip(), "each entry needs an operator-facing note"
        assert isinstance(e.get("capture_wired"), bool), (
            "capture_wired must be an explicit bool (the consent-collected honesty flag)"
        )


def test_ids_unique():
    ids = [e["id"] for e in _entries()]
    assert len(ids) == len(set(ids)), "duplicate consent-map id"


def test_every_seeded_consent_activity_is_mapped():
    """The empty-map premise was FALSE: db/gdpr-seed.sql seeds real
    legal_basis=consent rows. Every one MUST appear in the consent map so the
    'consent declared, not collected' gap is visible, not hidden."""
    seeded = _seeded_consent_ids()
    mapped = {e["id"] for e in _entries()}
    missing = seeded - mapped
    assert not missing, (
        "seeded legal_basis=consent activities absent from the consent map: "
        f"{sorted(missing)} — add each so the demonstrability gap is surfaced"
    )


def test_map_ids_are_real_seeded_register_slugs():
    seeded = _seeded_consent_ids()
    for e in _entries():
        assert e["id"] in seeded, (
            f"consent-map id {e['id']!r} is not a seeded legal_basis=consent "
            "register slug — do not invent activities"
        )


def test_consent_events_whitelisted_both_sides():
    bone = (REPO / "files/anatomy/bone/events.py").read_text()
    wing = (REPO / "files/anatomy/wing/app/Model/EventRepository.php").read_text()
    for ev in ("consent_granted", "consent_withdrawn"):
        assert f'"{ev}"' in bone, f"{ev} missing from Bone VALID_TYPES"
        assert f"'{ev}'" in wing, f"{ev} missing from Wing EventRepository::VALID_TYPES"


def test_capture_wired_implies_automated_write_method():
    """C7: capture_wired honesty. Today every row is capture_wired:false (the
    demonstrability gap is declared, not hidden). If a row ever flips to true it
    MUST name an automated write path (record-consent | external) — `manual`
    with capture_wired:true would re-assert the 'consent collected' claim while
    nothing writes a gdpr_consent row (the Art-7(1) falsehood this map surfaces)."""
    for e in _entries():
        if e.get("capture_wired") is True:
            assert e["method"] in {"record-consent", "external"}, (
                f"{e['id']}: capture_wired:true requires an automated write method "
                f"(record-consent|external), not {e['method']!r}"
            )
