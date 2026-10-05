#!/usr/bin/env python3
"""Where am I? The estate in four questions, for a model that just arrived.

    tools/home.py                  the four classes, counts, most-connected nodes
    tools/home.py tool             every node in one class, most connected first
    tools/home.py service:keap     one node: what it is, its class, what it touches
    tools/home.py keap             same, by local name when that is unambiguous

Reads state/home-graph.json (tools/home-graph-gen.py, a projection of the
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
GRAPH = REPO / "state" / "home-graph.json"
ANATOMY = REPO / "state" / "anatomy-graph.json"

QUESTIONS = {
    "specialization": "who can I be",
    "system": "what runs here",
    "tool": "what can I reach for",
    "knowledge": "what is known",
}
TOP = 5
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
    shown = [n for n in hits if graph["nodes"][n]["class"] != "internal"]
    return shown if len(shown) == 1 else hits


def overview(graph: dict, deg: collections.Counter) -> dict:
    out = {}
    for cls in QUESTIONS:
        members = [n for n, v in graph["nodes"].items() if v["class"] == cls]
        out[cls] = {"count": len(members),
                    "top": sorted(members, key=lambda n: (-deg[n], n))[:TOP]}
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
    ap = argparse.ArgumentParser(description="the estate in four questions")
    ap.add_argument("target", nargs="?", help="a class name or a node id / local name")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    try:
        graph = json.loads(GRAPH.read_text(encoding="utf-8"))
        graph["nodes"], graph["edges"]
    except (OSError, ValueError, KeyError) as exc:
        print(f"home: UNKNOWN — cannot read {GRAPH.relative_to(REPO)} ({exc}); "
              f"regenerate with tools/home-graph-gen.py")
        return 0
    deg = _degree(graph)

    if not args.target:
        data = overview(graph, deg)
        if args.json:
            print(json.dumps(data, indent=2))
            return 0
        print("nOS home — four questions (tools/home.py <class|node> to go deeper)")
        for cls, q in QUESTIONS.items():
            print(f"\n{cls} — {q}: {data[cls]['count']}")
            for nid in data[cls]["top"]:
                print(f"  {nid}  ({deg[nid]} edges)")
        print(f"\ninternal (hidden plumbing): {data['internal']['count']}")
        return 0

    if args.target in QUESTIONS or args.target == "internal":
        members = sorted((n for n, v in graph["nodes"].items() if v["class"] == args.target),
                         key=lambda n: (-deg[n], n))
        if args.json:
            print(json.dumps(members, indent=2))
            return 0
        print(f"{args.target} — {QUESTIONS.get(args.target, 'hidden plumbing')}: {len(members)}")
        for nid in members[:36]:
            print(f"  {nid}  ({deg[nid]} edges)")
        if len(members) > 36:
            print(f"  … {len(members) - 36} more (--json for all)")
        return 0

    hits = _resolve(graph, args.target)
    if len(hits) != 1:
        print(f"home: {args.target!r} " + ("names no node or class" if not hits
              else f"is ambiguous: {', '.join(hits)}"))
        return 0
    data = node_view(graph, hits[0])
    if args.json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return 0
    print(f"{data['id']}  [{data['class']} — {QUESTIONS.get(data['class'], 'hidden plumbing')}]")
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
