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


def _resolve_account(code: str, party: str | None, accounts_by_code: dict) -> str | None:
    """The one analytical-vs-synthetic decision: try `<code>.<party>` (a
    per-client analytical account, e.g. '311.synthetic-client-alfa') before
    falling back to the shared synthetic `code` — never raising, so a party
    with no analytical account still posts (to the synthetic account)."""
    if party:
        hit = accounts_by_code.get(f"{code}.{party}")
        if hit:
            return hit
    return accounts_by_code.get(code)


def derive_entry(invoice: dict, own_party: str, accounts_by_code: dict) -> dict | None:
    """Derive ONE balanced journal entry from an invoice, from own_party's books
    (single-entity: a firm keeps ONE ledger, so the posting depends on whether
    own_party is the seller or the buyer of this invoice).

    invoice: {slug, seller, buyer, net_amount, vat_amount, vat_breakdown?}.
    accounts_by_code: {'311':slug, '601':slug, '343':slug, '321':slug, '501':slug}
    PLUS, optionally, per-party analytical entries keyed '<code>.<party-slug>'
    (e.g. '311.synthetic-client-alfa') — see _resolve_account. The caller builds
    this map from KEAP account rows; resolution + fallback lives HERE so there is
    one place to check it.
    - own_party is the SELLER → issued invoice: DR 311 gross · CR 601 net · CR 343 vat.
    - own_party is the BUYER  → received invoice: DR 501 net · DR 343 vat · CR 321 gross.
    - own_party is neither    → None (not our book).
    vat_breakdown (D1's per-rate {rate,base,vat} list): when present, posts ONE
    343 leg PER RATE instead of a single leg for vat_amount — the sum still
    equals vat_amount because D1 already sums the breakdown into it.
    Returns {'entry': row, 'postings': [rows]}, balanced by construction. Amounts
    are positive; the side is `direction`.
    """
    net = float(invoice.get("net_amount") or 0)
    vat = float(invoice.get("vat_amount") or 0)
    gross = round(net + vat, 2)
    breakdown = invoice.get("vat_breakdown") or []
    vat_amounts = [round(float(b["vat"]), 2) for b in breakdown if b.get("vat")] if breakdown else ([vat] if vat else [])
    if own_party == invoice.get("seller"):
        legs = [("311", "debit", gross), ("601", "credit", net)] + \
            [("343", "credit", amt) for amt in vat_amounts]
    elif own_party == invoice.get("buyer"):
        legs = [("501", "debit", net)] + \
            [("343", "debit", amt) for amt in vat_amounts] + \
            [("321", "credit", gross)]
    else:
        return None
    codes = {code for code, _, _ in legs}
    missing = [c for c in codes if _resolve_account(c, own_party, accounts_by_code) is None]
    if missing:
        raise KeyError(f"accounts_by_code missing code(s) {missing} for invoice {invoice.get('slug')}")
    entry_slug = f"je-{invoice.get('slug')}"
    counts = {code: sum(1 for c, _, _ in legs if c == code) for code in codes}
    seen: dict = {}
    postings = []
    for code, direction, amount in legs:
        if not amount:
            continue                                            # drop a zero-VAT leg
        seen[code] = seen.get(code, 0) + 1
        suffix = f"-{seen[code]}" if counts[code] > 1 else ""    # multi-rate 343 needs unique slugs
        postings.append({"slug": f"post-{entry_slug}-{code}{suffix}", "entry": entry_slug,
                         "account": _resolve_account(code, own_party, accounts_by_code),
                         "direction": direction, "amount": round(amount, 2)})
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

    inv = {"slug": "inv-x", "seller": "alfa", "buyer": "customer",
           "net_amount": 1500, "vat_amount": 270,
           "vat_breakdown": [{"rate": 21, "base": 1000, "vat": 210}, {"rate": 12, "base": 500, "vat": 60}]}
    synthetic_only = {"311": "acc-311", "601": "acc-601", "343": "acc-343"}
    e = derive_entry(inv, "alfa", synthetic_only)
    assert entry_balances(e["postings"]) == [], "multi-rate entry must still balance"
    vat_legs = [p for p in e["postings"] if p["account"] == "acc-343"]
    assert len(vat_legs) == 2 and round(sum(p["amount"] for p in vat_legs), 2) == 270, \
        "one 343 leg per rate, summing to vat_amount"
    assert next(p for p in e["postings"] if p["direction"] == "debit")["account"] == "acc-311", \
        "no analytical account given -> fell back to the synthetic 311"

    analytical = {**synthetic_only, "311.alfa": "acc-311-alfa"}
    e2 = derive_entry(inv, "alfa", analytical)
    assert next(p for p in e2["postings"] if p["direction"] == "debit")["account"] == "acc-311-alfa", \
        "an analytical 311.<party> account must be preferred over the synthetic one"
    print("nos_accounting self-check OK")
