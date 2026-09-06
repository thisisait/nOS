"""routing-graph.json is a faithful, current projection of agent capabilities.

Same one-authority contract as the anatomy and loop graphs: the committed JSON
(and the face's vendored copy) must equal a fresh generate, and every edge must
land on a real node. A manifest edit that changes a capability but not the graph
goes red here (regenerate-and-diff), so the Routing view never renders stale.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))


def _load(mod: str):
    spec = importlib.util.spec_from_file_location(mod, REPO / "tools" / f"{mod}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


gen = _load("routing-graph-gen")
OUT = REPO / "state/routing-graph.json"
FACE = REPO / "files/anatomy/face/src/lib/anatomy/routing-graph.json"


def test_committed_matches_a_fresh_build():
    fresh = gen._serialize(gen.build())
    assert OUT.read_text(encoding="utf-8") == fresh, (
        "state/routing-graph.json is stale — run tools/routing-graph-gen.py"
    )


def test_face_copy_is_identical():
    assert FACE.read_text(encoding="utf-8") == OUT.read_text(encoding="utf-8"), (
        "the face's vendored routing-graph.json drifted from state/ — regenerate"
    )


def test_every_edge_lands_on_a_node():
    g = json.loads(OUT.read_text(encoding="utf-8"))
    ids = {n["id"] for n in g["nodes"]}
    for e in g["edges"]:
        assert e["source"] in ids, f"edge source {e['source']} has no node"
        assert e["target"] in ids, f"edge target {e['target']} has no node"


def test_agents_carry_a_parseable_address():
    uri = _load("nos_work_uri")
    g = json.loads(OUT.read_text(encoding="utf-8"))
    agent_nodes = [n for n in g["nodes"] if n["kind"] == "agent"]
    assert agent_nodes, "no agent nodes — the projection is empty"
    for n in agent_nodes:
        uri.parse(n["address"])  # raises on malformed
