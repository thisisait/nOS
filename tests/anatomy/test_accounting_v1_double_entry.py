"""accounting-v1-double-entry acceptance (D3, consulting-firm-deployment epic).

Proves, end-to-end and offline (no live KEAP), that derive_entry (1) resolves
an analytical 311.<party>/321.<party> account when one exists, (2) falls back
to the synthetic 311/321 when it doesn't (never raises), (3) posts one 343 VAT
leg PER RATE for a multi-rate invoice, and (4) reproduces the consulting-firm
fixture's own isolation invariant when run over EVERY seeded invoice for
EVERY client's book.

Retro-red: on today's tree (before this D3 change) derive_entry ignores any
'<code>.<party>' key in accounts_by_code (ALWAYS posts to the synthetic
account) and posts exactly one 343 leg from vat_amount regardless of
vat_breakdown — tests 1 and 3 below fail on that tree.
"""
from __future__ import annotations

import importlib.util
import pathlib

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
SEED = REPO / "state/fixtures/consulting-firm.seed.yml"
TABLES_DIR = REPO / "state/keap-tables"
CLIENTS = ["synthetic-client-alfa", "synthetic-client-beta", "synthetic-client-gama"]


def _load(name: str, path: pathlib.Path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


NA = _load("nos_accounting", REPO / "files/anatomy/module_utils/nos_accounting.py")
ND = _load("nos_digest", REPO / "files/anatomy/module_utils/nos_digest.py")
DP = _load("derive_postings", REPO / "tools/derive-postings.py")

INVOICE = {"slug": "invoice-x", "document_number": "INV-1",
           "seller": "party-A", "buyer": "party-B", "net_amount": 40000, "vat_amount": 8400}
MULTI_RATE_INVOICE = {"slug": "invoice-mr", "document_number": "INV-MR",
                      "seller": "party-A", "buyer": "party-B", "net_amount": 1500, "vat_amount": 270,
                      "vat_breakdown": [{"rate": 21, "base": 1000, "vat": 210},
                                        {"rate": 12, "base": 500, "vat": 60}]}


# ── (1) analytical resolution + (2) fallback ─────────────────────────────────

def test_analytical_account_is_preferred_when_present():
    accounts = {"311": "acc-311", "601": "acc-601", "343": "acc-343", "311.party-A": "acc-311-A"}
    e = NA.derive_entry(INVOICE, "party-A", accounts)
    dr_311 = next(p for p in e["postings"] if p["direction"] == "debit")
    assert dr_311["account"] == "acc-311-A", "an analytical 311.<party> account exists but was not used"


def test_fallback_to_synthetic_never_raises():
    accounts = {"311": "acc-311", "601": "acc-601", "343": "acc-343"}   # no analytical row for party-A
    e = NA.derive_entry(INVOICE, "party-A", accounts)
    dr_311 = next(p for p in e["postings"] if p["direction"] == "debit")
    assert dr_311["account"] == "acc-311", "must fall back to the synthetic account, not crash"


# ── (3) multi-rate 343 ────────────────────────────────────────────────────────

def test_multirate_invoice_posts_one_343_leg_per_rate():
    accounts = {"311": "acc-311", "601": "acc-601", "343": "acc-343"}
    e = NA.derive_entry(MULTI_RATE_INVOICE, "party-A", accounts)
    vat_legs = [p for p in e["postings"] if p["account"] == "acc-343"]
    assert len(vat_legs) == 2, f"expected 2 VAT legs (2 rates), got {len(vat_legs)}"
    assert {p["amount"] for p in vat_legs} == {210, 60}
    assert round(sum(p["amount"] for p in vat_legs), 2) == 270.0
    assert NA.entry_balances(e["postings"]) == []          # (5) money: still balanced, exact 2dp


# ── build_accounts_by_code: the shared caller<->derive_entry contract ───────

def test_build_accounts_by_code_derives_composite_keys_from_the_parent():
    rows = [
        {"slug": "acc-311", "code": "311"},
        {"slug": "acc-311-alfa", "code": "311-alfa", "parent": "acc-311", "party": "synthetic-client-alfa"},
    ]
    m = DP.build_accounts_by_code(rows)
    assert m["311"] == "acc-311"
    assert m["311.synthetic-client-alfa"] == "acc-311-alfa"


# ── (4) end-to-end acceptance over the D2 fixture, per client book ─────────

def _fixture():
    assert SEED.exists(), "consulting-firm.seed.yml missing — D2 must run before D3"
    return yaml.safe_load(SEED.read_text())


def test_end_to_end_every_clients_book_balances_with_no_cross_client_bridge():
    seed = _fixture()
    accounts_by_code = DP.build_accounts_by_code(seed["account"])
    account_party = {a["slug"]: a.get("party") for a in seed["account"]}

    for client in CLIENTS:
        entries, postings = [], []
        for inv in seed["invoice"]:
            derived = NA.derive_entry(inv, client, accounts_by_code)
            if derived is None:
                continue                       # not this client's book
            entries.append(derived["entry"])
            postings.extend(derived["postings"])

        assert entries, f"{client}: derive_entry produced no entries at all"
        errors = NA.check_entries(postings)
        assert errors == [], f"{client}: book does not balance: {errors}"

        for p in postings:
            touched_party = account_party.get(p["account"])
            assert touched_party in (None, client), (
                f"{client}'s book posts to account {p['account']!r} whose analytical "
                f"party is {touched_party!r} — cross-client bridge"
            )

    # the derived bundle itself must also be a valid, gate-clean bundle shape
    all_entries, all_postings = [], []
    for client in CLIENTS:
        for inv in seed["invoice"]:
            derived = NA.derive_entry(inv, client, accounts_by_code)
            if derived:
                all_entries.append(derived["entry"])
                all_postings.extend(derived["postings"])
    bundle = {"meta": {"source_id": "derive:test", "importer": "derive-postings",
                       "importer_version": "0.1.0", "trusted": True},
              "deterministic": {"journal-entry": all_entries, "posting": all_postings}}
    assert ND.check_bundle(bundle, TABLES_DIR) == []
    assert NA.check_entries(all_postings) == []


if __name__ == "__main__":
    test_analytical_account_is_preferred_when_present()
    test_fallback_to_synthetic_never_raises()
    test_multirate_invoice_posts_one_343_leg_per_rate()
    test_build_accounts_by_code_derives_composite_keys_from_the_parent()
    test_end_to_end_every_clients_book_balances_with_no_cross_client_bridge()
    print("accounting-v1-double-entry acceptance OK")
