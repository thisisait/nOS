#!/usr/bin/env python3
"""Project the anatomy graph onto the four questions a newly arrived model asks.

state/anatomy-graph.json holds every node in one address space, in as many
kinds as the estate has organs. A model needs four: who can I be
(specialization), what runs here (system), what can I reach for (tool), what
is known (knowledge). state/home-classes.yml folds each anatomy KIND into one of
those (or `internal`); this file applies the fold and nothing else.

A PROJECTION, not a second graph: every home node is an anatomy node carrying
only its kind and class, and an edge survives only between two non-internal
nodes. A new fact goes into anatomy-graph-gen.py, never here.

Regenerate-and-diff, as anatomy-graph-gen.py: byte-stable, sorted, no
timestamps. Gate: tests/anatomy/test_home_graph_is_a_projection.py.

Usage:
    python3 tools/home-graph-gen.py            # write state/home-graph.json
    python3 tools/home-graph-gen.py --check    # exit 1 if the artifact is stale
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
ANATOMY = REPO / "state" / "anatomy-graph.json"
CLASSES = REPO / "state" / "home-classes.yml"
TARGET = REPO / "state" / "home-graph.json"

HOME_CLASSES = ("specialization", "system", "tool", "knowledge")
ALL_CLASSES = HOME_CLASSES + ("internal",)
#: The only keys a map row may carry — anything more is a per-node fact creeping in.
ROW_KEYS = {"class", "reason"}


def _die(msg: str) -> None:
    print(f"home-graph-gen: {msg}", file=sys.stderr)
    raise SystemExit(1)


def kind_map(doc: dict) -> dict[str, str]:
    """kind -> class from the map file, refusing any row that is not exactly that."""
    rows = (doc or {}).get("classes")
    if not isinstance(rows, dict):
        _die(f"{CLASSES.relative_to(REPO)} has no `classes:` mapping")
    out = {}
    for kind, row in rows.items():
        if not isinstance(row, dict) or set(row) != ROW_KEYS:
            _die(f"kind {kind!r}: a row is exactly {sorted(ROW_KEYS)}, got {row!r}")
        if row["class"] not in ALL_CLASSES:
            _die(f"kind {kind!r}: class {row['class']!r} is not one of {ALL_CLASSES}")
        if not str(row["reason"]).strip():
            _die(f"kind {kind!r}: a class with no reason is an assertion")
        out[kind] = row["class"]
    return out


def project(anatomy: dict, kinds: dict[str, str]) -> dict:
    present = {n["kind"] for n in anatomy["nodes"].values()}
    unmapped = sorted(present - set(kinds))
    if unmapped:
        _die(f"anatomy kinds with no home class: {unmapped} — add a row to "
             f"{CLASSES.relative_to(REPO)} (class + one-line reason)")
    dead = sorted(set(kinds) - present)
    if dead:
        _die(f"map rows for kinds the anatomy graph no longer has: {dead}")

    # Class and kind only: description/source stay in the anatomy graph and
    # are joined by id (tools/home.py), so no fact is held twice.
    nodes = {nid: {"class": kinds[n["kind"]], "kind": n["kind"]}
             for nid, n in sorted(anatomy["nodes"].items())}
    edges = sorted(
        ({"from": e["from"], "to": e["to"], "kind": e["kind"]}
         for e in anatomy["edges"]
         if nodes[e["from"]]["class"] != "internal" and nodes[e["to"]]["class"] != "internal"),
        key=lambda e: (e["from"], e["to"], e["kind"]))
    counts = {c: sum(1 for n in nodes.values() if n["class"] == c) for c in ALL_CLASSES}
    counts["edges"] = len(edges)
    return {
        "version": 1,
        "generated_by": "tools/home-graph-gen.py",
        "projects": "state/anatomy-graph.json",
        "classes_from": "state/home-classes.yml",
        "counts": counts,
        "nodes": nodes,
        "edges": edges,
    }


def build() -> dict:
    anatomy = json.loads(ANATOMY.read_text(encoding="utf-8"))
    return project(anatomy, kind_map(yaml.safe_load(CLASSES.read_text(encoding="utf-8"))))


def render(graph: dict) -> str:
    return json.dumps(graph, indent=2, ensure_ascii=False) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="project state/home-graph.json")
    ap.add_argument("--check", action="store_true", help="exit 1 if the artifact is stale")
    args = ap.parse_args()
    text = render(build())
    c = json.loads(text)["counts"]
    summary = ", ".join(f"{k} {c[k]}" for k in ALL_CLASSES) + f"; {c['edges']} edges"
    if args.check:
        current = TARGET.read_text(encoding="utf-8") if TARGET.exists() else ""
        if current != text:
            print(f"home-graph: {TARGET.relative_to(REPO)} STALE — regenerate with "
                  f"tools/home-graph-gen.py", file=sys.stderr)
            return 1
        print(f"home-graph current ({summary})")
        return 0
    TARGET.write_text(text, encoding="utf-8")
    print(f"wrote {TARGET.relative_to(REPO)} ({summary})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
