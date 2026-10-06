#!/usr/bin/env python3
"""What am I part of? The estate as a body plan, for a model that just arrived.

    tools/body.py                  the ladder top to bottom, then senses, limbs, memory, law, reflexes
    tools/body.py "organ system"   every node at one level, most connected first
    tools/body.py service:keap     one node: what it is, its level, what it touches
    tools/body.py keap             same, by local name when that is unambiguous

Reads state/body-plan.json (tools/body-plan-gen.py, a projection of the
anatomy graph) and, for one node's description/source, state/anatomy-graph.json.
READER: never writes, exits 0 whatever it finds; an unreadable
graph prints UNKNOWN, never an empty estate. `--json` for a caller.
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
GRAPH = REPO / "state" / "body-plan.json"
ANATOMY = REPO / "state" / "anatomy-graph.json"

#: The ladder in order, then the cross-cutting systems — one plain line each.
LEVELS = {
    "genome": "declared contracts every part inherits — task types, skills",
    "cell": "who you can be — one model in one specialization",
    "tissue": "cells of one specialization working together",
    "organ": "a part with one job — a service, host daemon, hosted forge or face app",
    "organ system": "organs grouped for one function",
    "organism": "the estate as a whole",
    "habitat": "what lives beside the organism — third-party processors it does not own",
    "sense": "what you can ask — readers, judges and read-only grants",
    "limb": "what you can reach for — tool grants that act",
    "memory": "what the estate has learned — KEAP tables",
    "law": "the rules it inherits — constitution articles and paragraphs",
    "reflex": "what runs by itself — scheduled responses Pulse fires",
}
CROSS = "sense"
EMPTY = {
    "tissue": "nothing declares a tissue yet",
    "organism": "no node stands for the whole; the whole is this graph",
}
TOP = 3
EDGE_CAP = 24


def _degree(graph: dict) -> collections.Counter:
    deg = collections.Counter()
    for e in graph["edges"]:
        deg[e["from"]] += 1
        deg[e["to"]] += 1
    return deg


def _resolve(graph: dict, arg: str) -> list[str]:
    if arg in graph["nodes"]:
        return [arg]
    hits = sorted(n for n in graph["nodes"] if n.split(":", 1)[-1] == arg)
    # `keap` is both service:keap and authentik:keap; the visible one is meant.
    shown = [n for n in hits if graph["nodes"][n]["level"] != "internal"]
    return shown if len(shown) == 1 else hits


def _members(graph: dict, deg: collections.Counter, level: str) -> list[str]:
    return sorted((n for n, v in graph["nodes"].items() if v["level"] == level),
                  key=lambda n: (-deg[n], n))


def overview(graph: dict, deg: collections.Counter) -> dict:
    out = {lv: {"count": len(m := _members(graph, deg, lv)), "top": m[:TOP]} for lv in LEVELS}
    out["internal"] = {"count": graph["counts"].get("internal", 0)}
    return out


def _anatomy_node(nid: str) -> dict:
    """description + source live in the anatomy graph only; UNKNOWN if unreadable."""
    try:
        n = json.loads(ANATOMY.read_text(encoding="utf-8"))["nodes"][nid]
        return {"description": n.get("description"), "source": n.get("source")}
    except (OSError, ValueError, KeyError):
        return {"description": "UNKNOWN (state/anatomy-graph.json unreadable or lacks this node)",
                "source": "UNKNOWN"}


def node_view(graph: dict, nid: str) -> dict:
    n = {**graph["nodes"][nid], **_anatomy_node(nid)}
    touches = [(e["kind"], "->", e["to"]) for e in graph["edges"] if e["from"] == nid]
    touches += [(e["kind"], "<-", e["from"]) for e in graph["edges"] if e["to"] == nid]
    return {"id": nid, **n, "touches": [{"kind": k, "dir": d, "node": o} for k, d, o in touches]}


def main() -> int:
    ap = argparse.ArgumentParser(description="the estate as a body plan")
    ap.add_argument("target", nargs="?", help="a level name or a node id / local name")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    try:
        graph = json.loads(GRAPH.read_text(encoding="utf-8"))
        graph["nodes"], graph["edges"]
    except (OSError, ValueError, KeyError) as exc:
        print(f"body: UNKNOWN — cannot read {GRAPH.relative_to(REPO)} ({exc}); "
              f"regenerate with tools/body-plan-gen.py")
        return 0
    deg = _degree(graph)

    if not args.target:
        data = overview(graph, deg)
        if args.json:
            print(json.dumps(data, indent=2))
            return 0
        print("nOS body plan — genome to habitat, then senses, limbs, memory, law, reflexes "
              "(tools/body.py <level|node>)")
        for lv, line in LEVELS.items():
            if lv == CROSS:
                print("  ── cutting across every level ──")
            print(f"{lv:<13}{line}: {data[lv]['count']}")
            if data[lv]["top"]:
                print(" " * 13 + ", ".join(f"{n} ({deg[n]})" for n in data[lv]["top"]))
            else:
                print(" " * 13 + f"(empty — {EMPTY.get(lv, 'no kind is placed here')})")
        print(f"{'internal':<13}hidden plumbing: {data['internal']['count']}")
        return 0

    if args.target in LEVELS or args.target == "internal":
        members = _members(graph, deg, args.target)
        if args.json:
            print(json.dumps(members, indent=2))
            return 0
        print(f"{args.target} — {LEVELS.get(args.target, 'hidden plumbing')}: {len(members)}")
        if not members:
            print(f"  (empty — {EMPTY.get(args.target, 'no kind is placed here')})")
        for nid in members[:36]:
            print(f"  {nid}  ({deg[nid]} edges)")
        if len(members) > 36:
            print(f"  … {len(members) - 36} more (--json for all)")
        return 0

    hits = _resolve(graph, args.target)
    if len(hits) != 1:
        print(f"body: {args.target!r} " + ("names no node or level" if not hits
              else f"is ambiguous: {', '.join(hits)}"))
        return 0
    data = node_view(graph, hits[0])
    if args.json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return 0
    print(f"{data['id']}  [{data['level']} — {LEVELS.get(data['level'], 'hidden plumbing')}]")
    print(f"  kind:   {data['kind']}")
    print(f"  what:   {data['description']}")
    print(f"  source: {data['source']}")
    t = data["touches"]
    print(f"  touches ({len(t)}):" if t else "  touches: nothing outside internal plumbing")
    for x in t[:EDGE_CAP]:
        print(f"    {x['dir']} {x['node']}  ({x['kind']})")
    if len(t) > EDGE_CAP:
        print(f"    … {len(t) - EDGE_CAP} more (--json for all)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
