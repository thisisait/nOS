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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--own-party", required=True, help="the party whose books to post (seller or buyer)")
    ap.add_argument("--absorb", action="store_true", help="upsert into KEAP (default dry)")
    ap.add_argument("--out", help="write the gated bundle YAML here (default stdout, dry)")
    args = ap.parse_args()

    try:
        accounts = {r.get("code"): r.get("slug") for r in read_rows("account") if r.get("code")}
        invoices = read_rows("invoice")
    except (urllib.error.URLError, OSError) as exc:
        print(f"REFUSING: KEAP unreadable ({exc})", file=sys.stderr)
        return 2

    entries, postings, skipped = [], [], 0
    for inv in invoices:
        try:
            derived = nos_accounting.derive_entry(inv, args.own_party, accounts)
        except KeyError as exc:
            print(f"skip {inv.get('slug')}: {exc}", file=sys.stderr)
            continue
        if derived is None:
            skipped += 1                     # not our book (own_party is neither party)
            continue
        entries.append(derived["entry"])
        postings.extend(derived["postings"])

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
          f"(skipped {skipped} not-our-book){'  (DRY)' if not args.absorb else ''}", file=sys.stderr)
    if args.absorb:
        return absorb(bundle)
    text = yaml.safe_dump(bundle, sort_keys=False, allow_unicode=True)
    out = args.out and (REPO / args.out if not pathlib.Path(args.out).is_absolute() else pathlib.Path(args.out))
    out.write_text(text) if out else print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
