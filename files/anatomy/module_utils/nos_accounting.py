"""nos_accounting — the double-entry invariant for the accounting knowledge graph.

Accounting is a distinct organ from digest; this holds its load-bearing judge,
entry_balances() — the accounting equivalent of nos_digest.check_bundle. A journal
entry is valid only when its debits equal its credits, so an unbalanced entry never
absorbs (the firebreak).

STANDARD-AGNOSTIC by design (accounting-knowledge-graph spec, 2026-09-11): the
arithmetic invariant here knows nothing about which REPORTING standard an account
maps to. We start on a small universal reporting skeleton (asset/liability/equity/
revenue/expense — accounting facts, not copyrightable), onboard the permissive
US-GAAP taxonomy first, and add IFRS later — each standard is additive taxonomy +
mappings, never a change to this invariant.
"""
from __future__ import annotations


def entry_balances(postings: list) -> list[str]:
    """Return [] if the postings of ONE journal entry balance — sum of debit
    amounts == sum of credit amounts — else a list of human-facing errors.

    Money is compared at 2 decimals.  # ponytail: float money rounded to cents;
    a real ledger uses integer minor units per currency — swap when sub-cent or
    multi-currency precision bites. Amounts are always POSITIVE; the side is the
    `direction`, never a negative amount (that is a data error, flagged)."""
    debit = credit = 0.0
    errors: list[str] = []
    for p in postings:
        slug = p.get("slug", "?") if isinstance(p, dict) else "?"
        d = p.get("direction") if isinstance(p, dict) else None
        if d not in ("debit", "credit"):
            errors.append(f"posting {slug}: direction must be 'debit'|'credit', got {d!r}")
            continue
        try:
            amt = float(p.get("amount"))
        except (TypeError, ValueError):
            errors.append(f"posting {slug}: amount is not a number ({p.get('amount')!r})")
            continue
        if amt < 0:
            errors.append(f"posting {slug}: amount is negative ({amt}) — encode the side in "
                          "direction, never a signed amount")
            continue
        debit += amt if d == "debit" else 0.0
        credit += amt if d == "credit" else 0.0
    if not errors and round(debit, 2) != round(credit, 2):
        errors.append(f"entry does not balance: debits {round(debit, 2)} != credits {round(credit, 2)}")
    return errors


def check_entries(postings: list) -> list[str]:
    """Group postings by their `entry` rowRef and balance EACH entry. The bundle-
    level judge over a posting set (any number of journal entries)."""
    by_entry: dict = {}
    errors: list[str] = []
    for p in postings:
        if not isinstance(p, dict):
            errors.append("a posting is not a mapping")
            continue
        by_entry.setdefault(p.get("entry"), []).append(p)
    for entry, group in by_entry.items():
        if entry in (None, ""):
            errors.append("posting(s) with no `entry` rowRef — cannot balance an entryless posting")
            continue
        errors += [f"{entry}: {e}" for e in entry_balances(group)]
    return errors


def derive_entry(invoice: dict, own_party: str, accounts_by_code: dict) -> dict | None:
    """Derive ONE balanced journal entry from an invoice, from own_party's books
    (single-entity: a firm keeps ONE ledger, so the posting depends on whether
    own_party is the seller or the buyer of this invoice).

    invoice: {slug, seller, buyer, net_amount, vat_amount}.  accounts_by_code:
    {'311':slug, '601':slug, '343':slug, '321':slug, '501':slug} (KEAP account rows).
    - own_party is the SELLER → issued invoice: DR 311 gross · CR 601 net · CR 343 vat.
    - own_party is the BUYER  → received invoice: DR 501 net · DR 343 vat · CR 321 gross.
    - own_party is neither    → None (not our book).
    Returns {'entry': row, 'postings': [rows]}, balanced by construction. Amounts are
    positive; the side is `direction`.  # ponytail: uses the synthetic account (311),
    not the analytical 311.<party> — analytical accounts are a later refinement.
    """
    net = float(invoice.get("net_amount") or 0)
    vat = float(invoice.get("vat_amount") or 0)
    gross = round(net + vat, 2)
    if own_party == invoice.get("seller"):
        legs = [("311", "debit", gross), ("601", "credit", net), ("343", "credit", vat)]
    elif own_party == invoice.get("buyer"):
        legs = [("501", "debit", net), ("343", "debit", vat), ("321", "credit", gross)]
    else:
        return None
    missing = [c for c, _, _ in legs if c not in accounts_by_code]
    if missing:
        raise KeyError(f"accounts_by_code missing code(s) {missing} for invoice {invoice.get('slug')}")
    entry_slug = f"je-{invoice.get('slug')}"
    postings = [{"slug": f"post-{entry_slug}-{code}", "entry": entry_slug,
                 "account": accounts_by_code[code], "direction": direction, "amount": amount}
                for code, direction, amount in legs if amount]   # drop a zero-VAT leg
    return {"entry": {"slug": entry_slug, "description": f"Auto z faktury {invoice.get('document_number', invoice.get('slug'))}",
                      "source": invoice.get("slug")},
            "postings": postings}


if __name__ == "__main__":
    balanced = [{"slug": "p1", "direction": "debit", "amount": 48400},
                {"slug": "p2", "direction": "credit", "amount": 40000},
                {"slug": "p3", "direction": "credit", "amount": 8400}]
    assert entry_balances(balanced) == [], entry_balances(balanced)
    off = [{"slug": "p1", "direction": "debit", "amount": 48400},
           {"slug": "p2", "direction": "credit", "amount": 40000}]
    assert any("balance" in e for e in entry_balances(off)), "off-by-8400 must fail"
    assert any("negative" in e for e in entry_balances(
        [{"slug": "p", "direction": "debit", "amount": -5}])), "negative amount must fail"
    assert any(e.startswith("e1:") and "balance" in e for e in check_entries(
        [{"slug": "p1", "entry": "e1", "direction": "debit", "amount": 10},
         {"slug": "p2", "entry": "e1", "direction": "credit", "amount": 9}])), "check_entries groups by entry"
    print("nos_accounting self-check OK")
