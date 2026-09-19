"""The load-bearing digest judge: nos_digest.check_bundle().

Validated against the REAL fixture seeds (which are trusted deterministic
bundles — their {slug:[rows]} IS the deterministic section) plus deliberate
corruptions, so the gate that stands between an importer and the live doors is
itself gated.
"""
import copy
import importlib.util
import pathlib

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
MOD = REPO / "files" / "anatomy" / "module_utils" / "nos_digest.py"
TABLES = REPO / "state" / "keap-tables"


def _nd():
    spec = importlib.util.spec_from_file_location("nos_digest", MOD)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


ND = _nd()


def _seed(name: str) -> dict:
    return yaml.safe_load((REPO / "state" / "fixtures" / f"{name}.seed.yml").read_text())


def test_real_fixtures_pass_as_trusted_bundles():
    for name in ("label-printer", "kolben-it"):
        errs = ND.check_fixture_seed(_seed(name), TABLES)
        assert errs == [], f"{name} should be a valid trusted bundle: {errs}"


def test_untrusted_bundle_requires_per_row_provenance():
    # the same good fixture, declared UNTRUSTED → every row lacks _prov
    errs = ND.check_bundle({"meta": {}, "deterministic": _seed("kolben-it")}, TABLES)
    assert errs, "an untrusted bundle without _prov must fail"
    assert all("_prov" in e for e in errs), errs


def test_forward_reference_is_caught():
    # reverse the key order so domain tables precede the party spine they rowRef
    seed = _seed("kolben-it")
    reordered = {k: seed[k] for k in reversed(list(seed.keys()))}
    errs = ND.check_bundle({"meta": {"trusted": True}, "deterministic": reordered}, TABLES)
    assert any("FORWARD" in e for e in errs), errs


def test_unresolved_rowref_is_caught():
    seed = copy.deepcopy(_seed("kolben-it"))
    seed["kolben-ticket"][0] = {**seed["kolben-ticket"][0], "project": "no-such-project"}
    errs = ND.check_bundle({"meta": {"trusted": True}, "deterministic": seed}, TABLES)
    assert any("no-such-project" in e for e in errs), errs


def test_untrusted_bundle_with_provenance_passes():
    seed = copy.deepcopy(_seed("label-printer"))
    stamp = {"source_id": "src:test", "importer_version": "0.0.0", "content_hash": "abc"}
    for rows in seed.values():
        for r in rows:
            r["_prov"] = dict(stamp)
    errs = ND.check_bundle(
        {"meta": {"source_id": "src:test", "trusted": False}, "deterministic": seed}, TABLES)
    assert errs == [], f"a stamped untrusted bundle should pass: {errs}"


def test_unknown_top_level_key_is_flagged():
    errs = ND.check_bundle({"meta": {"trusted": True}, "deterministic": {}, "bogus": 1}, TABLES)
    assert any("bogus" in e for e in errs), errs


def test_external_rowref_is_allowed_but_in_bundle_forward_still_caught():
    """A rowRef to a table NOT in the bundle is an EXTERNAL (pre-existing KEAP)
    reference — allowed (KEAP validates at absorb), so a derivation bundle can
    reference an already-seeded account/invoice without re-emitting stubs. But a
    FORWARD ref within the bundle must still fail — the external path must not
    mask it."""
    ext = {"meta": {"trusted": True}, "deterministic": {
        "posting": [{"slug": "p1", "entry": "je-x", "account": "acc-311", "direction": "debit", "amount": 5}]}}
    assert ND.check_bundle(ext, TABLES) == [], ND.check_bundle(ext, TABLES)   # both refs external → ok
    fwd = {"meta": {"trusted": True}, "deterministic": {
        "posting": [{"slug": "p1", "entry": "je-1", "account": "acc-311", "direction": "debit", "amount": 5}],
        "journal-entry": [{"slug": "je-1"}]}}                                  # journal-entry AFTER posting
    assert any("FORWARD" in e for e in ND.check_bundle(fwd, TABLES)), ND.check_bundle(fwd, TABLES)


def test_captures_or_proposals_are_refused_until_inspectable():
    # The broken state the fail-closed guard closes: a bundle carrying an
    # unread section must NOT pass green (estate #1 anti-pattern). A bundle with
    # ONLY captures used to return [] clean — the worst case, no deterministic
    # section to trip any other check.
    for section in ("captures", "proposals"):
        errs = ND.check_bundle({"meta": {"trusted": True}, section: [{"any": "thing"}]}, TABLES)
        assert any(section in e and "refused" in e for e in errs), (section, errs)
    # an EMPTY section is fine — nothing to inspect, nothing to greenlight
    assert ND.check_bundle({"meta": {"trusted": True}, "deterministic": {}, "captures": []},
                           TABLES) == []


def test_teardown_plan_is_the_seed_reversed():
    seed = _seed("kolben-it")
    plan = ND.teardown_plan(seed)
    # leaf-first: the last-seeded table is deleted first, the party spine last
    assert plan[0][0] == list(seed.keys())[-1]      # kolben-time-entry
    assert plan[-1][0] == list(seed.keys())[0]      # party
    assert len(plan) == sum(len(rows) for rows in seed.values())   # every row, once
    # a full bundle envelope works too (deterministic section unwrapped)
    assert ND.teardown_plan({"meta": {}, "deterministic": seed}) == plan


def _friend_bundle() -> dict:
    return yaml.safe_load((pathlib.Path(__file__).with_name("friend-iphone-backup.bundle.yml")).read_text())


def _stamp(row: dict) -> dict:
    row = dict(row)
    row["_prov"] = {"source_id": "src:test", "importer_version": "0.0.0", "content_hash": "abc"}
    return row


def _device_pair(extraction: dict) -> dict:
    return {
        "meta": {"source_id": "src:test", "trusted": False},
        "deterministic": {
            "device": [_stamp({
                "slug": "device-friend-iphone",
                "model": "iPhone 14",
                "os_family": "ios",
                "identifier_hash": "sha256:" + ("a" * 64),
            })],
            "device-extraction": [_stamp(extraction)],
        },
    }


def test_friend_iphone_backup_bundle_is_refused():
    """Pre-fix: check_bundle returned [] for this stamped untrusted third-party
    extraction and absorb would POST. The gate must refuse (not via resolve_party)."""
    errs = ND.check_bundle(_friend_bundle(), TABLES)
    assert errs, "friend-iphone-backup style bundle must not pass check_bundle"
    blob = " ".join(errs).lower()
    assert "i\u010do" not in blob and "ico" not in blob and "synthetic range" not in blob, errs
    assert any("operator_owns_device" in e or "subject_kind" in e or "third" in e.lower() for e in errs), errs


def test_device_extraction_attestation_variants_are_refused():
    base = {
        "slug": "ext-friend-unattested",
        "device": "device-friend-iphone",
        "owner": "Alex Friend",
        "notes": "",
        "report_path": "",
    }
    variants = [
        {**base, "subject_kind": "third_party", "operator_owns_device": False},
        {**base, "subject_kind": "operator_device", "operator_owns_device": False},
        {**base, "subject_kind": "operator_device"},  # owns missing
    ]
    for extra in variants:
        errs = ND.check_bundle(_device_pair(extra), TABLES)
        assert errs, extra


def test_html_or_zip_in_device_text_columns_is_refused():
    html = "<!DOCTYPE html><html><head><title>iLEAPP Report</title></head><body><h1>SMS</h1></body></html>"
    zip_magic = "PK\x03\x04" + "FAKE_ITUNES_BACKUP" * 4
    for field, payload in (("notes", html), ("report_path", html), ("notes", zip_magic)):
        extra = {
            "slug": "ext-dump",
            "device": "device-friend-iphone",
            "owner": "Operator",
            "subject_kind": "operator_device",
            "operator_owns_device": True,
            "notes": "",
            "report_path": "/tmp/ileapp/index.html",
            field: payload,
        }
        errs = ND.check_bundle(_device_pair(extra), TABLES)
        assert errs, (field, payload[:40])


def test_party_keys_in_a_device_bundle_are_refused():
    b = _device_pair({
        "slug": "ext-ok",
        "device": "device-friend-iphone",
        "owner": "Operator",
        "subject_kind": "operator_device",
        "operator_owns_device": True,
        "notes": "",
        "report_path": "",
    })
    b["deterministic"]["party"] = [_stamp({"slug": "party-device-deadbeef", "legal_name": "Ada Lovelace"})]
    errs = ND.check_bundle(b, TABLES)
    assert errs
    assert any("party" in e for e in errs), errs


def test_operator_owned_extraction_without_dump_still_passes():
    errs = ND.check_bundle(_device_pair({
        "slug": "ext-ok",
        "device": "device-friend-iphone",
        "owner": "Operator",
        "subject_kind": "operator_device",
        "operator_owns_device": True,
        "notes": "operator phone, consented",
        "report_path": "/tmp/ileapp/index.html",
    }), TABLES)
    assert errs == [], errs


# ── Wave-2 gate: free-text special-category smuggling (importer not yet built) ──

def _operator_extraction(**extra) -> dict:
    base = {
        "slug": "ext-smuggle",
        "device": "device-friend-iphone",
        "owner": "Operator",
        "subject_kind": "operator_device",
        "operator_owns_device": True,
        "notes": "",
        "report_path": "",
    }
    base.update(extra)
    return _device_pair(base)


def test_plaintext_tsv_special_category_in_notes_is_refused():
    """The exact smuggling the HTML/zip magic missed: a TSV of messages / a
    heart-rate reading pasted into device-extraction.notes as PLAIN TEXT. No
    magic bytes, so pre-fix check_bundle returned [] and absorb would POST."""
    for payload in (
        "sms.tsv\t+420123456789\tmeet at the clinic",
        "heartRate\t72",
    ):
        errs = ND.check_bundle(_operator_extraction(notes=payload), TABLES)
        assert errs, payload
        blob = " ".join(errs).lower()
        assert "tsv" in blob or "art. 9" in blob or "special-category" in blob, errs


def test_special_category_note_needs_art9_consent_ref():
    """A tab-free, short note that still names a special-category class (health)
    must carry art9_consent_ref — empty is refused, non-empty passes."""
    errs = ND.check_bundle(_operator_extraction(notes="resting heart rate reviewed"), TABLES)
    assert any("art9" in e or "Art. 9" in e for e in errs), errs

    ok = ND.check_bundle(_operator_extraction(
        notes="sleep tracker export reviewed",
        art9_consent_ref="consent:art9:2026-09-19",
    ), TABLES)
    assert ok == [], ok


def test_oversized_free_text_is_refused():
    errs = ND.check_bundle(_operator_extraction(notes="x" * 2000), TABLES)
    assert any("oversized" in e for e in errs), errs
