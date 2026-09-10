"""The importer-spine round-trip, offline half.

Proves express → GATE → (plan the store) → reset on the reference CSV importer,
without a live KEAP: run_importer stamps provenance and gates; the deterministic
party-ico-<8> slug dedups a repeated IČO; teardown_plan reverses the order. The
live store→reset half is the converge (digest-import --absorb + digest-teardown).
"""
import importlib.util
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]
CSV = REPO / "state" / "fixtures" / "kolben-import.csv"
TABLES = REPO / "state" / "keap-tables"


def _load():
    import sys
    sys.path.insert(0, str(REPO / "files" / "anatomy" / "module_utils"))
    import nos_digest
    spec = importlib.util.spec_from_file_location("digest_import", REPO / "tools" / "digest-import.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return nos_digest, mod


def _bundle():
    nd, mod = _load()
    imp = mod.CsvPartyImporter("test.csv")
    bundle, errors = nd.run_importer(imp, CSV.read_text(), TABLES)
    return nd, imp, bundle, errors


def test_gate_passes_and_bundle_is_untrusted_with_prov():
    nd, imp, bundle, errors = _bundle()
    assert errors == [], errors
    assert bundle["meta"]["trusted"] is False
    for rows in bundle["deterministic"].values():
        for r in rows:
            assert nd.PROV_REQUIRED <= set(r["_prov"]), r


def test_repeated_ico_dedups_to_one_deterministic_party():
    _nd, imp, bundle, _ = _bundle()
    parties = bundle["deterministic"]["party"]
    slugs = [p["slug"] for p in parties]
    assert slugs == ["party-ico-00000120", "party-ico-00000121", "party-ico-00000122"], slugs
    assert len(slugs) == len(set(slugs))          # the doubled IČO collapsed
    assert imp.skipped and "Keyless" in imp.skipped[0]   # keyless row refused, reported


def test_tax_rows_ref_the_party_and_teardown_is_leaf_first():
    nd, _imp, bundle, _ = _bundle()
    for tax in bundle["deterministic"]["party-tax-identity"]:
        assert tax["party"].startswith("party-ico-")
    plan = nd.teardown_plan(bundle)
    # leaf first: every party-tax-identity row precedes every party row.
    last_tax = max(i for i, (t, _) in enumerate(plan) if t == "party-tax-identity")
    first_party = min(i for i, (t, _) in enumerate(plan) if t == "party")
    assert last_tax < first_party, plan


def test_strip_provenance_removes_prov_before_upsert():
    nd, _imp, bundle, _ = _bundle()
    stripped = nd.strip_provenance(bundle["deterministic"])
    for rows in stripped.values():
        for r in rows:
            assert "_prov" not in r
