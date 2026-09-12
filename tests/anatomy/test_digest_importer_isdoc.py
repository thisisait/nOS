"""The THIRD importer — ISDOC e-invoices → the invoice facet — offline half.

Proves the harness takes a third, XML source and the seller/buyer DUAL party
resolve: each invoice attributes to two parties, both resolved against the spine,
neither minted. An invoice whose buyer is unknown is skipped whole. Party index
injected; the live index (from KEAP) is the CLI's job.
"""
import importlib.util
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]
FIXTURE = REPO / "state" / "fixtures" / "isdoc-fixture"
TABLES = REPO / "state" / "keap-tables"
INDEX = {"by_key": {("ICO", "00000112"): "synthetic-mesto-lipno",
                     ("ICO", "00000113"): "synthetic-svoboda-petr"}, "by_name": {}}


def _load():
    import sys
    sys.path.insert(0, str(REPO / "files" / "anatomy" / "module_utils"))
    import nos_digest
    spec = importlib.util.spec_from_file_location("digest_import_isdoc",
                                                  REPO / "tools" / "digest-import-isdoc.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return nos_digest, mod


def _bundle():
    nd, mod = _load()
    imp = mod.IsdocImporter("isdoc-fixture", INDEX, fixture_mode=True)
    bundle, errors = nd.run_importer(imp, str(FIXTURE), TABLES)
    return nd, imp, bundle, errors


def test_gate_passes_and_bundle_is_party_then_invoice():
    _nd, _imp, bundle, errors = _bundle()
    assert errors == [], errors
    assert list(bundle["deterministic"].keys()) == ["party", "invoice"]


def test_dual_resolve_and_unknown_buyer_is_skipped():
    _nd, imp, bundle, _ = _bundle()
    invoices = bundle["deterministic"]["invoice"]
    assert {i["document_number"] for i in invoices} == {"2026-INV-001", "2026-INV-002"}  # 003 skipped
    for i in invoices:
        assert i["seller"] in ("synthetic-mesto-lipno", "synthetic-svoboda-petr")
        assert i["buyer"] in ("synthetic-mesto-lipno", "synthetic-svoboda-petr")
        assert i["seller"] != i["buyer"]
    parties = {p["slug"] for p in bundle["deterministic"]["party"]}
    assert parties == {"synthetic-mesto-lipno", "synthetic-svoboda-petr"}   # deduped, not 4
    assert any("2026-inv-003" in s and "buyer unresolved" in s for s in imp.skipped), imp.skipped


def test_amount_and_dates_parsed_and_prov_stamped():
    nd, _imp, bundle, _ = _bundle()
    inv1 = next(i for i in bundle["deterministic"]["invoice"] if i["document_number"] == "2026-INV-001")
    assert inv1["payable_amount"] == 48400.0 and inv1["currency"] == "CZK"
    assert isinstance(inv1["issue_date"], int) and isinstance(inv1["due_date"], int)  # ISO → epoch
    for rows in bundle["deterministic"].values():
        for r in rows:
            assert nd.PROV_REQUIRED <= set(r["_prov"]), r


def test_deterministic_slug_is_seller_plus_document():
    _nd, _imp, bundle, _ = _bundle()
    inv1 = next(i for i in bundle["deterministic"]["invoice"] if i["document_number"] == "2026-INV-001")
    assert inv1["slug"] == "invoice-synthetic-mesto-lipno-2026-inv-001"
