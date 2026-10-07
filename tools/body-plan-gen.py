#!/usr/bin/env python3
"""Project the anatomy graph onto biology's levels of organisation — the body plan.

state/anatomy-graph.json holds every node in one address space, in as many
kinds as the estate has parts. A newly arrived model already knows the ladder
genome → cell → tissue → organ → organ system → organism → habitat, and the
systems that cut across it: sense (reads), limb (acts), memory (learned), law
(inherited), reflex (scheduled response), heartbeat (the liveness signal, the
one host daemon that is no organ). state/genome/lexicon.yml places
each anatomy KIND on one of those (or `internal`) through the one word that
names it under `names: graph_kind`; this file applies the placement and
nothing else.

A PROJECTION, not a second graph: every body-plan node is an anatomy node
carrying only its kind and level, and an edge survives only between two
non-internal nodes. A new fact goes into anatomy-graph-gen.py, never here.

Regenerate-and-diff, as anatomy-graph-gen.py: byte-stable, sorted, no
timestamps. Gate: tests/anatomy/test_body_plan_is_a_projection.py.

Usage:
    python3 tools/body-plan-gen.py            # write state/body-plan.json
    python3 tools/body-plan-gen.py --check    # exit 1 if the artifact is stale
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
ANATOMY = REPO / "state" / "anatomy-graph.json"
LEVELS_FILE = REPO / "state" / "genome" / "lexicon.yml"
TARGET = REPO / "state" / "body-plan.json"

#: The ladder, in order, then the cross-cutting systems. Order is the reading order.
LADDER = ("genome", "cell", "tissue", "organ", "organ system", "organism", "habitat")
SYSTEMS = ("sense", "limb", "memory", "law", "reflex", "heartbeat")
ALL_LEVELS = LADDER + SYSTEMS + ("internal",)
#: The only keys a kind row may carry — anything more is a per-node fact creeping in.
ROW_KEYS = {"graph_kind", "reason"}


def _die(msg: str) -> None:
    print(f"body-plan-gen: {msg}", file=sys.stderr)
    raise SystemExit(1)


def kind_rows(doc: dict) -> dict[str, tuple[str, dict]]:
    """kind -> (naming word, its graph_kind row); a kind named by two words is refused."""
    words = (doc or {}).get("words")
    if not isinstance(words, dict):
        _die(f"{LEVELS_FILE.relative_to(REPO)} has no `words:` mapping")
    out: dict[str, tuple[str, dict]] = {}
    for word, w in words.items():
        for row in w.get("names") or []:
            if "graph_kind" not in row:
                continue
            if row["graph_kind"] in out:
                _die(f"kind {row['graph_kind']!r} is named by both "
                     f"{out[row['graph_kind']][0]!r} and {word!r}")
            out[row["graph_kind"]] = (word, row)
    return out


def kind_map(doc: dict) -> dict[str, str]:
    """kind -> level: the naming word's level, or the word itself when it is `cross`."""
    if tuple((doc or {}).get("order", ())[: len(LADDER)]) != LADDER:
        _die(f"{LEVELS_FILE.relative_to(REPO)} `order` does not open with {LADDER}")
    out = {}
    for kind, (word, row) in kind_rows(doc).items():
        if set(row) != ROW_KEYS:
            _die(f"kind {kind!r}: a row is exactly {sorted(ROW_KEYS)}, got {row!r}")
        level = doc["words"][word]["level"]
        level = word if level == "cross" else level
        if level not in ALL_LEVELS:
            _die(f"kind {kind!r}: level {level!r} (word {word!r}) is not one of {ALL_LEVELS}")
        if not str(row["reason"]).strip():
            _die(f"kind {kind!r}: a level with no reason is an assertion")
        out[kind] = level
    return out


def project(anatomy: dict, kinds: dict[str, str]) -> dict:
    present = {n["kind"] for n in anatomy["nodes"].values()}
    unmapped = sorted(present - set(kinds))
    if unmapped:
        _die(f"anatomy kinds with no level: {unmapped} — name each under one word's "
             f"`names: graph_kind` in {LEVELS_FILE.relative_to(REPO)} (+ one-line reason)")
    dead = sorted(set(kinds) - present)
    if dead:
        _die(f"lexicon names kinds the anatomy graph no longer has: {dead}")

    # Level and kind only: description/source stay in the anatomy graph and
    # are joined by id (tools/body.py), so no fact is held twice.
    nodes = {nid: {"level": kinds[n["kind"]], "kind": n["kind"]}
             for nid, n in sorted(anatomy["nodes"].items())}
    edges = sorted(
        ({"from": e["from"], "to": e["to"], "kind": e["kind"]}
         for e in anatomy["edges"]
         if nodes[e["from"]]["level"] != "internal" and nodes[e["to"]]["level"] != "internal"),
        key=lambda e: (e["from"], e["to"], e["kind"]))
    # Every level is counted, empty ones included: an empty tissue is a fact.
    counts = {lv: sum(1 for n in nodes.values() if n["level"] == lv) for lv in ALL_LEVELS}
    counts["edges"] = len(edges)
    return {
        "version": 1,
        "generated_by": "tools/body-plan-gen.py",
        "projects": "state/anatomy-graph.json",
        "levels_from": "state/genome/lexicon.yml",
        "counts": counts,
        "nodes": nodes,
        "edges": edges,
    }


def build() -> dict:
    anatomy = json.loads(ANATOMY.read_text(encoding="utf-8"))
    return project(anatomy, kind_map(yaml.safe_load(LEVELS_FILE.read_text(encoding="utf-8"))))


def render(graph: dict) -> str:
    return json.dumps(graph, indent=2, ensure_ascii=False) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="project state/body-plan.json")
    ap.add_argument("--check", action="store_true", help="exit 1 if the artifact is stale")
    args = ap.parse_args()
    text = render(build())
    c = json.loads(text)["counts"]
    summary = ", ".join(f"{k} {c[k]}" for k in ALL_LEVELS) + f"; {c['edges']} edges"
    if args.check:
        current = TARGET.read_text(encoding="utf-8") if TARGET.exists() else ""
        if current != text:
            print(f"body-plan: {TARGET.relative_to(REPO)} STALE — regenerate with "
                  f"tools/body-plan-gen.py", file=sys.stderr)
            return 1
        print(f"body-plan current ({summary})")
        return 0
    TARGET.write_text(text, encoding="utf-8")
    print(f"wrote {TARGET.relative_to(REPO)} ({summary})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
