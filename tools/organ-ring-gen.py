#!/usr/bin/env python3
"""Compile the apex organ-system ring order into the face's organ-ring.json (face-skill-tree-view).

The Planner's skill tree places the 13 organ systems on ring 1 in the apex ruling's
order (core column, left wing, right wing; `order` within a side). The face is synced
alone to the host and cannot read files/anatomy/apex/ruling.yml, so this writes the
ring as a committed copy inside the face. Same sort as tools/roadmap-status.py
ring_order(). Key, side, title and the one-sentence `tells` (the skill tree shows it
as a system's subtitle on hover); everything else stays in the ruling.

    tools/organ-ring-gen.py            # write the face copy
    tools/organ-ring-gen.py --check    # exit 1 if the committed copy is stale
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
RULING = REPO / "files/anatomy/apex/ruling.yml"
OUT = REPO / "files/anatomy/face/src/lib/tables/organ-ring.json"
SIDES = {"core": 0, "left": 1, "right": 2}


def build() -> dict:
    systems = yaml.safe_load(RULING.read_text(encoding="utf-8"))["organ_systems"]
    ring = sorted(systems, key=lambda k: (SIDES.get(systems[k].get("side"), 9), systems[k].get("order", 99)))
    return {"generated_by": "tools/organ-ring-gen.py",
            "ring": [{"key": k, "side": systems[k].get("side"),
                      "title": systems[k].get("title", k), "tells": systems[k].get("tells", "")}
                     for k in ring]}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    text = json.dumps(build(), indent=2) + "\n"
    if args.check:
        if not OUT.is_file() or OUT.read_text(encoding="utf-8") != text:
            print(f"stale {OUT.relative_to(REPO)} — run tools/organ-ring-gen.py", file=sys.stderr)
            return 1
        print("organ-ring: committed copy matches")
        return 0
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
