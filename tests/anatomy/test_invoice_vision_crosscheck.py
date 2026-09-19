"""isdoc-vision-crosscheck unit — offline half.

nos_digest.invoice_cross_check() is a PURE field-level comparator between an
ISDOC record and a vision-extracted record (both the isdoc-record dict
shape). nos_digest.reconcile_invoices() partitions a batch: a mismatching pair
never reaches deterministic invoice[] — it is DROPPED and routed to a
compose_invoice_review() row instead; a within-tolerance (or vision-absent)
invoice stays clean with zero review rows. DETECT + SURFACE only.

Retro-red: none of invoice_cross_check / reconcile_invoices /
compose_invoice_review exist on today's tree — every test here fails at
import/AttributeError before this unit's change.
"""
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "files" / "anatomy" / "module_utils"))
import nos_digest  # noqa: E402

ISDOC = {"id": "2026-INV-301", "currency": "CZK", "payable": 12100.0,
        "seller": {"ico": "00000112", "name": "Mesto Lipno (synthetic)"},
        "buyer": {"ico": "00000113", "name": "Petr Svoboda (synthetic)"}}


def test_within_tolerance_pair_has_no_mismatches():
    vision = dict(ISDOC, payable=12100.004)   # sub-cent float noise
    assert nos_digest.invoice_cross_check(ISDOC, vision, amount_tol=0.01) == []


def test_total_and_supplier_ico_mismatch_are_both_reported():
    vision = dict(ISDOC, payable=9900.0,
                  seller={"ico": "00000199", "name": "Mesto Lipno (synthetic)"})
    mismatches = nos_digest.invoice_cross_check(ISDOC, vision, amount_tol=0.01)
    fields = {m["field"] for m in mismatches}
    assert fields == {"payable", "seller.ico"}
    payable_m = next(m for m in mismatches if m["field"] == "payable")
    assert payable_m["isdoc_value"] == 12100.0 and payable_m["vision_value"] == 9900.0


def test_reconcile_drops_mismatching_invoice_from_clean_and_routes_to_review():
    isdoc_records = [ISDOC, dict(ISDOC, id="2026-INV-302")]
    vision_records = [dict(ISDOC, payable=9900.0)]   # only 301 has a vision extract, mismatching
    clean, review_items = nos_digest.reconcile_invoices(isdoc_records, vision_records, amount_tol=0.01)
    clean_ids = {r["id"] for r in clean}
    assert clean_ids == {"2026-INV-302"}   # 301 dropped; 302 has no vision extract, absorbs unchanged
    assert len(review_items) == 1 and review_items[0]["document_number"] == "2026-INV-301"
    assert any(m["field"] == "payable" for m in review_items[0]["mismatches"])


def test_compose_invoice_review_writes_one_row_per_mismatching_invoice():
    review_items = [{"document_number": "2026-INV-301",
                     "mismatches": [{"field": "payable", "isdoc_value": 12100.0, "vision_value": 9900.0}]}]
    bundle = nos_digest.compose_invoice_review(review_items, batch_id="crosscheck-run-1")
    rows = bundle["invoice-review"]
    assert len(rows) == 1
    row = rows[0]
    assert row["document_number"] == "2026-INV-301"
    assert row["mismatches"][0]["field"] == "payable"
    assert row["mismatches"][0]["isdoc_value"] == 12100.0
    assert row["mismatches"][0]["vision_value"] == 9900.0


def test_clean_match_or_no_vision_extract_emits_zero_review_rows():
    isdoc_records = [ISDOC]
    vision_records = [dict(ISDOC)]   # exact match
    _clean, review_items = nos_digest.reconcile_invoices(isdoc_records, vision_records, amount_tol=0.01)
    assert review_items == []
    _clean2, review_items2 = nos_digest.reconcile_invoices([ISDOC], [], amount_tol=0.01)
    assert review_items2 == []
