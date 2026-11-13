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
    tools/roadmap-status.py --knowledge > roadmap.md   # one file to attach to a cloud chat
    tools/roadmap-status.py --knowledge --status active,next --track face
    tools/roadmap-status.py --json       # for a caller
    tools/roadmap-status.py --frontier watch [--json]   # buildable rows of one subtree
    tools/roadmap-status.py --frontier ring [--json]    # the whole ring: all 13 organ systems
    # each buildable row is `ready` (carries a spec, see spec_ready) or `needs-spec (no …)`

Exit 0 when it could read the table. Exit 2 when it could NOT — an unreachable
KEAP must not render as an empty roadmap, which would read as "no work left".
"""

from __future__ import annotations

import argparse
import collections
import datetime
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEF = REPO / "state/keap-tables/roadmap.table.yml"

#: Same table id and forward-auth headers as the seeder. Loopback only — the
#: agent surface is bound to 127.0.0.1 and the estate's edge never sees this.
from keap_api import human_base, human_headers, paged  # noqa: E402 — sibling helper in tools/
from roadmap_seed_lib import knowledge_pack, rank  # noqa: E402
#: NOS_ROADMAP_TABLE_ID overrides for an estate whose roadmap table was minted
#: through the agent door (id == slug, e.g. "roadmap"); KEAP_API_URL for a
#: non-default loopback publish. Defaults are the operator estate's values.
TABLE = os.environ.get("NOS_ROADMAP_TABLE_ID", "2d498264-bc9a-4324-9935-489e5e4d92f3")
BASE = f"{human_base()}/api/tables/{TABLE}"

#: X-Authentik-* admin identity + the SEC-02 x-keap-proxy-secret (resolved once
#: by keap_api). Without the secret every /api call here 401s since KEAP P1.
HEADERS = human_headers()



def get(url: str) -> dict:
    req = urllib.request.Request(url, headers=HEADERS, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            d = json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")[:200]
        if e.code in (403, 404):
            raise SystemExit(f"CANNOT READ table `{TABLE}`: HTTP {e.code} — it is not visible to you "
                             f"(your tier, or no grant); the estate roadmap needs tier-managers. {body}")
        raise SystemExit(f"CANNOT READ table `{TABLE}`: HTTP {e.code} {body}")
    if not d.get("success", True) or "data" not in d:
        err = str(d.get("error") or d)
        hint = " — not visible to you (your tier, or no grant); the estate roadmap needs tier-managers" \
            if "unknown table" in err else ""
        raise SystemExit(f"CANNOT READ table `{TABLE}`: {err}{hint}")
    return d


def declared_columns() -> list[str]:
    try:
        import yaml
    except ImportError:  # pragma: no cover - PyYAML is a playbook dependency
        return []
    if not DEF.exists():
        return []
    spec = yaml.safe_load(DEF.read_text(encoding="utf-8"))
    return [c["key"] for c in spec["schema"]["columns"]]


def order(r: dict) -> tuple:
    """Status first, then the operator's explicit order, then slug.

    `ordinal` carries the concept `ui.sort` and until 2026-08-09 no reader
    honoured it — so a set of rows deliberately sequenced as a week rendered
    alphabetically, which is the one order that cannot be a plan. Rows with
    no ordinal keep sorting after those that have one rather than at 0,
    because absent is not first.
    """
    raw = r.get("ordinal")
    try:
        explicit = (0, float(raw)) if raw not in (None, "") else (1, 0.0)
    except (TypeError, ValueError):
        explicit = (1, 0.0)
    return (rank(r.get("status")), *explicit, r.get("slug") or "")


#: A label: the word, an optional "(operator)", then a colon ("E2E (operator, Studio):").
_LABEL = r"(?:\s*\([^)\n]*\))?\s*:"
#: The top agent's stamp: it wrote "SPEC ACCEPTED" / "SPEC READY" or its explore-round rulings in.
SPEC_STAMP = re.compile(r"spec (?:accepted|ready)|explore rounds? \d", re.I)
#: The four parts of the house spec shape (roadmap-loop §6), each a label or a heading, never a bare
#: word: "tests/e2e/" in prose is not an acceptance, "never" in prose is not a must-not.
SPEC_PARTS = {
    "goal": re.compile(rf"\bgoal{_LABEL}|^#+ *goal\b", re.I | re.M),
    "slice": re.compile(rf"smallest(?: shippable)? slice|first slice|\bslices?(?: \d+)?{_LABEL}|\bslice \d"
                        r"|^#{1,6} [^\n]*\bslice", re.I | re.M),
    "e2e": re.compile(rf"\be2e(?: acceptance)?{_LABEL}|\bacceptance{_LABEL}|^#{{1,6}} [^\n]*\b(?:e2e|acceptance)\b",
                      re.I | re.M),
    "must-not": re.compile(rf"\bmust not{_LABEL}|^#+ *must not\b|\bout of scope{_LABEL}|\bnon-goals?{_LABEL}",
                           re.I | re.M),
}


def spec_ready(body: str | None) -> tuple[bool, list[str]]:
    """Does the row carry a READY SPEC (operator 2026-11-13: the loop builds only those)?

    Ready = the top agent's stamp (`SPEC ACCEPTED`, `SPEC READY`, `explore round(s) N`), or all four
    parts of the house spec shape, each found case-insensitively as a label or a markdown heading:
      goal      `Goal:` · `## Goal`
      slice     `smallest (shippable) slice` · `first slice` · `Slice:` / `Slice 1` / `Slices:` · a heading naming a slice
      e2e       `E2E:` · `E2E acceptance` · `E2E (operator):` · `Acceptance:` · a heading naming e2e/acceptance
      must-not  `Must not:` · `## Must not` · `Out of scope:` · `Non-goals:`
    Returns (ready, the missing parts in that order). A heuristic over text, not a judge: it says
    whether the shape is there, never whether the spec is good."""
    body = str(body or "")
    if SPEC_STAMP.search(body):
        return True, []
    missing = [part for part, pat in SPEC_PARTS.items() if not pat.search(body)]
    return not missing, missing


#: The statuses that open the frontier: `shipped`, and `active` — a branch the operator has allocated
#: and is growing (an epic ships only when its children do, so shipped-only deadlocks every epic).
#: `review` does not: it is pushed but not landed, a child would stack on code dev does not have.
OPEN, GROWN = ("active", "next"), ("shipped", "active")


def frontier(rows: list[dict], root: str) -> dict:
    """The passive tree under `root` (operator 2026-11-13, roadmap-organic-structure).

    An open row is on the frontier only when every ancestor up to and including
    `root` is shipped; otherwise it names the nearest unshipped ancestor. Rows
    whose parent is not on the board, and cycles met on the way down, are
    reported rather than followed."""
    by_slug = {r.get("slug"): r for r in rows if r.get("slug")}
    if root not in by_slug:
        return {"state": "UNKNOWN", "root": root,
                "reason": f"no row `{root}` on the board"}
    kids = collections.defaultdict(list)
    for r in rows:
        kids[r.get("parent") or ""].append(r)
    missing = sorted(f"{r.get('slug')} (parent `{r.get('parent')}`)" for r in rows
                     if r.get("parent") and r.get("parent") not in by_slug)
    out, blocked, cycles, seen = [], [], [], {root}
    stack = [(by_slug[root], 0, None)]
    while stack:
        node, depth, blocker = stack.pop()
        here = blocker if node.get("status") in GROWN else node
        for c in kids.get(node.get("slug"), []):
            if c.get("slug") in seen:
                cycles.append(f"{node.get('slug')} -> {c.get('slug')}")
                continue
            seen.add(c.get("slug"))
            item = {k: c.get(k) for k in ("slug", "title", "status", "track", "parent")}
            item["depth"] = depth + 1
            if c.get("status") in OPEN:
                if here is None:
                    item["ready"], item["missing"] = spec_ready(c.get("body"))
                    out.append((item, c))
                else:
                    item.update(blocked_by=here.get("slug"), blocked_by_status=here.get("status"))
                    blocked.append((item, c))
            stack.append((c, depth + 1, here))

    def key(pair: tuple) -> tuple:
        return (pair[0]["depth"], *order(pair[1]))
    return {"state": "ok", "root": root, "root_status": by_slug[root].get("status"),
            "frontier": [i for i, _ in sorted(out, key=key)],
            "blocked": [i for i, _ in sorted(blocked, key=key)],
            "cycles": cycles, "missing_parent": missing}


def ring_order() -> list[str]:
    """The 13 apex organ systems in their ring order: core column, then left wing, then right."""
    import yaml
    systems = yaml.safe_load((REPO / "files/anatomy/apex/ruling.yml").read_text(encoding="utf-8"))["organ_systems"]
    side = {"core": 0, "left": 1, "right": 2}
    return sorted(systems, key=lambda k: (side.get(systems[k].get("side"), 9), systems[k].get("order", 99)))


def frontier_ring(rows: list[dict]) -> dict:
    """Every system's frontier, nearest the centre first, then ring order. Open top-level rows that
    hang under no system are `ungrown`: the migration's remaining work, never silently dropped."""
    ring = ring_order()
    by_slug = {r.get("slug"): r for r in rows if r.get("slug")}
    absent = [k for k in ring if k not in by_slug]
    if absent:
        return {"state": "UNKNOWN", "root": "ring", "reason": f"organ-system rows missing: {', '.join(absent)}"}
    out, blocked, cycles, missing = [], [], [], set()
    for i, root in enumerate(ring):
        f = frontier(rows, root)
        for item in f["frontier"]:
            out.append({**item, "system": root, "_ring": i})
        for item in f["blocked"]:
            blocked.append({**item, "system": root, "_ring": i})
        cycles += f["cycles"]
        missing.update(f["missing_parent"])
    ungrown = sorted(r.get("slug") for r in rows if not r.get("parent") and r.get("slug") not in ring
                     and r.get("status") in OPEN and not str(r.get("slug")).startswith("rel-"))  # a milestone, as planner.ts isMilestone
    def key(item: dict) -> tuple:
        return (item["depth"], item["_ring"], *order(by_slug[item["slug"]]))
    clean = lambda items: [{k: v for k, v in i.items() if k != "_ring"} for i in sorted(items, key=key)]  # noqa: E731
    return {"state": "ok", "root": "ring", "root_status": "shipped", "frontier": clean(out), "blocked": clean(blocked),
            "cycles": cycles, "missing_parent": sorted(missing), "ungrown": ungrown}


def print_frontier(f: dict) -> None:
    if f["state"] != "ok":
        print(f"UNKNOWN: frontier under `{f['root']}` — {f['reason']}. Not an empty frontier.")
        return
    ready = sum(1 for r in f["frontier"] if r["ready"])
    print(f"frontier under `{f['root']}` ({f['root_status']}) — "
          f"{len(f['frontier'])} buildable, {len(f['blocked'])} blocked")
    print(f"  {ready} ready, {len(f['frontier']) - ready} needs-spec — the loop builds only `ready`; "
          "a needs-spec row is an explore candidate (roadmap-loop §6)")
    for r in f["frontier"]:
        where = f"{r['system']:10s} " if "system" in r else ""
        spec = "ready" if r["ready"] else "needs-spec (" + ", ".join(f"no {m}" for m in r["missing"]) + ")"
        print(f"  d{r['depth']} [{r['status']:6s}] {where}{r['slug'] or '?':28s} {r['title'] or ''}  — {spec}")
    if f["blocked"]:
        print("\n  blocked — nearest unshipped ancestor:")
        for r in f["blocked"]:
            print(f"  d{r['depth']} [{r['status']:6s}] {r['slug'] or '?':28s} "
                  f"<- `{r['blocked_by']}` ({r['blocked_by_status']})")
    for c in f["cycles"]:
        print(f"  ! cycle: {c}")
    if f["missing_parent"]:
        print(f"  ! {len(f['missing_parent'])} row(s) on the board name a parent that is not on it: "
              + ", ".join(f["missing_parent"][:8]) + (" …" if len(f["missing_parent"]) > 8 else ""))
    if f.get("ungrown"):
        print(f"  ! {len(f['ungrown'])} open top-level row(s) hang under no organ system (not on any frontier): "
              + ", ".join(f["ungrown"][:8]) + (" …" if len(f["ungrown"]) > 8 else ""))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--all", action="store_true", help="every row, not only the ones in motion")
    ap.add_argument("--track", help="restrict to one track")
    ap.add_argument("--status", help="restrict to these statuses, comma-separated (e.g. active,next)")
    ap.add_argument("--schema", action="store_true", help="declared columns vs the live table")
    ap.add_argument("--json", action="store_true", help="machine-readable")
    ap.add_argument("--frontier", metavar="ROOT",
                    help="open rows under ROOT whose ancestors are all shipped; the rest name their blocker")
    ap.add_argument("--knowledge", action="store_true",
                    help="one markdown file of the board (bodies whole) to attach to a conversation")
    args = ap.parse_args()

    try:
        table = get(BASE)["data"]
        rows = [r.get("values", r) for r in paged(get, BASE + "/rows")["data"]["rows"]]
    except (urllib.error.URLError, OSError, KeyError, ValueError, SystemExit) as exc:
        if args.frontier:  # a reader: UNKNOWN and exit 0, never an empty frontier
            f = {"state": "UNKNOWN", "root": args.frontier, "reason": f"board unreadable: {exc}"}
            json.dump(f, sys.stdout) if args.json else print_frontier(f)
            print()
            return 0
        if isinstance(exc, SystemExit):
            raise
        # Absence must never render as calm. An empty roadmap and an unreachable
        # one look identical on stdout, and only one of them is good news.
        print(f"CANNOT READ the roadmap table: {exc}", file=sys.stderr)
        print(f"  tried {BASE} — is KEAP up? (`docker ps --filter name=keap`)", file=sys.stderr)
        return 2

    if args.frontier:
        f = frontier_ring(rows) if args.frontier == "ring" else frontier(rows, args.frontier)
        json.dump(f, sys.stdout, indent=1, ensure_ascii=False) if args.json else print_frontier(f)
        print()
        return 0

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
    if args.status:
        # Naming a status is asking for it: a settled one shows without --all.
        wanted = {x.strip() for x in args.status.split(",") if x.strip()}
        rows = [r for r in rows if r.get("status") in wanted]
        args.all = True

    if args.knowledge:
        sys.stdout.write(knowledge_pack(rows, table.get("title") or TABLE,
                                        datetime.date.today().isoformat(), settled=args.all))
        return 0

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
        for r in sorted(children.get(parent, []), key=order):
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
