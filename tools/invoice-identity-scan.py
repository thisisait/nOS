#!/usr/bin/env python3
"""invoice-identity-scan — does the LIVE invoice table still hold one row per document?

A READER. It writes nothing, and it answers the question that a balance check
structurally cannot: on 2026-09-23 document 2026-BETA-002 stood twice and both
copies balanced, because two correct copies of a document are individually
correct. Identity is the only place that duplication is visible.

Three findings, in the order they matter:

  DUPLICATE  two rows for the same (book_owner, seller, document_number)
  TWIN       the same (seller, document_number) across two books — legitimate
             only when one firm's sale is another's purchase AND both are your
             clients; otherwise it is a party-spine fork wearing a disguise
  DRIFT      a row whose slug is not nos_digest.invoice_slug(...) — it predates
             the identity, or something minted its own id

What it CANNOT see: a duplicate hiding behind a party fork. 2026-ALFA-PHOTO-001
also stands twice live, but one row names `party-ico-00000131` and the other
`synthetic-client-alfa` — the same firm under two spellings — so neither the
identity nor the (seller, document) key matches. That is the party spine's own
problem (dtt `party-identity-fixture-vs-resolver`), and pretending this reader
covers it would be the worst kind of green.

Usage:
  tools/invoice-identity-scan.py            # findings only
  tools/invoice-identity-scan.py --all      # every row, OK lines included
  tools/invoice-identity-scan.py --json     # for a pane / a loop

Exit: 0 clean (or reporting, with --all) · 3 findings · 2 KEAP unreadable.
A reader exits 3 rather than 1 so a loop can declare it in findings_exit_codes.
"""
from __future__ import annotations

import argparse
import collections
import json
import pathlib
import sys
import urllib.error

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "files" / "anatomy" / "module_utils"))
from digest_absorb import read_rows  # noqa: E402
import nos_digest  # noqa: E402


def scan(rows: list[dict]) -> dict:
    """Pure over its input — the tests drive it with plain dicts, no live KEAP."""
    by_identity = collections.defaultdict(list)
    by_document = collections.defaultdict(list)
    drift = []
    for r in rows:
        try:
            want = nos_digest.invoice_slug(r.get("book_owner"), r.get("seller"),
                                           r.get("document_number"))
        except ValueError as exc:
            drift.append({"slug": r.get("slug"), "want": None, "why": str(exc)})
            continue
        if r.get("slug") != want:
            drift.append({"slug": r.get("slug"), "want": want, "why": "not the derived identity"})
        by_identity[want].append(r.get("slug"))
        by_document[(r.get("seller"), r.get("document_number"))].append(r.get("slug"))
    return {
        "rows": len(rows),
        "duplicates": [{"identity": k, "slugs": sorted(v)}
                       for k, v in sorted(by_identity.items()) if len(v) > 1],
        "twins": [{"seller": k[0], "document_number": k[1], "slugs": sorted(v)}
                  for k, v in sorted(by_document.items(), key=lambda kv: str(kv[0]))
                  if len(set(v)) > 1],
        "drift": drift,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--all", action="store_true", help="print every row, not just findings")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    try:
        rows = read_rows("invoice")
    except (urllib.error.URLError, OSError) as exc:
        print(f"UNKNOWN: KEAP unreadable ({exc}) — not reporting green", file=sys.stderr)
        return 2

    report = scan(rows)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"{report['rows']} invoice row(s) live")
        for d in report["duplicates"]:
            print(f"  DUPLICATE {d['identity']}\n            {' · '.join(d['slugs'])}")
        for t in report["twins"]:
            print(f"  TWIN      {t['seller']} / {t['document_number']}\n"
                  f"            {' · '.join(t['slugs'])}")
        for d in report["drift"]:
            print(f"  DRIFT     {d['slug']}\n            {d['why']}"
                  + (f" (expected {d['want']})" if d["want"] else ""))
        if args.all:
            for r in rows:
                print(f"  row       {r.get('slug')}  owner={r.get('book_owner')} "
                      f"seller={r.get('seller')} doc={r.get('document_number')} "
                      f"src={r.get('source')}")
        if not (report["duplicates"] or report["twins"] or report["drift"]):
            print("  clean — one row per document, every id derived")
    return 3 if (report["duplicates"] or report["twins"] or report["drift"]) else 0


if __name__ == "__main__":
    sys.exit(main())
