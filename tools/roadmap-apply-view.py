#!/usr/bin/env python3
"""Apply the roadmap definition's `view:` block to the live table.

WHY THIS EXISTS. `state/keap-tables/roadmap.table.yml` is git-owned and, until
this file, HAD NO APPLIER. `tests/anatomy/test_the_roadmap_declares_the_table_it
_fills.py` said so in its own header on 2026-08-07 — "The definition has never
been applied. Nothing applies it" — and named the reason the carve-out hides it:
`UNSEEDED` in `test_keap_table_concepts.py` excuses the roadmap because its ROWS
come from `tools/roadmap-seed.py`, while what is actually unapplied is the
DEFINITION. The carve-out was doing more work than its reason claimed.

The column half has since been applied by hand (the live table now carries all
23 declared columns). The `view:` block, added 2026-08-28, has not — and it is
the half the nOS face reads to render the roadmap as a timeline with highlight
navigation. Without an applier it is a declaration in git that reaches nothing,
which is this estate's most-repeated defect and never announces itself.

WHY A TOOL AND NOT A PLAYBOOK TASK. The same split `UNSEEDED` records for the
rows: the playbook seeds the three `face-*` config tables; the roadmap is filled
by tools in this family (`roadmap-seed`, `-status`, `-update`, `-verify`). Adding
the roadmap to `seed-face-tables.yml` would POST `slug: roadmap` and CREATE A
SECOND, EMPTY TABLE beside the live one, whose id is a UUID — the worst possible
outcome, since the live table owns `status`/`verified` and a fresh one would
render 122 rows with an empty board. So: same family, same door, same headers.

WHY IT DOES NOT HARDCODE THE TABLE ID. Six tools already carry the literal
`2d498264-…`; a seventh copy of one fact is the defect the genome exists to end.
This one RESOLVES the table by the title the definition itself declares, and
refuses when that matches zero or more than one table rather than guessing. It
therefore keeps working unchanged the day the table id becomes `roadmap`.

DRY RUN BY DEFAULT. Without `--confirm` this prints the diff and writes nothing
(destructive-op doctrine: the operator asks for a write in so many words). With
`--confirm` it PATCHes and then RE-READS the table to check what landed — the
PATCH's own 200 is a success marker written by the code that attempted the work,
and this estate has paid for that shape too many times to accept one here.

Usage:
    tools/roadmap-apply-view.py              # dry run — the diff, nothing written
    tools/roadmap-apply-view.py --confirm    # apply, then verify by reading back

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
DEF = REPO / "state/keap-tables/roadmap.table.yml"

#: Same loopback door and forward-auth headers as the rest of the family. The
#: agent surface is bound to 127.0.0.1 and the estate's edge never sees this.
API = "http://127.0.0.1:8091/api/tables"
from keap_api import human_headers  # noqa: E402 — sibling helper in tools/

#: X-Authentik-* admin identity + the SEC-02 x-keap-proxy-secret (resolved once
#: by keap_api). Without the secret every /api call here 401s since KEAP P1.
HEADERS = human_headers()


def call(url: str, method: str = "GET", body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, headers=HEADERS, method=method, data=data)
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def load_definition() -> tuple[str, dict]:
    import yaml

    spec = yaml.safe_load(DEF.read_text(encoding="utf-8"))
    view = spec.get("view")
    if not isinstance(view, dict):
        sys.exit(f"REFUSING: {DEF.name} declares no `view:` block — nothing to apply.")
    return spec["title"], view


def resolve_table(title: str) -> dict:
    """The live table this definition describes, by its declared title.

    Refuses on 0 or >1 match. A definition that names two tables is a question
    this script must not answer by picking one — a wrong guess writes a render
    style onto somebody else's data.
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
    ap.add_argument("--confirm", action="store_true", help="actually write (default is a dry run)")
    args = ap.parse_args()

    title, declared = load_definition()

    try:
        table = resolve_table(title)
        live = call(f"{API}/{table['id']}")["data"]
    except (urllib.error.URLError, OSError, KeyError, ValueError) as exc:
        # An unreachable KEAP must not read as "already applied".
        print(f"CANNOT READ the roadmap table: {exc}", file=sys.stderr)
        print(f"  tried {API} — is KEAP up? (`docker ps --filter name=keap`)", file=sys.stderr)
        return 2

    live_cols = {c.get("key") for c in (live.get("schema", {}).get("columns") or [])}
    current = live.get("view")

    # REFUSE BEFORE WRITING. KEAP validates this too (validateViewMeta, on the
    # PATCH), but a local check names the offending field instead of returning
    # the first error, and it costs nothing to fail without a network write.
    unknown = [f"{where} → {col}" for where, col in named_columns(declared) if col not in live_cols]
    if unknown:
        print(f"REFUSING: the block names columns the LIVE table does not have:", file=sys.stderr)
        for u in unknown:
            print(f"    {u}", file=sys.stderr)
        print(f"  live columns: {' '.join(sorted(c for c in live_cols if c))}", file=sys.stderr)
        print("  Apply the column half first (`tools/roadmap-status.py --schema`).", file=sys.stderr)
        return 1

    print(f"table  : {live.get('title')}  (id {table['id']})")
    print(f"live   : {json.dumps(current, sort_keys=True) if current else '— no view block —'}")
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

    hl = len(declared.get("highlights") or [])
    print(f"\nApplied and verified: style={declared.get('style')} · "
          f"{len(declared.get('facets') or [])} facet(s) · {hl} highlight(s) · "
          f"{'an offer' if declared.get('offer') else 'no offer'}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
