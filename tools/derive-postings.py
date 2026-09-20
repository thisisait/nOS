#!/usr/bin/env python3
"""derive-postings — the invoice→ledger tie (accounting increment 3c).

Reads absorbed invoices + the chart of accounts from KEAP and derives one BALANCED
journal entry per invoice, from own_party's books (single-entity): own=seller →
DR 311 / CR 601+343 (issued), own=buyer → DR 501+343 / CR 321 (received). Emits a
{journal-entry, posting} bundle, GATES it (check_bundle + the double-entry
invariant check_entries), and absorbs. NOT a parse-importer — it derives over rows
already in KEAP, so the bundle references pre-existing accounts + invoices as
EXTERNAL rowRefs (KEAP validates them at absorb).

  tools/derive-postings.py --own-party synthetic-mesto-lipno
  tools/derive-postings.py --own-party synthetic-mesto-lipno --absorb

DRY by default. Exit 0 · 1 gate refused / an entry does not balance · 2 KEAP.
"""
from __future__ import annotations

import argparse
import pathlib
import sys
import urllib.error

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "files" / "anatomy" / "module_utils"))
from digest_absorb import absorb, read_rows  # noqa: E402
import nos_accounting  # noqa: E402
import nos_digest  # noqa: E402

TABLES_DIR = REPO / "state" / "keap-tables"


def build_accounts_by_code(account_rows: list) -> dict:
    """{'311': slug, ...} PLUS, for every analytical account (one whose `party`
    is set), a composite '<parent's code>.<party>' entry — e.g. an account row
    {code: '311-alfa', parent: acc-311, party: synthetic-client-alfa} adds
    '311.synthetic-client-alfa'. Pure — shared by the live CLI and the offline
    end-to-end acceptance test, so both build the map identically."""
    by_slug = {r["slug"]: r for r in account_rows if r.get("slug")}
    accounts_by_code = {r["code"]: r["slug"] for r in account_rows if r.get("code")}
    for r in account_rows:
        party, parent = r.get("party"), r.get("parent")
        parent_code = by_slug.get(parent, {}).get("code") if parent else None
        if party and parent_code:
            accounts_by_code[f"{parent_code}.{party}"] = r["slug"]
    return accounts_by_code


def derive_bundle_parts(invoices: list, own_party: str, accounts: dict):
    """Split invoice rows into balanced journal-entry/posting parts for own_party's
    book. Each invoice is (a) skipped if not our book, (b) routed aside + reported
    if it does not reconcile against its own PayableAmount — a dropped/mis-summed
    line or a credit note (nos_accounting.reconcile_invoice), so one bad doc never
    poisons the batch — else (c) derived. Returns (entries, postings, skipped,
    routed, reports). Pure over its inputs, so the money loop is unit-testable
    without a live KEAP."""
    entries, postings, reports = [], [], []
    skipped = routed = 0
    for inv in invoices:
        recon = nos_accounting.reconcile_invoice(inv)
        if recon:
            reports += [f"route-aside {inv.get('slug')}: {e}" for e in recon]
            routed += 1
            continue
        try:
            derived = nos_accounting.derive_entry(inv, own_party, accounts)
        except KeyError as exc:
            reports.append(f"skip {inv.get('slug')}: {exc}")
            continue
        if derived is None:
            skipped += 1                     # not our book (own_party is neither party)
            continue
        entries.append(derived["entry"])
        postings.extend(derived["postings"])
    return entries, postings, skipped, routed, reports


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--own-party", required=True, help="the party whose books to post (seller or buyer)")
    ap.add_argument("--absorb", action="store_true", help="upsert into KEAP (default dry)")
    ap.add_argument("--out", help="write the gated bundle YAML here (default stdout, dry)")
    args = ap.parse_args()

    try:
        accounts = build_accounts_by_code(read_rows("account"))
        invoices = read_rows("invoice")
    except (urllib.error.URLError, OSError) as exc:
        print(f"REFUSING: KEAP unreadable ({exc})", file=sys.stderr)
        return 2

    entries, postings, skipped, routed, reports = derive_bundle_parts(invoices, args.own_party, accounts)
    for r in reports:
        print(r, file=sys.stderr)

    bundle = {"meta": {"source_id": f"derive:{args.own_party}", "importer": "derive-postings",
                       "importer_version": "0.1.0", "trusted": True},
              "deterministic": {"journal-entry": entries, "posting": postings}}

    errors = nos_digest.check_bundle(bundle, TABLES_DIR) + \
        [f"balance: {e}" for e in nos_accounting.check_entries(postings)]
    if errors:
        print("GATE REFUSED — nothing absorbed:", file=sys.stderr)
        for e in errors:
            print(f"  ✗ {e}", file=sys.stderr)
        return 1

    print(f"gate OK: {len(entries)} entr(ies), {len(postings)} posting(s) — all balanced "
          f"(skipped {skipped} not-our-book, routed aside {routed} unreconciled)"
          f"{'  (DRY)' if not args.absorb else ''}", file=sys.stderr)
    if args.absorb:
        return absorb(bundle)
    text = yaml.safe_dump(bundle, sort_keys=False, allow_unicode=True)
    out = args.out and (REPO / args.out if not pathlib.Path(args.out).is_absolute() else pathlib.Path(args.out))
    out.write_text(text) if out else print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
