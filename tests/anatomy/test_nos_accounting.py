"""The double-entry invariant (accounting-knowledge-graph, increment 1).

nos_accounting.entry_balances is the accounting equivalent of check_bundle: a
journal entry absorbs only if its debits equal its credits. Standard-agnostic —
this pins the arithmetic, not any reporting standard.
"""
import importlib.util
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]


def _na():
    spec = importlib.util.spec_from_file_location(
        "nos_accounting", REPO / "files" / "anatomy" / "module_utils" / "nos_accounting.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


NA = _na()

# An issued invoice for 48,400 (20% VAT): DR receivable / CR revenue + VAT output.
BALANCED = [{"slug": "p1", "direction": "debit", "amount": 48400},
            {"slug": "p2", "direction": "credit", "amount": 40000},
            {"slug": "p3", "direction": "credit", "amount": 8400}]


def test_a_balanced_entry_passes():
    assert NA.entry_balances(BALANCED) == []


def test_an_unbalanced_entry_is_refused():
    errs = NA.entry_balances(BALANCED[:2])          # drop the VAT credit
    assert any("balance" in e and "8400" in e for e in errs), errs


def test_a_negative_amount_is_a_data_error():
    errs = NA.entry_balances([{"slug": "p", "direction": "debit", "amount": -5}])
    assert any("negative" in e for e in errs), errs


def test_a_bad_direction_is_refused():
    errs = NA.entry_balances([{"slug": "p", "direction": "left", "amount": 5}])
    assert any("direction" in e for e in errs), errs


ACCOUNTS = {"311": "acc-311", "601": "acc-601", "343": "acc-343",
            "321": "acc-321", "501": "acc-501"}
INVOICE = {"slug": "invoice-x", "document_number": "INV-1",
           "seller": "party-A", "buyer": "party-B", "net_amount": 40000, "vat_amount": 8400}


def test_derive_entry_issued_invoice_from_the_sellers_books():
    e = NA.derive_entry(INVOICE, "party-A", ACCOUNTS)          # own = seller
    legs = {(p["account"], p["direction"]): p["amount"] for p in e["postings"]}
    assert legs == {("acc-311", "debit"): 48400, ("acc-601", "credit"): 40000, ("acc-343", "credit"): 8400}
    assert NA.entry_balances(e["postings"]) == []              # balanced by construction
    assert e["entry"]["source"] == "invoice-x"                 # the digest→ledger tie


def test_derive_entry_received_invoice_from_the_buyers_books():
    e = NA.derive_entry(INVOICE, "party-B", ACCOUNTS)          # own = buyer
    legs = {(p["account"], p["direction"]): p["amount"] for p in e["postings"]}
    assert legs == {("acc-501", "debit"): 40000, ("acc-343", "debit"): 8400, ("acc-321", "credit"): 48400}
    assert NA.entry_balances(e["postings"]) == []


def test_derive_entry_returns_none_when_not_our_book():
    assert NA.derive_entry(INVOICE, "party-C", ACCOUNTS) is None   # neither seller nor buyer


def test_the_accounting_fixture_is_a_valid_bundle_and_balances():
    """The increment-2 fixture: a valid trusted bundle (rowRefs resolve in
    dependency order) whose one journal entry balances under the invariant."""
    import sys
    import yaml
    sys.path.insert(0, str(REPO / "files" / "anatomy" / "module_utils"))
    import nos_digest
    seed = yaml.safe_load((REPO / "state" / "fixtures" / "accounting.seed.yml").read_text())
    assert list(seed.keys()) == ["account", "journal-entry", "posting"]   # dependency order
    assert nos_digest.check_fixture_seed(seed, REPO / "state" / "keap-tables") == []
    assert NA.check_entries(seed["posting"]) == []                        # the demo entry balances


def test_check_entries_balances_each_entry_and_flags_entryless():
    postings = [{"slug": "a", "entry": "e1", "direction": "debit", "amount": 10},
                {"slug": "b", "entry": "e1", "direction": "credit", "amount": 9},   # e1 off by 1
                {"slug": "c", "entry": "e2", "direction": "debit", "amount": 5},
                {"slug": "d", "entry": "e2", "direction": "credit", "amount": 5},   # e2 balances
                {"slug": "x", "direction": "debit", "amount": 1}]                   # no entry
    errs = NA.check_entries(postings)
    assert any(e.startswith("e1:") and "balance" in e for e in errs), errs   # e1 flagged
    assert not any(e.startswith("e2:") for e in errs)                        # e2 clean
    assert any("entryless" in e for e in errs)                               # x flagged
