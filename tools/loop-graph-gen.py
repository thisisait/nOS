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

import glob
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
#: Operational loops are DATA — one declarative manifest each — and this is the
#: single source for both their runtime and their picture (loop-definition-model,
#: ratified 2026-09-07). SERE is the code exception below; every other loop is a
#: <name>.loop.yml here, and a new loop is a new file, never a branch of markup.
LOOPS_DIR = os.path.join(REPO, "files", "anatomy", "loops")

# A loop is a selection, not a filter — draw one at a time (roadmap). SERE is
# the one loop whose shape is CODE (ledger.py), because the engine structurally
# enforces it; it is the exception the loop-definition-model names. Every other
# entry in the catalog comes from a manifest (see build()).
DEFAULT_LOOP = "sere"
SERE_ENTRY = {
    "id": "sere",
    "label": "SERE — self-enhancing loop",
    "blurb": ("The estate improving itself: a model proposes a change, code "
               "alone judges it against the gate set, and only a pass may "
               "land — merge, converge, and rescan happen outside this "
               "engine. Doctrine: files/anatomy/bone/ledger.py."),
}

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


# ── Operational loops, from data (loop-definition-model) ─────────────────────
#
# A loop is a manifest: id/label/blurb + a trigger + ordered steps. A step may
# be PARAMETRISED — `for_each: <param>` expands it to one node per item in that
# param list, so a "fetch each source" step is declared once and drawn as N
# nodes. The face renders the emitted nodes; a future slice generates the pulse
# job(s) from the same trigger+steps (the OTHER output the model names).

_STEP_BAND = 300  # x per step column
_ITEM_H = 84      # y per for_each item within a column
_STEP_RUNNERS = {"tool", "agent", "query"}
_SLUG = __import__("re").compile(r"^[a-z][a-z0-9-]*[a-z0-9]$")


def _tmpl(text: str, item: dict) -> str:
    """`{field}` → item[field]. A parametrised step's label reads per-item."""
    out = text
    for k, v in item.items():
        out = out.replace("{" + str(k) + "}", str(v))
    return out


def _validate_manifest(m: dict, path: str) -> None:
    def bad(why: str):
        raise ValueError(f"{os.path.relpath(path, REPO)}: {why}")

    for req in ("id", "label", "blurb", "trigger", "steps"):
        if req not in m:
            bad(f"missing required key `{req}`")
    if not (isinstance(m["id"], str) and _SLUG.match(m["id"])):
        bad(f"id {m.get('id')!r} is not a slug ([a-z][a-z0-9-])")
    if m["id"] == "sere":
        bad("id `sere` is reserved for the code-defined loop")
    trig = m["trigger"]
    if not isinstance(trig, dict) or not (trig.get("cadence") or trig.get("event")):
        bad("trigger needs a `cadence` (cron) or an `event`")
    params = m.get("params") or {}
    if not isinstance(params, dict):
        bad("`params` must be a map of name → list")
    for pname, items in params.items():
        if not isinstance(items, list) or not all(isinstance(it, dict) and "id" in it for it in items):
            bad(f"param `{pname}` must be a list of objects each with an `id`")
    if not (isinstance(m["steps"], list) and m["steps"]):
        bad("`steps` must be a non-empty list")
    seen: set[str] = set()
    for s in m["steps"]:
        if not (isinstance(s, dict) and isinstance(s.get("id"), str)):
            bad("each step needs a string `id`")
        if s["id"] in seen:
            bad(f"duplicate step id `{s['id']}`")
        seen.add(s["id"])
        if s.get("runner") not in _STEP_RUNNERS:
            bad(f"step `{s['id']}` runner must be one of {sorted(_STEP_RUNNERS)}")
        fe = s.get("for_each")
        if fe is not None and fe not in params:
            bad(f"step `{s['id']}` for_each `{fe}` is not a declared param")


def _load_manifests() -> list[dict]:
    out = []
    for path in sorted(glob.glob(os.path.join(LOOPS_DIR, "*.loop.yml"))):
        m = yaml.safe_load(open(path, encoding="utf-8")) or {}
        _validate_manifest(m, path)  # a manifest a runner can't execute is refused HERE, not at converge
        out.append(m)
    if len({m["id"] for m in out}) != len(out):
        raise ValueError("two loop manifests declare the same id")
    return sorted(out, key=lambda m: m["id"])


def _manifest_graph(m: dict) -> tuple[list[dict], list[dict]]:
    """One manifest → its (nodes, edges), each tagged with the loop's id. A
    for_each step fans: every node of the previous layer wires to every node of
    this one, so the pipeline reads left-to-right whether a step is 1 or N."""
    loop = m["id"]
    params = m.get("params") or {}
    nodes: list[dict] = []
    edges: list[dict] = []

    def N(nid, kind, label, x, y, **meta):
        nodes.append({"id": nid, "kind": kind, "label": label, "loop": loop,
                      "x": x, "y": y, **meta})
        return nid

    def E(src, tgt):
        edges.append({"id": f"{src}=>{tgt}", "source": src, "target": tgt,
                      "kind": "flow", "loop": loop})

    trig = m["trigger"]
    cad = trig.get("cadence") or trig.get("event") or "—"
    prefix = "⏱ " if trig.get("cadence") else "⚡ "
    prev = [N(f"trigger:{loop}", "trigger", prefix + str(cad), 0, 0,
              cadence=trig.get("cadence"), event=trig.get("event"))]

    for i, step in enumerate(m["steps"]):
        x = (i + 1) * _STEP_BAND
        fe = step.get("for_each")
        layer: list[str] = []
        if fe:
            for j, item in enumerate(params.get(fe, [])):
                layer.append(N(f"step:{loop}:{step['id']}:{item['id']}", "step",
                               _tmpl(str(step.get("label", step["id"])), item),
                               x, j * _ITEM_H, runner=step.get("runner", ""),
                               param=fe, item=item["id"]))
        else:
            layer.append(N(f"step:{loop}:{step['id']}", "step",
                           str(step.get("label", step["id"])), x, 0,
                           runner=step.get("runner", "")))
        for p in prev:
            for c in layer:
                E(p, c)
        prev = layer

    return nodes, edges


def build() -> dict:
    nodes: list[dict] = []
    edges: list[dict] = []
    lane_n: dict[str, int] = {}

    def add(kind: str, ident: str, label: str, **meta) -> str:
        nid = f"{kind}:{ident}"
        i = lane_n.get(kind, 0)
        lane_n[kind] = i + 1
        nodes.append({"id": nid, "kind": kind, "label": label, "loop": DEFAULT_LOOP,
                      "x": _LANE_X.get(kind, 0), "y": i * _ROW_H, **meta})
        return nid

    def edge(source: str, target: str, kind: str, label: str = "") -> None:
        edges.append({"id": f"{source}=>{target}", "source": source, "target": target,
                      "kind": kind, "loop": DEFAULT_LOOP,
                      **({"label": label} if label else {})})

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

    # ── Operational loops from manifests — data, generated into the same graph
    #    as SERE's code-derived nodes, each carrying its own `loop` tag. ───────
    manifests = _load_manifests()
    for m in manifests:
        mn, me = _manifest_graph(m)
        nodes.extend(mn)
        edges.extend(me)

    return {
        "version": 2,
        "generated_from": "files/anatomy/bone/ledger.py + files/anatomy/loops/*.loop.yml",
        "engine_actor": ledger.ENGINE_ACTOR,
        "loops": [SERE_ENTRY] + [{"id": m["id"], "label": m["label"], "blurb": m["blurb"]}
                                 for m in manifests],
        "default_loop": DEFAULT_LOOP,
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
