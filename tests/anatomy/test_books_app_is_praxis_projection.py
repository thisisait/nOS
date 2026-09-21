"""Books is the praxis projection: queue + invoices + journals + parties.

Face Books must load the SoT tables and HMAC-upsert only pending-invoice-verify.
A tab that drops journal-entry or books invoices itself is not this organ.
"""

from __future__ import annotations

import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]
BOOKS = REPO / "files/anatomy/face/src/lib/apps/native/BooksApp.svelte"


def test_books_loads_the_praxis_tables_and_does_not_upsert_invoices():
    src = BOOKS.read_text(encoding="utf-8")
    for table in (
        "pending-invoice-verify",
        "invoice",
        "invoice-line",
        "journal-entry",
        "party",
    ):
        assert f"loadTable('{table}')" in src, f"Books no longer loads {table}"
    assert "tablesUpsertRow('pending-invoice-verify'" in src
    assert "tablesUpsertRow('invoice'" not in src
    assert "tablesUpsertRow('journal-entry'" not in src
    assert "tablesUpsertRow('posting'" not in src
    assert "key: 'journals'" in src
    assert "nos:party:" in src
    assert "slug === 'dolibarr'" in src
