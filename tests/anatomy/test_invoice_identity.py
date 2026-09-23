"""Invoice identity is DERIVED, never chosen — one spelling across sources.

Found live 2026-09-23 in the Books app: document 2026-BETA-002 stood twice —
`inv-beta-002` (the hand-written consulting-firm fixture) beside
`invoice-synthetic-beta-vendor-2026-beta-002` (the importers). The ledger
balanced on both, which is exactly why a balance check cannot find this: a
duplicated document is internally consistent.

The fix is identity in the row id — `nos_digest.invoice_slug(book_owner,
seller, document_number)` — so a second source UPSERTS the same row. These
tests pin the three places that can drift apart: the helper, the absorb gate
(check_bundle), and every producer in the repo (importer + seed fixtures).
"""
import pathlib
import sys

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "files" / "anatomy" / "module_utils"))
import nos_digest  # noqa: E402

TABLES = REPO / "state" / "keap-tables"


def test_identity_is_all_three_fields():
    a = nos_digest.invoice_slug("client-beta", "vendor", "2026-1")
    assert a == "invoice-client-beta-vendor-2026-1"
    # each field participates — change one, get a different row
    assert nos_digest.invoice_slug("client-gama", "vendor", "2026-1") != a
    assert nos_digest.invoice_slug("client-beta", "other", "2026-1") != a
    assert nos_digest.invoice_slug("client-beta", "vendor", "2026-2") != a
    # ...and the same document from two sources is ONE row
    assert nos_digest.invoice_slug("client-beta", "vendor", " 2026/1 ") == \
        nos_digest.invoice_slug("client-beta", "vendor", "2026-1")


def test_unknown_book_is_visible_not_guessed():
    assert nos_digest.invoice_slug(None, "vendor", "x").startswith("invoice-unbooked-")


def test_an_unidentifiable_invoice_is_refused():
    with pytest.raises(ValueError):
        nos_digest.invoice_slug("owner", "", "2026-1")
    with pytest.raises(ValueError):
        nos_digest.invoice_slug("owner", "vendor", None)


def test_a_long_identity_folds_instead_of_colliding():
    long = "x" * 200
    a = nos_digest.invoice_slug("owner", long, "2026-1")
    b = nos_digest.invoice_slug("owner", long, "2026-2")
    assert len(a) <= 128 and a != b          # a blind truncate would equate them


def _bundle(rows):
    return {"meta": {"trusted": True}, "deterministic": {
        "party": [{"slug": s, "legal_name": s, "party_kind": "org", "country": "CZ"}
                  for s in ("book", "vendor")],
        "invoice": rows,
        "invoice-line": [{"slug": f"line-{r['slug']}", "invoice": r["slug"], "line_no": 1,
                          "description": "x", "quantity": 1,
                          "net_amount": r["net_amount"], "vat_amount": r["vat_amount"]}
                         for r in rows]}}


def _row(slug):
    return {"slug": slug, "document_number": "2026-1", "seller": "vendor", "buyer": "book",
            "book_owner": "book", "currency": "CZK", "net_amount": 100, "vat_amount": 21}


def test_absorb_gate_refuses_a_chosen_invoice_id():
    derived = nos_digest.invoice_slug("book", "vendor", "2026-1")
    assert nos_digest.check_bundle(_bundle([_row(derived)]), TABLES) == []
    errs = nos_digest.check_bundle(_bundle([_row("inv-beta-002")]), TABLES)
    assert any("derived identity" in e for e in errs), errs


def test_every_seed_fixture_carries_derived_invoice_ids():
    checked = 0
    for p in sorted((REPO / "state" / "fixtures").glob("*.seed.yml")):
        seed = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        for r in seed.get("invoice") or []:
            want = nos_digest.invoice_slug(r.get("book_owner"), r["seller"], r["document_number"])
            assert r["slug"] == want, f"{p.name}: {r['slug']} should be {want}"
            checked += 1
    assert checked, "no fixture invoice rows found — the gate would pass vacuously"


def test_the_importer_derives_the_same_identity():
    """The ISDOC composer is the shared producer (VisionImporter inherits
    compose verbatim), so pinning it covers both importers."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "digest_import_isdoc", REPO / "tools" / "digest-import-isdoc.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    imp = mod.IsdocImporter("x.isdoc", {}, fixture_mode=True)
    imp.book_owner_slug = "book"
    bundle = imp.compose([{
        "id": "2026-1", "file": "x.isdoc", "currency": "CZK", "issue": None, "due": None,
        "payable": None, "net": 100, "vat": 21, "seller_slug": "vendor", "buyer_slug": "book",
        "seller": {"name": "V"}, "buyer": {"name": "B"}, "lines": []}])
    inv = bundle["invoice"][0]
    assert inv["slug"] == nos_digest.invoice_slug("book", "vendor", "2026-1")
    assert inv["book_owner"] == "book"


def test_the_fixture_ledger_is_what_derive_entry_would_derive():
    """The same duplication one level down: the consulting-firm fixture seeded a
    hand-written book (je-alfa-001) while an ISDOC import of the SAME documents
    derived its own (je-<invoice>), so the live ledger carried 16 entries for 10
    invoices. One producer, one spelling — the seeded rows must BE the derived
    rows, amounts included."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "derive_postings", REPO / "tools" / "derive-postings.py")
    DP = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(DP)
    import nos_accounting

    seed = yaml.safe_load((REPO / "state" / "fixtures" / "consulting-firm.seed.yml")
                          .read_text(encoding="utf-8"))
    accounts = DP.build_accounts_by_code(seed["account"])
    seeded_entries = {r["slug"] for r in seed["journal-entry"]}
    seeded_postings = {(r["slug"], r["entry"], r["account"], r["direction"], float(r["amount"]))
                       for r in seed["posting"]}
    for inv in seed["invoice"]:
        derived = nos_accounting.derive_entry(inv, inv["book_owner"], accounts)
        assert derived["entry"]["slug"] in seeded_entries, inv["slug"]
        for p in derived["postings"]:
            key = (p["slug"], p["entry"], p["account"], p["direction"], float(p["amount"]))
            assert key in seeded_postings, f"{inv['slug']}: fixture is missing {key}"
