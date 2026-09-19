"""invoice-vision-intake unit — offline half (mirrors test_digest_importer_isdoc.py).

VisionImporter(IsdocImporter) overrides ONLY parse(): globs *.extract.json
sidecars into the same record-dict shape the ISDOC importer produces, so
normalize/compose/_resolve (dual-party resolve, book_owner) are inherited.

parse() IS the operator-verify rung: a verified, high-confidence sidecar lands;
an unverified or any-field-below-floor sidecar is absent from the bundle AND
present in skipped[] with a reason — it can never reach absorb.
"""
import importlib.util
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]
FIXTURE = REPO / "state" / "fixtures" / "vision-fixture"
TABLES = REPO / "state" / "keap-tables"
INDEX = {"by_key": {("ICO", "00000112"): "synthetic-mesto-lipno",
                     ("ICO", "00000113"): "synthetic-svoboda-petr"}, "by_name": {}}


def _load():
    import sys
    sys.path.insert(0, str(REPO / "files" / "anatomy" / "module_utils"))
    import nos_digest
    spec = importlib.util.spec_from_file_location("digest_import_vision",
                                                  REPO / "tools" / "digest-import-vision.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return nos_digest, mod


def _bundle(**kw):
    nd, mod = _load()
    imp = mod.VisionImporter("vision-fixture", INDEX, fixture_mode=True, **kw)
    bundle, errors = nd.run_importer(imp, str(FIXTURE), TABLES)
    return nd, imp, bundle, errors


def test_verified_invoice_lands_seller_and_buyer_resolved_never_minted():
    _nd, _imp, bundle, errors = _bundle()
    assert errors == [], errors
    invoices = bundle["deterministic"]["invoice"]
    assert {i["document_number"] for i in invoices} == {"2026-INV-201"}
    inv = invoices[0]
    assert inv["seller"] == "synthetic-mesto-lipno"
    assert inv["buyer"] == "synthetic-svoboda-petr"
    assert inv["seller"] != inv["buyer"]
    parties = {p["slug"] for p in bundle["deterministic"]["party"]}
    assert {"synthetic-mesto-lipno", "synthetic-svoboda-petr"} <= parties
    assert inv["net_amount"] == 10000.0 and inv["vat_amount"] == 2100.0
    assert inv["payable_amount"] == 12100.0


def test_unverified_and_low_confidence_are_skipped_never_absorbed():
    _nd, imp, bundle, _errors = _bundle()
    doc_numbers = {i["document_number"] for i in bundle["deterministic"]["invoice"]}
    assert "2026-INV-202" not in doc_numbers
    assert "2026-INV-203" not in doc_numbers
    joined = " | ".join(imp.skipped)
    assert "2026-inv-202" in joined.lower() and "low-confidence" in joined
    assert "2026-inv-203" in joined.lower() and "not operator-verified" in joined


def test_book_owner_is_stamped_from_context_and_resolved_never_generated():
    _nd, _imp, bundle, errors = _bundle(book_owner_ico="00000113")
    assert errors == [], errors
    inv = bundle["deterministic"]["invoice"][0]
    assert inv["book_owner"] == "synthetic-svoboda-petr"


def test_unknown_book_owner_ico_skips_the_stamp_not_the_run():
    _nd, imp, bundle, errors = _bundle(book_owner_ico="00000199")
    assert errors == [], errors
    inv = bundle["deterministic"]["invoice"][0]
    assert "book_owner" not in inv
    assert any("book-owner" in s for s in imp.skipped), imp.skipped
