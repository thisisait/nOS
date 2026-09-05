#!/usr/bin/env python3
"""Generate the loop-harness graph from ledger.py — the source of the loop's shape.

The planner's loops view (face-planner slice 3) renders the agentic loop's
HARNESS: the propose→judge→apply flow, the four roles and what each may write,
the intent classes (with `harness` sayable-but-refused), the config toggle, and
the measured agent write-grants. That structure is DOCTRINE, declared once in
files/anatomy/bone/ledger.py — so this tool derives it from the source (imports
the module, reads the live symbols; the same symbols two gates already import)
rather than restating it, and the face imports the emitted JSON build-time.

Mirrors tools/anatomy-graph-gen.py exactly: byte-stable render (sorted where it
can be, trailing newline, no timestamps), DUAL-WRITE to state/ and the vendored
face copy, `--check` returns 1 on drift. Gate: tests/anatomy/test_loop_graph_is_sound.py.

    tools/loop-graph-gen.py            # write both copies
    tools/loop-graph-gen.py --check    # exit 1 if either copy is stale
"""

from __future__ import annotations

import json
import os
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(REPO, "files", "anatomy", "bone"))
import ledger  # noqa: E402 — THE source of truth for loop structure

import yaml  # noqa: E402

TARGET = os.path.join(REPO, "state", "loop-graph.json")
FACE_TARGET = os.path.join(REPO, "files/anatomy/face/src/lib/anatomy/loop-graph.json")
GRANTS = os.path.join(REPO, "docs/plans/rsi-research/artifacts/wing-write-grants.json")
TOGGLE_SEED = os.path.join(REPO, "state/fixtures/loop-config.seed.yml")

# Lane x-bands (kind → column); nodes stack vertically within a lane. The flow
# edges (propose→judge→apply) draw across, so the picture reads left-to-right:
# what is proposed → who acts → the machinery → what it writes → who may write.
_LANE_X = {"intent": 0, "role": 340, "stage": 680, "table": 1020, "agent": 1360, "route": 1700}
_ROW_H = 92


def _toggle() -> dict:
    """The harness_proposals_enabled row from the committed fixture (repo IS the
    value — see the fixture header). Absent row ⇒ enabled null, not false."""
    try:
        seed = yaml.safe_load(open(TOGGLE_SEED, encoding="utf-8")) or {}
        for row in seed.get("loop-config", []):
            if row.get("slug") == "harness_proposals_enabled":
                return {"found": True, "enabled": bool(row.get("enabled", False)),
                        "name": str(row.get("name", "")), "description": str(row.get("description", "")).strip()}
    except OSError:
        pass
    return {"found": False, "enabled": None, "name": "", "description": ""}


def _grants() -> list[dict]:
    try:
        return (json.load(open(GRANTS, encoding="utf-8")) or {}).get("grants", []) or []
    except OSError:
        return []


def build() -> dict:
    nodes: list[dict] = []
    edges: list[dict] = []
    lane_n: dict[str, int] = {}

    def add(kind: str, ident: str, label: str, **meta) -> str:
        nid = f"{kind}:{ident}"
        i = lane_n.get(kind, 0)
        lane_n[kind] = i + 1
        nodes.append({"id": nid, "kind": kind, "label": label,
                      "x": _LANE_X.get(kind, 0), "y": i * _ROW_H, **meta})
        return nid

    def edge(source: str, target: str, kind: str, label: str = "") -> None:
        edges.append({"id": f"{source}=>{target}", "source": source, "target": target,
                      "kind": kind, **({"label": label} if label else {})})

    # ── The three flow stages (apply is OUT of the loop: a pass waits on
    #    merge→converge→rescan, an act the engine does not perform). ──────────
    propose = add("stage", "propose", "propose", note="a model proposes")
    judge = add("stage", "judge", "judge", note="code runs the gate set")
    apply = add("stage", "apply", "apply", out_of_loop=True,
                note="merge → converge → rescan (outside the engine)")
    edge(propose, judge, "flow", "gates run")
    # The verdict is DERIVED by the judge, never caller-supplied (Constraint A);
    # the three-valued result is the edge's vocabulary.
    edge(judge, apply, "flow", "/".join(ledger.RESULTS) + " → act on pass")

    # ── Roles and what each MAY write (the sqlite authorizer, _ROLE_WRITES). ──
    ROLE_LABEL = {"proposer": "proposer (model)", "evaluator": "evaluator (code)",
                  "operator": "operator", "reader": "reader"}
    STAGE_OF_ROLE = {"proposer": propose, "evaluator": judge}
    for role in sorted(ledger._ROLE_WRITES):
        rid = add("role", role, ROLE_LABEL.get(role, role))
        if role in STAGE_OF_ROLE:
            edge(rid, STAGE_OF_ROLE[role], "acts", "")
        for tbl in sorted(ledger._ROLE_WRITES[role]):
            tid = f"table:{tbl}"
            if not any(n["id"] == tid for n in nodes):
                add("table", tbl, tbl)
            edge(rid, tid, "writes", "")

    # ── Intent classes (what may be proposed). harness is sayable-but-refused;
    #    gate-add always needs the operator. ──────────────────────────────────
    for name in sorted(ledger.INTENT_CLASSES):
        disabled = name in ledger.DISABLED_INTENTS
        op_req = name in ledger.OPERATOR_REQUIRED_INTENTS
        iid = add("intent", name, name, disabled=disabled, operator_required=op_req)
        edge(iid, propose, "proposes", "")

    # ── The config toggle governing the one refused intent. ──────────────────
    tog = _toggle()
    tid = add("toggle", "harness_proposals_enabled", tog["name"] or "Harness proposals",
              enabled=tog["enabled"], found=tog["found"],
              address="loop-config / harness_proposals_enabled",
              description=tog["description"])
    if "intent:harness" in {n["id"] for n in nodes}:
        edge(tid, "intent:harness", "governs", "off ⇒ refused")

    # ── Measured agent write-grants (agent → HTTP route; a DIFFERENT axis from
    #    role→table, kept as its own edge class). ──────────────────────────────
    for g in _grants():
        agent = str(g.get("agent", ""))
        if not agent:
            continue
        aid = add("agent", agent, agent)
        for r in g.get("routes", []):
            route = f"{r.get('method', '')} {r.get('path', '')}".strip()
            if not route:
                continue
            rtid = f"route:{route}"
            if not any(n["id"] == rtid for n in nodes):
                add("route", route, route)
            edge(aid, rtid, "may-write", "")

    return {
        "version": 1,
        "generated_from": "files/anatomy/bone/ledger.py",
        "engine_actor": ledger.ENGINE_ACTOR,
        "nodes": nodes,
        "edges": edges,
        # Negative space, rendered as refusals in the estate's style — a harness
        # a system can enhance itself is not a harness.
        "refusals": [
            "POST /verdicts does not exist — a verdict is the judge's exit code, never a caller's claim (Constraint A)",
            f"intent `harness` is refused at propose time; the switch is {ledger.DISABLED_INTENT_TOGGLE}",
            "the proposer authorizer denies loop_verdicts — proposer and judge never share a writable table"
        ]
    }


def render(graph: dict) -> str:
    return json.dumps(graph, indent=2, ensure_ascii=False) + "\n"


def main() -> int:
    out = render(build())
    if "--check" in sys.argv:
        stale = [p for p in (TARGET, FACE_TARGET)
                 if not os.path.exists(p) or open(p, encoding="utf-8").read() != out]
        if stale:
            print("STALE loop-graph.json — run tools/loop-graph-gen.py:", file=sys.stderr)
            for p in stale:
                print("  " + os.path.relpath(p, REPO), file=sys.stderr)
            return 1
        print("loop-graph.json is current in both copies")
        return 0
    for p in (TARGET, FACE_TARGET):
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(out)
    g = build()
    print(f"wrote {len(g['nodes'])} nodes / {len(g['edges'])} edges to both copies")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
