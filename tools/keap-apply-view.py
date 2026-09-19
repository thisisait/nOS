#!/usr/bin/env python3
"""Apply a KEAP table definition's `view:` block to the live table.

GENERALIZES tools/roadmap-apply-view.py's shape (same door, same refuse-before
-write / verify-by-reading discipline) for the D5 client-filter-view unit:
`state/keap-tables/invoice.table.yml` and `state/keap-tables/account.table.yml`
each gained a `view: {facets: [...]}` block that, without an applier, is
exactly the defect roadmap-apply-view.py's own header names — "git-green and
estate-absent". Both are digest OUTPUT tables (UNSEEDED in
test_keap_table_concepts.py: rows come from the invoice/accounting importers,
not the playbook seeder), so the playbook-seeder applier does not cover them
either — same split as roadmap.

Kept as a separate small tool rather than folding into roadmap-apply-view.py:
that script's docstring, module constant and tests are roadmap-specific, and
duplicating the ~40-line PATCH/verify body for a second table is smaller and
safer than parameterizing tested, working code for a different owner.

DRY RUN BY DEFAULT. Without `--confirm` this prints the diff and writes
nothing. With `--confirm` it PATCHes and RE-READS the table to check what
landed.

Usage:
    tools/keap-apply-view.py --def state/keap-tables/invoice.table.yml
    tools/keap-apply-view.py --def state/keap-tables/account.table.yml --confirm

Exit 0 applied/nothing-to-do · 1 refused (invalid or unverifiable) · 2 unreadable.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

from keap_api import human_base, human_headers  # noqa: E402 — sibling helper in tools/
API = f"{human_base()}/api/tables"
HEADERS = human_headers()


def call(url: str, method: str = "GET", body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, headers=HEADERS, method=method, data=data)
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def load_definition(def_path: Path) -> tuple[str, dict]:
    import yaml

    spec = yaml.safe_load(def_path.read_text(encoding="utf-8"))
    view = spec.get("view")
    if not isinstance(view, dict):
        sys.exit(f"REFUSING: {def_path.name} declares no `view:` block — nothing to apply.")
    return spec["title"], view


def resolve_table(title: str) -> dict:
    """The live table this definition describes, by its declared title.

    Refuses on 0 or >1 match — a wrong guess would write a render style onto
    somebody else's data.
    """
    tables = call(API)["data"]
    hits = [t for t in tables if t.get("title") == title]
    if len(hits) != 1:
        sys.exit(
            f"REFUSING: {len(hits)} live table(s) titled {title!r} — expected exactly 1.\n"
            f"  known titles: {', '.join(sorted(t.get('title', '?') for t in tables))}"
        )
    return hits[0]


def named_columns(view: dict) -> list[tuple[str, str]]:
    """Every column key the block names, with where it was named."""
    out: list[tuple[str, str]] = []
    for f in ("titleColumn", "bodyColumn", "dateColumn", "mediaColumn"):
        if view.get(f):
            out.append((f, view[f]))
    for i, c in enumerate(view.get("metaColumns") or []):
        out.append((f"metaColumns[{i}]", c))
    for i, c in enumerate(view.get("facets") or []):
        out.append((f"facets[{i}]", c))
    for i, h in enumerate(view.get("highlights") or []):
        for j, p in enumerate(h.get("when") or []):
            out.append((f"highlights[{i}].when[{j}]", p["column"]))
    for j, p in enumerate((view.get("offer") or {}).get("when") or []):
        out.append((f"offer.when[{j}]", p["column"]))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--def", dest="def_path", required=True,
                    help="path to the *.table.yml declaring the view: block")
    ap.add_argument("--confirm", action="store_true", help="actually write (default is a dry run)")
    args = ap.parse_args()

    def_path = Path(args.def_path)
    if not def_path.is_absolute():
        def_path = REPO / def_path
    title, declared = load_definition(def_path)

    try:
        table = resolve_table(title)
        live = call(f"{API}/{table['id']}")["data"]
    except (urllib.error.URLError, OSError, KeyError, ValueError) as exc:
        print(f"CANNOT READ {title!r}: {exc}", file=sys.stderr)
        print(f"  tried {API} — is KEAP up? (`docker ps --filter name=keap`)", file=sys.stderr)
        return 2

    live_cols = {c.get("key") for c in (live.get("schema", {}).get("columns") or [])}
    current = live.get("view")

    # REFUSE BEFORE WRITING. KEAP validates this too (validateViewMeta, on the
    # PATCH), but a local check names the offending field instead of returning
    # the first error, and it costs nothing to fail without a network write.
    unknown = [f"{where} -> {col}" for where, col in named_columns(declared) if col not in live_cols]
    if unknown:
        print("REFUSING: the block names columns the LIVE table does not have:", file=sys.stderr)
        for u in unknown:
            print(f"    {u}", file=sys.stderr)
        print(f"  live columns: {' '.join(sorted(c for c in live_cols if c))}", file=sys.stderr)
        return 1

    print(f"table   : {live.get('title')}  (id {table['id']})")
    print(f"live    : {json.dumps(current, sort_keys=True) if current else '— no view block —'}")
    print(f"declared: {json.dumps(declared, sort_keys=True)}")

    if current == declared:
        print("\nAlready applied — nothing to do.")
        return 0

    if not args.confirm:
        print("\nDRY RUN — nothing was written. Re-run with --confirm to apply.")
        return 0

    call(f"{API}/{table['id']}", method="PATCH", body={"view": declared})

    # VERIFY BY READING, never by the PATCH's status code.
    landed = call(f"{API}/{table['id']}")["data"].get("view")
    if landed != declared:
        print("\nAPPLIED BUT NOT CONFIRMED — the table read back differently:", file=sys.stderr)
        print(f"  wanted: {json.dumps(declared, sort_keys=True)}", file=sys.stderr)
        print(f"  got   : {json.dumps(landed, sort_keys=True)}", file=sys.stderr)
        return 1

    print(f"\nApplied and verified: {len(declared.get('facets') or [])} facet(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
