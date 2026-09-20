"""UC1 hole: ISDOC → gated bundle → absorb into the right client's book.

Seller/buyer dual-resolve, book_owner stamping, rounding/PDP already exist.
This pin is the praxis path that was still missing: a mixed consulting-firm
ISDOC directory must land journal-entry + posting in EACH client's analytical
311/321 (account.party rowRef, Model C — no tenant column), and those rows
must reach KEAP only through digest_absorb.

Retro-red on today's tree: IsdocImporter.compose stamps a RUN-LEVEL book_owner
on every invoice (including ones that party is not on) and the gated bundle
has no journal-entry/posting at all — derive-postings.py is a second CLI that
keys own_party off --own-party, ignoring invoice.book_owner.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
DOCS = REPO / "state/fixtures/consulting-firm"
SEED = REPO / "state/fixtures/consulting-firm.seed.yml"
TABLES = REPO / "state/keap-tables"
CLIENTS = ["synthetic-client-alfa", "synthetic-client-beta", "synthetic-client-gama"]


def _load(name: str, path: pathlib.Path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


sys.path.insert(0, str(REPO / "files" / "anatomy" / "module_utils"))
ND = _load("nos_digest", REPO / "files/anatomy/module_utils/nos_digest.py")
NA = _load("nos_accounting", REPO / "files/anatomy/module_utils/nos_accounting.py")
ISDOC = _load("digest_import_isdoc", REPO / "tools/digest-import-isdoc.py")
DP = _load("derive_postings", REPO / "tools/derive-postings.py")
DA = _load("digest_absorb", REPO / "tools/digest_absorb.py")


def _seed():
    return yaml.safe_load(SEED.read_text())


def _party_index(seed: dict) -> dict:
    by_key = {}
    for row in seed["party-tax-identity"]:
        if row.get("scheme") == "ICO" and row.get("value") and row.get("party"):
            by_key[("ICO", str(row["value"]))] = row["party"]
    return {"by_key": by_key, "by_name": {}}


def _isdoc_bundle(seed: dict, **importer_kw):
    imp = ISDOC.IsdocImporter(
        "consulting-firm-isdoc", _party_index(seed), fixture_mode=True, **importer_kw)
    bundle, errors = ND.run_importer(imp, str(DOCS), TABLES)
    return imp, bundle, errors


def _ledger_bundle(seed: dict):
    """The UC1 gated bundle: ISDOC invoices + derived entries for every client book."""
    _imp, bundle, errors = _isdoc_bundle(seed)
    assert errors == [], errors
    accounts = DP.build_accounts_by_code(seed["account"])
    DP.attach_ledger(bundle, accounts)
    return bundle


def test_run_level_book_owner_is_not_stamped_on_a_foreign_invoice():
    """A mixed directory + --book-owner-ico alfa must NOT claim beta's invoices."""
    seed = _seed()
    _imp, bundle, errors = _isdoc_bundle(seed, book_owner_ico="00000131")
    assert errors == [], errors
    by_doc = {i["document_number"]: i for i in bundle["deterministic"]["invoice"]}
    assert by_doc["2026-ALFA-001"]["book_owner"] == "synthetic-client-alfa"
    assert by_doc["2026-ALFA-002"]["book_owner"] == "synthetic-client-alfa"
    assert "book_owner" not in by_doc["2026-BETA-001"]
    assert "book_owner" not in by_doc["2026-GAMA-002"]


def test_isdoc_fixtures_derive_into_each_clients_analytical_311_321():
    seed = _seed()
    bundle = _ledger_bundle(seed)
    det = bundle["deterministic"]
    invoices = det["invoice"]
    assert {i["document_number"] for i in invoices} == {
        "2026-ALFA-001", "2026-ALFA-002",
        "2026-BETA-001", "2026-BETA-002",
        "2026-GAMA-001", "2026-GAMA-002",
    }
    assert "journal-entry" in det and "posting" in det, (
        "gated ISDOC bundle has no ledger — absorb would book headers only"
    )
    assert ND.check_bundle(bundle, TABLES) == []
    assert NA.check_entries(det["posting"]) == []
    assert NA.lines_cover_invoices(det["invoice"], det["invoice-line"]) == []

    account_party = {a["slug"]: a.get("party") for a in seed["account"]}
    by_slug = {i["slug"]: i for i in invoices}
    assert all(i.get("book_owner") in CLIENTS for i in invoices), [
        (i["document_number"], i.get("book_owner")) for i in invoices]

    entry_owner = {}
    for je in det["journal-entry"]:
        inv = by_slug[je["source"]]
        entry_owner[je["slug"]] = inv["book_owner"]
    assert len(entry_owner) == 6

    violations = []
    for p in det["posting"]:
        owner = entry_owner[p["entry"]]
        touched = account_party.get(p["account"])
        if touched and touched != owner:
            violations.append(
                f"{p['slug']}: book {owner!r} posted to {p['account']!r} party={touched!r}")
    assert violations == [], "cross-client bridge:\n  " + "\n  ".join(violations)

    # issued alfa (multi-rate) → analytical 311-alfa; received alfa → 321-alfa
    inv_alfa_001 = next(i for i in invoices if i["document_number"] == "2026-ALFA-001")
    inv_alfa_002 = next(i for i in invoices if i["document_number"] == "2026-ALFA-002")
    je_001 = f"je-{inv_alfa_001['slug']}"
    je_002 = f"je-{inv_alfa_002['slug']}"
    posted = {(p["entry"], p["account"]) for p in det["posting"]}
    assert (je_001, "acc-311-alfa") in posted
    assert (je_002, "acc-321-alfa") in posted
    vat_001 = [p for p in det["posting"] if p["entry"] == je_001 and p["account"] == "acc-343"]
    assert len(vat_001) == 2 and {p["amount"] for p in vat_001} == {210.0, 60.0}


def test_counterparty_fallback_does_not_steal_the_clients_book():
    """--own-party of the buyer used to book an issued invoice into the
    customer's 321 (or synthetic 321). Analytical 311.<client> wins."""
    seed = _seed()
    _imp, bundle, errors = _isdoc_bundle(seed)
    assert errors == [], errors
    DP.attach_ledger(bundle, DP.build_accounts_by_code(seed["account"]),
                     own_party="synthetic-alfa-customer")
    inv = next(i for i in bundle["deterministic"]["invoice"]
               if i["document_number"] == "2026-ALFA-001")
    assert inv["book_owner"] == "synthetic-client-alfa"
    je = f"je-{inv['slug']}"
    assert any(p["entry"] == je and p["account"] == "acc-311-alfa"
               for p in bundle["deterministic"]["posting"])


def test_absorb_posts_ledger_only_through_digest_absorb(monkeypatch):
    seed = _seed()
    bundle = _ledger_bundle(seed)
    posts = []
    monkeypatch.setattr(DA, "_post_row", lambda table, row, hdr: posts.append((table, row["slug"])))
    monkeypatch.setattr(DA, "ensure_table", lambda *a, **k: None)
    monkeypatch.setattr(DA, "_existing_slugs", lambda *a, **k: set())
    monkeypatch.setattr(DA, "rw_token", lambda: "x")
    monkeypatch.setattr(DA, "proxy_header", lambda: {})
    assert DA.absorb(bundle) == 0
    tables = {t for t, _ in posts}
    assert {"invoice", "invoice-line", "journal-entry", "posting"} <= tables
    assert all(t in ("party", "invoice", "invoice-line", "journal-entry", "posting") for t, _ in posts)
