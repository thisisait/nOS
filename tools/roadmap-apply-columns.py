#!/usr/bin/env python3
"""Reconcile a NAMED column's shape from roadmap.table.yml to the live table.

WHY THIS EXISTS (sibling of roadmap-apply-view.py). The column half of the
definition was applied by hand and has since drifted: the definition declares
`track` as kind:text (free), while the LIVE column is a `select` with a fixed
option list — so a new track value (`digest`, and every future importer track)
is refused at write time with `track: expected one of options`. apply-view
reconciles the `view:` block; nothing reconciled the columns.

WHY PER-COLUMN AND NOT WHOLESALE. The definition and the live table diverge in
~20 places, several of them DELIBERATE and NOT this tool's to overwrite: the
live `status` board is a curated 7-value set (renaming rows is a decision, not
a cleanup), `refs` is text on purpose (its values are `depends: …` strings, not
JSON), and the live-only `when` column would be DROPPED by any full-columns
PATCH. So this tool reconciles ONLY the columns you name, replaces nothing
else, and refuses to change the column SET.

DRY RUN BY DEFAULT (destructive-op doctrine). --confirm PATCHes then RE-READS to
verify the shape landed — the PATCH's own 200 is a success marker written by the
code that attempted the work, and this estate has paid for that shape too often.

Usage:
    tools/roadmap-apply-columns.py                    # diff declared vs live (all cols)
    tools/roadmap-apply-columns.py --column track     # dry-run the track reconcile
    tools/roadmap-apply-columns.py --column track --confirm

Exit 0 applied/nothing-to-do · 1 refused/unverifiable · 2 unreadable.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEF = REPO / "state/keap-tables/roadmap.table.yml"
API = "http://127.0.0.1:8091/api/tables"

#: The fields this tool copies from the declaration onto a live column. `options`
#: is handled separately (present → set, absent → drop) so text-ifying a select
#: actually removes its enum.
_SHAPE = ("kind", "label", "role", "required")


def reconcile(live_cols: list[dict], declared_by_key: dict, keys: set) -> list[dict]:
    """Live columns, with each NAMED column overlaid by its declared shape.

    Never adds or drops a column — the returned list has the same keys, in the
    same order, as `live_cols`. Raises KeyError if a named column is absent from
    either side (a reconcile that can't name both is a guess).
    """
    live_by_key = {c["key"]: c for c in live_cols}
    for k in keys:
        if k not in live_by_key:
            raise KeyError(f"column {k!r} is not on the live table")
        if k not in declared_by_key:
            raise KeyError(f"column {k!r} is not declared in {DEF.name}")
    out = []
    for c in live_cols:
        if c["key"] not in keys:
            out.append(c)
            continue
        d = declared_by_key[c["key"]]
        merged = {**c, **{f: d[f] for f in _SHAPE if f in d}}
        if d.get("options") is not None:
            merged["options"] = d["options"]
        else:
            merged.pop("options", None)
        out.append(merged)
    return out


def call(url: str, method: str = "GET", body: dict | None = None) -> dict:
    sys.path.insert(0, str(REPO / "tools"))
    from keap_api import human_headers  # sibling helper; lazy so import stays I/O-free

    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, headers=human_headers(), method=method, data=data)
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def resolve_table(title: str) -> dict:
    hits = [t for t in call(API)["data"] if t.get("title") == title]
    if len(hits) != 1:
        sys.exit(f"REFUSING: {len(hits)} live table(s) titled {title!r} — expected exactly 1.")
    return hits[0]


def _shape_of(c: dict) -> str:
    return f"kind={c.get('kind')} options={c.get('options')}"


def main() -> int:
    import yaml

    ap = argparse.ArgumentParser()
    ap.add_argument("--column", action="append", default=[],
                    help="column key to reconcile to the definition (repeatable)")
    ap.add_argument("--confirm", action="store_true", help="apply, then verify by reading back")
    args = ap.parse_args()

    spec = yaml.safe_load(DEF.read_text(encoding="utf-8"))
    declared_by_key = {c["key"]: c for c in spec["schema"]["columns"]}
    table = resolve_table(spec["title"])
    live_cols = call(f"{API}/{table['id']}")["data"]["schema"]["columns"]
    live_by_key = {c["key"]: c for c in live_cols}
    print(f"table: {table.get('title')} (id {table['id']}) · {len(live_cols)} live column(s)")

    if not args.column:
        print("\ndeclared vs live (shape/options differences):")
        for k, d in declared_by_key.items():
            lc = live_by_key.get(k)
            if lc and (d.get("kind") != lc.get("kind") or (d.get("options") or None) != (lc.get("options") or None)):
                print(f"  {k}: def[{_shape_of(d)}] live[{_shape_of(lc)}]")
        print("\nName a column with --column KEY to reconcile it.")
        return 0

    try:
        new_cols = reconcile(live_cols, declared_by_key, set(args.column))
    except KeyError as e:
        sys.exit(f"REFUSING: {e}")

    # The column SET must be untouched — this tool reshapes, never adds/drops.
    assert [c["key"] for c in new_cols] == [c["key"] for c in live_cols], "column set changed"

    for k in args.column:
        print(f"  {k}: {_shape_of(live_by_key[k])}  →  {_shape_of(next(c for c in new_cols if c['key'] == k))}")

    if not args.confirm:
        print("\nDRY RUN — nothing written. Re-run with --confirm to apply.")
        return 0

    import urllib.error
    try:
        call(f"{API}/{table['id']}", "PATCH", {"schema": {"columns": new_cols}})
    except urllib.error.HTTPError as e:
        msg = e.read().decode("utf-8", "replace").strip()
        print(f"\nREFUSED by KEAP ({e.code}): {msg}", file=sys.stderr)
        if "would change kind" in msg:
            print("  KEAP's updateTableSchema (tables.ts) refuses ANY kind change — even\n"
                  "  select→text, the one widening that strands nothing. Needs a KEAP-side\n"
                  "  carve-out before a kind reconcile can land; `options` changes DO apply.",
                  file=sys.stderr)
        return 1
    landed = {c["key"]: c for c in call(f"{API}/{table['id']}")["data"]["schema"]["columns"]}
    bad = [k for k in args.column
           if landed[k].get("kind") != declared_by_key[k].get("kind")
           or (landed[k].get("options") or None) != (declared_by_key[k].get("options") or None)]
    if bad:
        print(f"\nAPPLIED BUT NOT CONFIRMED — read back wrong: {bad}", file=sys.stderr)
        return 1
    print(f"\nApplied and verified: {', '.join(args.column)} reconciled to the definition.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
