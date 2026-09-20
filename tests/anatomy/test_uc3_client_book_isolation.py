"""UC3 isolation pin (deployable beta): Alfa's money must not land on Beta's 311/321.

Model C: analytical 311/321 + book_owner; no tenant column. Existing gates
cover consulting-firm ISDOC (seller/customer, never client-to-client). This
file constructs the missing pair — Alfa sells to Beta — and fails if
derive_entry / attach_ledger posts onto the other client's analytical slug
or retargets book_owner. Concatenating own_party (seller+buyer) must not
resolve a 311/321 row either.
"""
from __future__ import annotations

import copy
import importlib.util
import pathlib

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
SEED = REPO / "state/fixtures/consulting-firm.seed.yml"
ALFA = "synthetic-client-alfa"
BETA = "synthetic-client-beta"
ALFA_311_321 = {"acc-311-alfa", "acc-321-alfa"}
BETA_311_321 = {"acc-311-beta", "acc-321-beta"}


def _load(name: str, path: pathlib.Path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


NA = _load("nos_accounting", REPO / "files/anatomy/module_utils/nos_accounting.py")
DP = _load("derive_postings", REPO / "tools/derive-postings.py")


def _accounts():
    seed = yaml.safe_load(SEED.read_text())
    return DP.build_accounts_by_code(seed["account"]), {
        a["slug"]: a.get("party") for a in seed["account"]}


def _cross_invoices():
    """One commercial fact, two books: Alfa issued / Beta received."""
    base = {"seller": ALFA, "buyer": BETA, "net_amount": 1000, "vat_amount": 210,
            "payable_amount": 1210, "vat_breakdown": [{"rate": 21, "base": 1000, "vat": 210}]}
    alfa = {**base, "slug": "inv-uc3-alfa", "document_number": "UC3-ALFA", "book_owner": ALFA}
    beta = {**base, "slug": "inv-uc3-beta", "document_number": "UC3-BETA", "book_owner": BETA}
    return alfa, beta


def _posted_accounts(postings, entry_slug):
    return {p["account"] for p in postings if p["entry"] == entry_slug}


def _attach(invoices, accounts, own_party=None):
    bundle = {"meta": {"source_id": "uc3-isolation", "importer": "test",
                       "importer_version": "0.1.0", "trusted": True},
              "deterministic": {"invoice": copy.deepcopy(invoices)}}
    DP.attach_ledger(bundle, accounts, own_party=own_party)
    return bundle["deterministic"]


def test_alfa_sale_to_beta_does_not_bridge_analytical_311_321():
    accounts, account_party = _accounts()
    inv_alfa, inv_beta = _cross_invoices()
    det = _attach([inv_alfa, inv_beta], accounts)
    by_slug = {i["slug"]: i for i in det["invoice"]}
    assert by_slug["inv-uc3-alfa"]["book_owner"] == ALFA
    assert by_slug["inv-uc3-beta"]["book_owner"] == BETA

    je_owner = {je["slug"]: by_slug[je["source"]]["book_owner"] for je in det["journal-entry"]}
    assert je_owner["je-inv-uc3-alfa"] == ALFA
    assert je_owner["je-inv-uc3-beta"] == BETA

    alfa_acc = _posted_accounts(det["posting"], "je-inv-uc3-alfa")
    beta_acc = _posted_accounts(det["posting"], "je-inv-uc3-beta")
    assert "acc-311-alfa" in alfa_acc
    assert "acc-321-beta" in beta_acc
    assert alfa_acc.isdisjoint(BETA_311_321), f"Alfa booked Beta 311/321: {alfa_acc}"
    assert beta_acc.isdisjoint(ALFA_311_321), f"Beta booked Alfa 311/321: {beta_acc}"

    for p in det["posting"]:
        touched = account_party.get(p["account"])
        owner = je_owner[p["entry"]]
        assert touched in (None, owner), (
            f"{p['slug']}: book {owner!r} posted to {p['account']!r} party={touched!r}")


def test_concatenated_own_party_cannot_retarget_the_book():
    """If a caller concatenates own_party (or passes the other client as
    fallback), stamped book_owner still owns the 311/321 — never a fused key,
    never Beta's analytical row on Alfa's invoice."""
    accounts, _ = _accounts()
    inv_alfa, _inv_beta = _cross_invoices()
    fused = ALFA + BETA
    det = _attach([inv_alfa], accounts, own_party=fused)
    assert det["invoice"][0]["book_owner"] == ALFA
    acc = _posted_accounts(det["posting"], "je-inv-uc3-alfa")
    assert "acc-311-alfa" in acc
    assert acc.isdisjoint(BETA_311_321)
    assert fused not in "".join(acc)

    e = NA.derive_entry(inv_alfa, fused, accounts)
    assert e is None, "concatenated own_party is neither seller nor buyer — must skip, not post"

    e_wrong = NA.derive_entry(inv_alfa, BETA, accounts)
    wrong_acc = {p["account"] for p in e_wrong["postings"]}
    assert "acc-321-beta" in wrong_acc
    assert wrong_acc.isdisjoint(ALFA_311_321), (
        "deriving Alfa's issued invoice as Beta must not stamp Alfa's 311/321; "
        "Alfa's book is a separate derive_entry(own_party=ALFA)")
