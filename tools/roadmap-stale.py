#!/usr/bin/env python3
"""READER: next/active roadmap rows whose work is already on dev (the board says to do it again).

Row roadmap-stale (2026-11-10): the loop spent most iterations proving rows done; 50 of them
carried "CLOSED 2026-10-02" or a merged branch while still `next`. Signals, each evidence:
a `feat|fix/<slug>` branch that is an ancestor of origin/dev; a body saying CLOSED/SHIPPED
<date>, "Built in <sha>" or "Propose: shipped". A row with open children is never stale.
Reads `nos dtt status --json` and git; writes nothing. Unreadable board = UNKNOWN, exit 0.

    tools/roadmap-stale.py           # slug · status · evidence
    tools/roadmap-stale.py --json
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys

DONE = re.compile(r"^(?:#+ )?(CLOSED \d{4}-\d\d-\d\d|SHIPPED \d{4}-\d\d-\d\d)|\bBuilt in [0-9a-f]{7,}|\bPropose: shipped", re.M)


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], capture_output=True, text=True)


def stale(rows: list[dict]) -> list[dict]:
    refs = set(_git("for-each-ref", "--format=%(refname:short)", "refs/remotes/origin/", "refs/heads/").stdout.split())
    open_parents = {r.get("parent") for r in rows if r["status"] in ("next", "active")}
    out = []
    for r in rows:
        if r["status"] not in ("next", "active") or r["slug"] in open_parents:
            continue
        ev = []
        for ref in (f"origin/feat/{r['slug']}", f"origin/fix/{r['slug']}", f"feat/{r['slug']}", f"fix/{r['slug']}"):
            if ref in refs and _git("merge-base", "--is-ancestor", ref, "origin/dev").returncode == 0:
                ev.append(f"merged {ref}")
                break
        if m := DONE.search(r.get("body") or ""):
            ev.append(f"body: {m.group(0).lstrip('# ')}")
        if ev:
            out.append({"slug": r["slug"], "status": r["status"], "evidence": ev})
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    got = subprocess.run(["nos", "dtt", "status", "--json"], capture_output=True, text=True)
    try:
        rows = json.loads(got.stdout)["rows"]
    except (ValueError, KeyError):
        print(json.dumps({"state": "UNKNOWN", "why": "nos dtt status unreadable"}) if args.json
              else "roadmap-stale: UNKNOWN (nos dtt status unreadable)")
        return 0
    found = stale(rows)
    if args.json:
        print(json.dumps({"state": "OK", "stale": found}, indent=1))
    else:
        for f in found:
            print(f"{f['slug']} · {f['status']} · {'; '.join(f['evidence'])}")
        print(f"{len(found)} stale row(s)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
