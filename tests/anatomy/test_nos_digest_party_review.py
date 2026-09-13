"""party-review-rung: review/ambiguous resolve_party outcomes become proposed
party-spine rows born __visibility:system (not /ingest/v1/capture).

The KEAP peel+history door already exists; this gate pins the nOS composer so a
review cannot mint a normal-visibility party. Device identifiers still mint none
(owner scheme B).
"""
import importlib.util
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]
MOD = REPO / "files" / "anatomy" / "module_utils" / "nos_digest.py"
TABLES = REPO / "state" / "keap-tables"


def _nd():
    spec = importlib.util.spec_from_file_location("nos_digest", MOD)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


ND = _nd()
VALID_ICO = "12345679"
EMPTY = {"by_key": {}, "by_name": {}}
BATCH = "autoskola-trio"


def _item(ref, **resolve_kw):
    return {"ref": ref, "result": ND.resolve_party(ref, resolve_kw.pop("index", EMPTY), **resolve_kw)}


def _spine_rows(det: dict):
    rows = []
    for table in ("party", "party-tax-identity", "party-address", "party-contact"):
        rows.extend(det.get(table) or [])
    return rows


def test_review_and_ambiguous_mint_system_visibility_not_normal():
    """The load-bearing pin: a review/ambiguous outcome must not be born as a
    normal-visibility party row (table default tier-managers)."""
    person = _item({"kind": "person", "name": "Petr Svoboda", "country": "CZ"})
    amb = _item({"kind": "org", "name": "ACME"},
                index={"by_key": {}, "by_name": {"acme": ["p1", "p2"]}})
    weak_org = _item({"kind": "org", "ico": VALID_ICO, "legal_name": "Kolben IT s.r.o."},
                     source_authoritative=False)
    assert person["result"]["status"] == "review"
    assert amb["result"]["status"] == "review" and len(amb["result"]["candidates"]) > 1
    assert weak_org["result"]["status"] == "review"

    det = ND.compose_party_review([person, amb, weak_org], batch_id=BATCH)
    rows = _spine_rows(det)
    assert rows, "review/ambiguous must become proposed spine rows"
    assert "captures" not in det and "proposals" not in det
    for r in rows:
        assert r.get("__visibility") == "system", r
    parties = det["party"]
    assert all("review-batch:" + BATCH in (p.get("notes") or "") for p in parties)
    assert len(parties) == 3  # one batch, three proposed parties (autoskola-trio)
    # a missing stamp would absorb as the table's tier-managers default
    assert not any("__visibility" not in p for p in parties)


def test_device_identifier_still_mints_no_party():
    """Owner scheme B: a device id is not slug material, even through review."""
    refs = [
        {"kind": "person", "name": "Pazny", "udid": "00008020-001A246E0A88002E"},
        {"kind": "person", "name": "Pazny", "imei": "490154203237518"},
        {"kind": "person", "name": "Pazny", "serial": "F2LXYZ123456"},
        {"kind": "person", "name": "Pazny", "device_id": "iphone-operator"},
        {"kind": "org", "legal_name": "party-device-deadbeef", "ico": VALID_ICO},
    ]
    items = [_item(r) for r in refs]
    det = ND.compose_party_review(items, batch_id="device-b")
    assert _spine_rows(det) == []
    assert not det.get("party")


def test_synthetic_and_resolved_do_not_enter_the_rung():
    synth = _item({"kind": "org", "ico": "00000112", "legal_name": "Fixture Co"})
    hit = _item({"kind": "org", "ico": VALID_ICO},
                index={"by_key": {("ICO", VALID_ICO): "party-ico-" + VALID_ICO}, "by_name": {}})
    created = _item({"kind": "org", "ico": VALID_ICO, "legal_name": "Auth s.r.o."},
                    source_authoritative=True)
    assert synth["result"]["status"] == "review"
    assert hit["result"]["status"] == "resolved"
    assert created["result"]["status"] == "create"
    det = ND.compose_party_review([synth, hit, created], batch_id=BATCH)
    assert _spine_rows(det) == []


def test_review_bundle_is_gated_deterministic_not_capture():
    person = _item({"kind": "person", "name": "Jana Novakova", "country": "CZ"})
    det = ND.compose_party_review([person], batch_id=BATCH)
    bundle = {"meta": {"trusted": False}, "deterministic": det}
    ND.stamp_provenance(det, source_id="review-test", importer_version="0")
    assert ND.check_bundle(bundle, TABLES) == []
    assert not bundle.get("captures")
    party = det["party"][0]
    assert party["party_kind"] == "person"
    assert party["slug"].startswith("party-review-")
    assert "party-tax-identity" not in det or not det["party-tax-identity"]
