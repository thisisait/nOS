#!/usr/bin/env python3
"""What the roadmap says, right now.

WHY THIS EXISTS. The `nOS Roadmap` DataTable is the estate's work surface, and
until 2026-08-07 it could only be WRITTEN. `tools/roadmap-seed.py` fills it;
nothing asked it anything. So the roadmap review that produced this file had to
be done with hand-written curl against `/agent/v1/tables`, which is the "vibing
on the OS, not on nOS" path the doctrine forbids — and, predictably, the prose
roadmap in `docs/roadmap.md` had drifted two releases behind without anyone
being able to cheaply notice.

This is the same fix `tools/rem-status.py` was for the security queue: the
estate answers the question, the document names it.

WHAT IT ALSO REPORTS, AND WHY THAT IS HALF THE POINT. The table has two
specifications — `state/keap-tables/roadmap.table.yml` (git) and whatever the
live table actually is — and they diverge today: the live table has nine
columns, the definition has twenty. A reader that printed only rows would let
that keep hiding. So `--schema` diffs them, and the default run prints a one-
line warning when they disagree rather than rendering calm.

`tests/anatomy/test_the_roadmap_declares_the_table_it_fills.py` compares the two
GIT artifacts offline. Only this tool can see the live table, so only this tool
can say whether the definition was ever applied.

Usage:
    tools/roadmap-status.py              # the tally, and everything not queued
    tools/roadmap-status.py --all        # every row, nested under its parent
    tools/roadmap-status.py --track face # one track
    tools/roadmap-status.py --schema     # declared columns vs the live table
    tools/roadmap-status.py --json       # for a caller

Exit 0 when it could read the table. Exit 2 when it could NOT — an unreachable
KEAP must not render as an empty roadmap, which would read as "no work left".
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEF = REPO / "state/keap-tables/roadmap.table.yml"

#: Same table id and forward-auth headers as the seeder. Loopback only — the
#: agent surface is bound to 127.0.0.1 and the estate's edge never sees this.
TABLE = "2d498264-bc9a-4324-9935-489e5e4d92f3"
BASE = f"http://127.0.0.1:8091/api/tables/{TABLE}"
HEADERS = {
    "X-Authentik-Username": "akadmin",
    "X-Authentik-Email": "admin@pazny.eu",
    "X-Authentik-Groups": "nos-providers,nos-admins",
    "Content-Type": "application/json",
}

#: Board order: what is moving, then what is waiting, then what is done. A
#: status the seeder invents tomorrow sorts last under its own name rather than
#: being dropped — an unknown lane is information, not noise.
STATUS_ORDER = ["doing", "active", "next", "review", "blocked",
                "triaged", "queued", "inbox", "parked", "shipped", "dropped"]


def get(url: str) -> dict:
    req = urllib.request.Request(url, headers=HEADERS, method="GET")
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def rank(status: str | None) -> tuple[int, str]:
    s = status or ""
    return (STATUS_ORDER.index(s) if s in STATUS_ORDER else len(STATUS_ORDER), s)


def declared_columns() -> list[str]:
    try:
        import yaml
    except ImportError:  # pragma: no cover - PyYAML is a playbook dependency
        return []
    if not DEF.exists():
        return []
    spec = yaml.safe_load(DEF.read_text(encoding="utf-8"))
    return [c["key"] for c in spec["schema"]["columns"]]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--all", action="store_true", help="every row, not only the ones in motion")
    ap.add_argument("--track", help="restrict to one track")
    ap.add_argument("--schema", action="store_true", help="declared columns vs the live table")
    ap.add_argument("--json", action="store_true", help="machine-readable")
    args = ap.parse_args()

    try:
        table = get(BASE)["data"]
        rows = [r.get("values", r) for r in get(BASE + "/rows?limit=500")["data"]["rows"]]
    except (urllib.error.URLError, OSError, KeyError, ValueError) as exc:
        # Absence must never render as calm. An empty roadmap and an unreachable
        # one look identical on stdout, and only one of them is good news.
        print(f"CANNOT READ the roadmap table: {exc}", file=sys.stderr)
        print(f"  tried {BASE} — is KEAP up? (`docker ps --filter name=keap`)", file=sys.stderr)
        return 2

    live_cols = [c.get("key") for c in (table.get("schema", {}).get("columns") or [])]
    declared = declared_columns()
    missing = [c for c in declared if c not in live_cols]

    if args.schema:
        print(f"declared in {DEF.relative_to(REPO)}: {len(declared)}")
        print(f"live on the table:            {len(live_cols)}")
        print("\n  declared but NOT live: " + (" ".join(missing) or "none"))
        extra = [c for c in live_cols if c not in declared]
        print("  live but NOT declared: " + (" ".join(extra) or "none"))
        if missing:
            print("\n  The definition has never been applied. Nothing applies it —"
                  "\n  the playbook seeds only the three face-* tables"
                  "\n  (roles/pazny.keap/tasks/seed-face-tables.yml).")
        return 0

    if args.track:
        rows = [r for r in rows if r.get("track") == args.track]

    if args.json:
        json.dump({"table": table.get("title"), "rows": rows,
                   "schema": {"declared": declared, "live": live_cols,
                              "declared_not_live": missing}},
                  sys.stdout, indent=1, ensure_ascii=False)
        print()
        return 0

    by_status = collections.Counter(r.get("status") for r in rows)
    by_track = collections.Counter(r.get("track") for r in rows)
    print(f"{table.get('title')} — {len(rows)} rows"
          + (f" · track={args.track}" if args.track else ""))
    print("  " + " · ".join(f"{n} {s}" for s, n in sorted(
        by_status.items(), key=lambda kv: rank(kv[0]))))
    print("  " + " · ".join(f"{s} {n}" for s, n in by_track.most_common()))

    if missing:
        print(f"\n  ! the git definition declares {len(missing)} column(s) this table "
              f"does not have\n    ({' '.join(missing[:6])}"
              f"{' …' if len(missing) > 6 else ''}) — `--schema` for the diff.")

    settled = {"shipped", "dropped"}
    show = rows if args.all else [r for r in rows if r.get("status") not in settled]
    children = collections.defaultdict(list)
    for r in show:
        children[r.get("parent") or ""].append(r)

    def emit(parent: str, depth: int) -> None:
        for r in sorted(children.get(parent, []), key=lambda x: rank(x.get("status"))):
            pad = "  " * depth
            print(f"  {pad}[{r.get('status') or '?':7s}] {r.get('track') or '-':11s} "
                  f"{r.get('slug') or '?':20s} {r.get('title') or ''}")
            emit(r.get("slug") or "\0", depth + 1)

    if show:
        print()
        emit("", 0)
        # A row whose parent is settled or filtered out would otherwise vanish
        # silently — and so would ITS children, which is how `local-llm-lfm25`
        # disappeared from the first run of this tool. Orphans are re-rooted and
        # recursed, not listed flat.
        present = {x.get("slug") for x in show}
        orphans = [r for r in show
                   if r.get("parent") and r.get("parent") not in present]
        if orphans:
            print(f"\n  +{len(orphans)} row(s) whose parent is settled or filtered:")
            for r in sorted(orphans, key=lambda x: rank(x.get("status"))):
                print(f"    [{r.get('status') or '?':7s}] {r.get('track') or '-':11s} "
                      f"{r.get('slug') or '?':20s} {r.get('title') or ''} "
                      f"(under {r.get('parent')})")
                emit(r.get("slug") or "\0", 2)

    if not args.all:
        rest = len(rows) - len(show)
        if rest:
            print(f"\n  +{rest} shipped/dropped — `--all` lists them.")

    # Say what is true NOW, not what was true when this was written. `verified`
    # was absent from the live table until the git definition was applied on
    # 2026-08-08; a footer that kept asserting it is missing would be this
    # repo's own recurring defect, shipped inside the tool built to catch it.
    if "verified" not in live_cols:
        print("\n  status is a CLAIM. The `verified` column that would hold an "
              "independent\n  observation is declared in git and absent from "
              "this table — see `--schema`.")
    else:
        unverified = sum(1 for r in rows if not r.get("verified"))
        # This footer said "and nothing writes it yet" for exactly one day, and
        # was false the moment tools/roadmap-verify.py landed. Count instead of
        # asserting: a number cannot outlive its mode the way a sentence can.
        disagree = [r for r in rows
                    if (r.get("verified") == "confirmed"
                        and r.get("status") not in ("shipped", "dropped"))
                    or (r.get("verified") == "contradicted"
                        and r.get("status") == "shipped")]
        print(f"\n  status is a CLAIM; `verified` is what a probe observed. "
              f"{len(rows) - unverified}/{len(rows)} rows carry a verdict\n"
              f"  (`tools/roadmap-verify.py --all` writes them from "
              f"state/roadmap-probes.yml).")
        if disagree:
            print(f"  {len(disagree)} row(s) where the two disagree — the most "
                  "useful rows here:")
            for r in disagree:
                print(f"    {r.get('slug'):<24} status={r.get('status'):<8} "
                      f"verified={r.get('verified')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
