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

    # Four fixed left-to-right LANES, one per node kind, reading as the sentence
    # the view IS: WHERE -> WHO (agent) -> CO (task_type) -> KAM (scope).
    LANE_WHERE, LANE_AGENT, LANE_CO, LANE_KAM = (i * COL_W for i in range(4))

    # Agents are grouped under their WHERE (rows within a group, a blank row
    # between groups) so the WHERE->WHO grouping reads visually, not just via
    # the runs-in edge. Row 0 of a group carries the WHERE node itself.
    row = 0
    agent_row: dict[str, int] = {}
    where_row: dict[str, int] = {}
    for w in wheres:
        where_row[w] = row
        group = sorted(name for name, p in parsed.items() if sorted(p.where)[0] == w)
        for name in group:
            row += 1
            agent_row[name] = row
        row += 2  # blank separator row before the next locus group

    for w in wheres:
        nodes.append({"id": f"where:{w}", "kind": "where", "label": w,
                      "x": LANE_WHERE, "y": where_row[w] * ROW_H})
    for name in sorted(parsed):
        p = parsed[name]
        w = sorted(p.where)[0]
        nodes.append({"id": f"agent:{name}", "kind": "agent", "label": name,
                      "x": LANE_AGENT, "y": agent_row[name] * ROW_H, "address": caps[name]})
        edges.append({"source": f"agent:{name}", "target": f"where:{w}", "kind": "runs-in"})

    # ponytail: order the CO/KAM lanes by the barycenter (mean row) of the
    # agents that use each one, one pass, no iterative Sugiyama median-sort —
    # good enough to untangle a graph this small; revisit with a real
    # crossing-count minimizer only if the agent roster gets much bigger.
    def _barycenter(users: list[str]) -> float:
        return sum(agent_row[u] for u in users) / len(users)

    co_users = {t: sorted(n for n, p in parsed.items() if t in p.co) for t in task_types}
    kam_users = {s: sorted(n for n, p in parsed.items() if s in p.kam) for s in scopes}
    task_types_ordered = sorted(task_types, key=lambda t: (_barycenter(co_users[t]), t))
    scopes_ordered = sorted(scopes, key=lambda s: (_barycenter(kam_users[s]), s))

    for i, t in enumerate(task_types_ordered):
        nodes.append({"id": f"co:{t}", "kind": "task_type", "label": t,
                      "x": LANE_CO, "y": i * ROW_H})
    for i, s in enumerate(scopes_ordered):
        nodes.append({"id": f"kam:{s}", "kind": "scope", "label": s,
                      "x": LANE_KAM, "y": i * ROW_H})

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
