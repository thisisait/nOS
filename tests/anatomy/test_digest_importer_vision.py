"""invoice-vision-intake unit — offline half (mirrors test_digest_importer_isdoc.py).

VisionImporter(IsdocImporter) overrides ONLY parse(): globs *.extract.json
sidecars into the same record-dict shape the ISDOC importer produces, so
normalize/compose/_resolve (dual-party resolve, book_owner) are inherited.

parse() IS the operator-verify rung: a verified, high-confidence sidecar lands;
an unverified or any-field-below-floor sidecar is absent from the bundle AND
present in skipped[] with a reason — it can never reach absorb.

UC5 batch: parse() honors pending-invoice-verify.resolution keyed on
sidecar_id (filename), not slug. Approval does not POST invoice/posting.
"""
import importlib.util
import json
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


# --- UC5: parse() + fake pending rows (no live KEAP, no compose) ---

SIDECAR_NAME = "held.extract.json"
HELD_SIDECAR = {
    "record": {"id": "2026-INV-UC5", "seller": {}, "buyer": {}},
    "fields": {"payable": {"value": 1, "confidence": 0.1, "source": "vlm"}},
    "verified": False,
}


def _parse(tmp_path, rows, monkeypatch=None):
    (tmp_path / SIDECAR_NAME).write_text(json.dumps(HELD_SIDECAR), encoding="utf-8")
    _nd, mod = _load()
    posted = []
    if monkeypatch is not None:
        import digest_absorb as da
        monkeypatch.setattr(da, "_post_row", lambda *a, **k: posted.append(a))
    imp = mod.VisionImporter("uc5", INDEX, fixture_mode=True, pending_verify=rows)
    recs = imp.parse(tmp_path)
    return imp, recs, posted


def test_parse_includes_approved_sidecar_id_skips_pending_and_rejected(tmp_path, monkeypatch):
    """RETRO-RED: lookup by slug (or ignoring resolution) includes the wrong set."""
    approved = [{"slug": "piv-not-the-filename", "sidecar_id": SIDECAR_NAME,
                 "resolution": "approved"}]
    imp, recs, posted = _parse(tmp_path, approved, monkeypatch)
    assert [r["id"] for r in recs] == ["2026-INV-UC5"]
    assert posted == [], "parse() must not POST invoice/posting; absorb is later"

    for resolution in ("pending", "rejected", None):
        rows = [{"slug": "piv-not-the-filename", "sidecar_id": SIDECAR_NAME,
                 "resolution": resolution}]
        imp, recs, _posted = _parse(tmp_path, rows)
        assert recs == [], f"{resolution!r} must stay held, got {recs}"
        assert SIDECAR_NAME in " ".join(imp.skipped)


def test_parse_does_not_join_on_slug(tmp_path):
    decoy = [{"slug": SIDECAR_NAME, "sidecar_id": "other.extract.json",
              "resolution": "approved"}]
    imp, recs, _posted = _parse(tmp_path, decoy)
    assert recs == [], "joining on slug would treat this decoy as approved"
    assert SIDECAR_NAME in " ".join(imp.skipped)


def test_parse_keap_path_indexes_rows_by_sidecar_id(tmp_path, monkeypatch):
    """pending_verify=None is main(); join must still be sidecar_id."""
    (tmp_path / SIDECAR_NAME).write_text(json.dumps(HELD_SIDECAR), encoding="utf-8")
    _nd, mod = _load()
    import digest_absorb as da
    seen = []
    monkeypatch.setattr(da, "read_rows", lambda table: seen.append(table) or [
        {"slug": "piv-not-the-filename", "sidecar_id": SIDECAR_NAME, "resolution": "approved"}])
    imp = mod.VisionImporter("uc5", INDEX, fixture_mode=True, pending_verify=None)
    recs = imp.parse(tmp_path)
    assert [r["id"] for r in recs] == ["2026-INV-UC5"]
    assert seen == ["pending-invoice-verify"]


def test_invoice_verify_approve_posts_only_pending_table(monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "invoice_verify_uc5", REPO / "tools" / "invoice-verify.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    row = {"slug": "piv-held-extract-json", "sidecar_id": SIDECAR_NAME,
           "fields": {}, "resolution": "pending"}
    monkeypatch.setattr(mod, "_row", lambda slug: dict(row))
    posted = []
    monkeypatch.setattr(mod.digest_absorb, "_post_row",
                        lambda table, values, hdr: posted.append(table))
    monkeypatch.setattr(mod, "emit_audit", lambda *a: True)
    assert mod.main(["approve", "piv-held-extract-json"]) == 0
    assert posted == ["pending-invoice-verify"]
