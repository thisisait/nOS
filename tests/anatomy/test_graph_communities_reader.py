"""Anatomy CI gate — tools/graph-communities.py is a deterministic reader
that actually detects disagreement.

Same reader contract as graph-report.py: no writes, exit 0 on findings,
UNKNOWN (not green) when the graph is missing. Plus the part specific to a
cross-check: fed a graph where a declared stack straddles two components it
must SAY so, and fed an agreeing graph it must not invent a finding —
a cross-check that cannot go red is decoration.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]
TOOL = REPO / "tools" / "graph-communities.py"


def _mod():
    spec = importlib.util.spec_from_file_location("graph_communities", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _body() -> str:
    return "\n".join(ln for ln in TOOL.read_text(encoding="utf-8").splitlines()
                     if not ln.lstrip().startswith("#"))


def test_it_does_not_write():
    body = _body()
    for verb in ("write_text(", "open(", "unlink(", "mkdir(", "rename(", "subprocess"):
        assert verb not in body, (
            f"graph-communities.py uses {verb} — it is a READER over "
            "state/anatomy-graph.json and may not touch anything else")
    assert "read_text(" in body, "it does not read the graph at all"


def test_two_builds_agree():
    """Label propagation is order-sensitive by nature; the tool pins visit
    order and tie-breaks so two runs cannot disagree and churn a report."""
    mod = _mod()
    assert mod.build() == mod.build()


def _graph(tmp_path, nodes, edges):
    p = tmp_path / "g.json"
    p.write_text(json.dumps({"nodes": nodes, "edges": edges}), encoding="utf-8")
    return p


def test_a_straddling_stack_is_reported(tmp_path, monkeypatch):
    """Two components, one declared stack across both → the split MUST appear;
    the community holding both stacks must appear as mixed."""
    mod = _mod()
    nodes = {"service:a": {"stack": "x"}, "service:b": {"stack": "x"},
             "service:c": {"stack": "y"}, "service:d": {"stack": "y"}}
    edges = [{"from": "service:a", "to": "service:c"},   # x–y bridge
             {"from": "service:b", "to": "service:d"}]
    monkeypatch.setattr(mod, "GRAPH", _graph(tmp_path, nodes, edges))
    d = mod.build()["disagreements"]["stack"]
    assert d["declared_split_across_communities"], "stack x+y straddle components; not reported"
    assert d["community_mixing_declared_values"], "every community mixes x and y; not reported"


def test_an_agreeing_graph_reports_agreement(tmp_path, monkeypatch):
    """Declared stacks that match the components exactly → no finding.
    A cross-check that fires on agreement trains readers to ignore it."""
    mod = _mod()
    nodes = {"service:a": {"stack": "x"}, "service:b": {"stack": "x"},
             "service:c": {"stack": "y"}, "service:d": {"stack": "y"}}
    edges = [{"from": "service:a", "to": "service:b"},
             {"from": "service:c", "to": "service:d"}]
    monkeypatch.setattr(mod, "GRAPH", _graph(tmp_path, nodes, edges))
    d = mod.build()["disagreements"]["stack"]
    assert not d["declared_split_across_communities"]
    assert not d["community_mixing_declared_values"]


def test_drop_excludes_the_node(tmp_path, monkeypatch):
    """--drop exists because service:authentik's 58 SSO edges fold half the
    estate into one community; dropping a node must remove its edges too."""
    mod = _mod()
    nodes = {"service:hub": {}, "service:a": {}, "service:b": {}}
    edges = [{"from": "service:hub", "to": "service:a"},
             {"from": "service:hub", "to": "service:b"}]
    monkeypatch.setattr(mod, "GRAPH", _graph(tmp_path, nodes, edges))
    assert mod.build()["communities"] == 1
    dropped = mod.build({"service:hub"})
    assert dropped["linked_nodes"] == 0, "dropping the hub must drop its edges"
