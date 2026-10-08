#!/usr/bin/env python3
"""What am I part of? The estate as a body plan, for a model that just arrived.

    tools/body.py                  the ladder bottom to top, then the cross-cutting words
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
MANIFEST = REPO / "state" / "manifest.yml"

LEXICON = REPO / "state" / "genome" / "lexicon.yml"


def _lexicon() -> dict:
    """The lexicon document, or {} when unreadable (the caller prints UNKNOWN)."""
    try:
        import yaml  # noqa: PLC0415
        return yaml.safe_load(LEXICON.read_text(encoding="utf-8")) or {}
    except (OSError, ValueError, ImportError):
        return {}


def _levels(doc: dict) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """(ladder, cross-cutting systems): `order` up to `cross`, then every cross word
    that names a graph kind — the rule tools/body-plan-gen.py applies too
    (test_body_levels_are_the_lexicon.py)."""
    try:
        order = doc["order"]
        ladder = tuple(order[: order.index("cross")])
        systems = tuple(w for w, v in doc["words"].items()
                        if v.get("level") == "cross"
                        and any("graph_kind" in r for r in v.get("names") or []))
        return ladder, systems
    except (KeyError, TypeError, ValueError):
        return (), ()


#: What each level means is the lexicon's `means` (test_body_glosses_are_the_lexicon.py),
#: never a string here; which words ARE levels is the lexicon's too.
_LADDER, _SYSTEMS = _levels(_lexicon())
LEVELS = _LADDER + _SYSTEMS


def gloss(level: str) -> str:
    """The lexicon's meaning of a level, on one line; UNKNOWN if unreadable."""
    try:
        return " ".join(str(_lexicon()["words"][level]["means"]).split())
    except (KeyError, TypeError):
        return "UNKNOWN (state/genome/lexicon.yml unreadable or lacks this word)"


#: Where the overview draws the line between the ladder and the cross-cutting systems.
CROSS = _SYSTEMS[0] if _SYSTEMS else None
EMPTY = {
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


def appendage(nid: str) -> str | None:
    """A property, not a level (body-plan.md §4.2): the manifest row's joint, if any."""
    if not nid.startswith("service:"):
        return None
    try:
        import yaml  # noqa: PLC0415
        rows = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))["services"]
    except (OSError, ValueError, KeyError, ImportError):
        return "UNKNOWN (state/manifest.yml unreadable)"
    row = next((r for r in rows if f"service:{r.get('id')}" == nid), {})
    if row.get("joint"):
        return f"appendage (joint: {row['joint']})"
    if row.get("joint_pending"):
        return f"appendage (joint pending: {row['joint_pending']})"
    return None


def node_view(graph: dict, nid: str) -> dict:
    n = {**graph["nodes"][nid], **_anatomy_node(nid), "appendage": appendage(nid)}
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
        ladder = f"{_LADDER[0]} to {_LADDER[-1]}" if _LADDER else "UNKNOWN ladder"
        print(f"nOS body plan — {ladder}, then {', '.join(_SYSTEMS) or 'UNKNOWN cross words'} "
              "(tools/body.py <level|node>)")
        for lv in LEVELS:
            line = gloss(lv)
            if lv == CROSS:
                print("  ── cutting across every level ──")
            print(f"{lv:<13}({data[lv]['count']}) {line}")
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
        what = gloss(args.target) if args.target in LEVELS else "hidden plumbing"
        print(f"{args.target} — {what}: {len(members)}")
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
    what = gloss(data["level"]) if data["level"] in LEVELS else "hidden plumbing"
    print(f"{data['id']}  [{data['level']} — {what}]")
    print(f"  kind:   {data['kind']}")
    if data["appendage"]:
        print(f"  also:   {data['appendage']}")
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
