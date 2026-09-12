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
