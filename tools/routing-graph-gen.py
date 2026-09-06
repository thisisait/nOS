#!/usr/bin/env python3
"""Compile the agent CAPABILITY graph into routing-graph.json (dtt-routing-address).

The capability side of the routing address is GIT-DERIVABLE (agent manifests +
tools/agent-capability.py), so — like the anatomy graph and the loop graph — it
compiles to a committed JSON, dual-written to the face's vendored copy, imported
build-time by the Planner Routing view, and pinned by a regenerate-and-diff gate
(tests/anatomy/test_routing_graph_is_sound.py). One authority: the generator.

WHY NOT the live assignment match here: assignments are RUNTIME currentState
rows, and the matcher (assignment ⊆ capability) is defined once in
tools/nos_work_uri.py — porting it into the face would fork that law. So this
graph shows the capability SPACE (who may do what, where, touching what); the
live match stays the terminal reader tools/work-assignment.py until a BFF hop or
a Pulse-computed match artifact carries the reference matcher's own output.

The graph: a WHERE column per execution locus; each agent under its WHERE;
shared task_type (CO) nodes and scope (KAM) nodes; edges agent→task_type
("can do") and agent→scope ("touches"). Deterministic layout (no Date/random).

    tools/routing-graph-gen.py            # write state/ + face copy
    tools/routing-graph-gen.py --check    # exit 1 if the committed copy is stale
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
import nos_work_uri  # noqa: E402

OUT = REPO / "state/routing-graph.json"
FACE_COPY = REPO / "files/anatomy/face/src/lib/anatomy/routing-graph.json"

COL_W = 300
ROW_H = 70


def _load(mod: str):
    spec = importlib.util.spec_from_file_location(mod, REPO / "tools" / f"{mod}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


cap = _load("agent-capability")


def build() -> dict:
    caps = {d["name"]: a for d in cap._agents() if (a := cap.capability(d)) is not None}
    parsed = {name: nos_work_uri.parse(addr) for name, addr in caps.items()}

    wheres = sorted({w for p in parsed.values() for w in p.where})
    task_types = sorted({c for p in parsed.values() for c in p.co if c != "*"})
    scopes = sorted({k for p in parsed.values() for k in p.kam if k != "*"})

    nodes: list[dict] = []
    edges: list[dict] = []

    # WHERE header nodes (row 0), agents stacked beneath their (first) WHERE.
    where_x = {w: i * COL_W for i, w in enumerate(wheres)}
    for w in wheres:
        nodes.append({"id": f"where:{w}", "kind": "where", "label": w,
                      "x": where_x[w], "y": 0})
    per_where: dict[str, int] = {}
    agent_pos: dict[str, tuple[int, int]] = {}
    for name in sorted(parsed):
        p = parsed[name]
        w = sorted(p.where)[0]
        n = per_where.get(w, 0)
        per_where[w] = n + 1
        x, y = where_x[w], (n + 1) * ROW_H
        agent_pos[name] = (x, y)
        nodes.append({"id": f"agent:{name}", "kind": "agent", "label": name,
                      "x": x, "y": y, "address": caps[name]})
        edges.append({"source": f"agent:{name}", "target": f"where:{w}", "kind": "runs-in"})

    # Shared CO (task_type) and KAM (scope) columns to the right.
    base_x = (len(wheres) + 1) * COL_W
    for i, t in enumerate(task_types):
        nodes.append({"id": f"co:{t}", "kind": "task_type", "label": t,
                      "x": base_x, "y": i * ROW_H})
    for i, s in enumerate(scopes):
        nodes.append({"id": f"kam:{s}", "kind": "scope", "label": s,
                      "x": base_x + COL_W, "y": i * ROW_H})

    for name, p in parsed.items():
        for t in sorted(p.co):
            if t != "*":
                edges.append({"source": f"agent:{name}", "target": f"co:{t}", "kind": "can-do"})
        for s in sorted(p.kam):
            if s != "*":
                edges.append({"source": f"agent:{name}", "target": f"kam:{s}", "kind": "touches"})

    return {
        "generated_by": "tools/routing-graph-gen.py",
        "note": "capability space (git-derived); live assignment match is tools/work-assignment.py",
        "wheres": wheres,
        "task_types": task_types,
        "scopes": scopes,
        "agents": sorted(parsed),
        "nodes": nodes,
        "edges": edges,
    }


def _serialize(g: dict) -> str:
    return json.dumps(g, indent=2, ensure_ascii=False) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    text = _serialize(build())
    if args.check:
        stale = [str(p) for p in (OUT, FACE_COPY)
                 if not p.is_file() or p.read_text(encoding="utf-8") != text]
        if stale:
            print("stale routing-graph.json — run tools/routing-graph-gen.py:\n  "
                  + "\n  ".join(stale), file=sys.stderr)
            return 1
        print("routing-graph: committed copies match")
        return 0
    OUT.write_text(text, encoding="utf-8")
    FACE_COPY.write_text(text, encoding="utf-8")
    g = json.loads(text)
    print(f"wrote {OUT.name} + face copy ({len(g['nodes'])} nodes, {len(g['edges'])} edges)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
