"""The reader that can see a duplication a balance check cannot.

`scan()` is pure over rows, so this drives it with the EXACT live shape that
was found on 2026-09-23 — and with a clean table, because a detector that
cannot report green is as useless as one that cannot report red.
"""
import importlib.util
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "files" / "anatomy" / "module_utils"))
import nos_digest  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "invoice_identity_scan", REPO / "tools" / "invoice-identity-scan.py")
SCAN = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(SCAN)


def _row(slug, owner, seller, doc):
    return {"slug": slug, "book_owner": owner, "seller": seller, "document_number": doc}


def _good(owner, seller, doc):
    return _row(nos_digest.invoice_slug(owner, seller, doc), owner, seller, doc)


def test_a_clean_table_reports_clean():
    r = SCAN.scan([_good("beta", "vendor", "2026-1"), _good("alfa", "vendor", "2026-2")])
    assert r["duplicates"] == [] and r["twins"] == [] and r["drift"] == []


def test_the_live_2026_beta_002_case():
    """Both rows named the same document; both booked; both balanced."""
    rows = [_row("inv-beta-002", "synthetic-client-beta", "synthetic-beta-vendor", "2026-BETA-002"),
            _row("invoice-synthetic-beta-vendor-2026-beta-002", "synthetic-client-beta",
                 "synthetic-beta-vendor", "2026-BETA-002")]
    r = SCAN.scan(rows)
    assert len(r["duplicates"]) == 1
    assert sorted(r["duplicates"][0]["slugs"]) == sorted(x["slug"] for x in rows)
    assert len(r["drift"]) == 2          # neither id is the derived one


def test_a_twin_across_books_is_reported_separately():
    rows = [_good("alfa", "vendor", "2026-9"), _good("beta", "vendor", "2026-9")]
    r = SCAN.scan(rows)
    assert r["duplicates"] == []         # different books: not the same row
    assert len(r["twins"]) == 1          # ...but worth a human's eye


def test_an_unidentifiable_row_is_drift_not_a_crash():
    r = SCAN.scan([_row("whatever", "beta", "", "2026-1")])
    assert len(r["drift"]) == 1 and r["drift"][0]["want"] is None
