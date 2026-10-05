"""The home graph is a projection of the anatomy graph, never a second graph.

state/home-graph.json answers four questions for a newly arrived model
(specialization / system / tool / knowledge) by folding anatomy KINDS through
state/home-classes.yml. The failure this guards is the one the estate keeps
paying for: two representations of one fact. If the map grew per-node rows, or
the artifact held a node the anatomy graph does not, the home graph would start
drifting from the estate it claims to describe — and read as complete.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import subprocess
import sys

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
ANATOMY = REPO / "state" / "anatomy-graph.json"
HOME = REPO / "state" / "home-graph.json"
CLASSES = REPO / "state" / "home-classes.yml"
GEN = REPO / "tools" / "home-graph-gen.py"


def _gen():
    spec = importlib.util.spec_from_file_location("_home_graph_gen", GEN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load():
    return (json.loads(ANATOMY.read_text(encoding="utf-8")),
            json.loads(HOME.read_text(encoding="utf-8")),
            yaml.safe_load(CLASSES.read_text(encoding="utf-8")))


def test_every_anatomy_kind_has_a_class():
    anatomy, _, doc = _load()
    kinds = {n["kind"] for n in anatomy["nodes"].values()}
    unmapped = sorted(kinds - set(doc["classes"]))
    assert not unmapped, (
        f"anatomy kinds with no home class: {unmapped}. Add a row to "
        f"state/home-classes.yml (class + one-line reason), then run "
        f"tools/home-graph-gen.py")
    bad = {k: r.get("class") for k, r in doc["classes"].items()
           if r.get("class") not in _gen().ALL_CLASSES}
    assert not bad, f"classes outside the five: {bad}"


def test_every_home_node_resolves_to_an_anatomy_node():
    anatomy, home, doc = _load()
    stray = sorted(set(home["nodes"]) - set(anatomy["nodes"]))
    assert not stray, f"home nodes the anatomy graph does not hold: {stray[:10]}"
    wrong = [nid for nid, n in home["nodes"].items()
             if n["kind"] != anatomy["nodes"][nid]["kind"]
             or n["class"] != doc["classes"][n["kind"]]["class"]]
    assert not wrong, f"home nodes whose kind/class disagree with the source: {wrong[:10]}"
    real = {(e["from"], e["to"], e["kind"]) for e in anatomy["edges"]}
    for e in home["edges"]:
        assert (e["from"], e["to"], e["kind"]) in real, f"edge not in the anatomy graph: {e}"
        for end in (e["from"], e["to"]):
            assert home["nodes"][end]["class"] != "internal", f"edge touches internal {end}"


def test_check_is_clean():
    got = subprocess.run([sys.executable, str(GEN), "--check"], cwd=REPO,
                         capture_output=True, text=True, timeout=60)
    assert got.returncode == 0, got.stderr or got.stdout


def test_the_map_holds_no_per_node_facts():
    anatomy, _, doc = _load()
    assert set(doc) == {"version", "classes"}, f"unexpected top-level keys: {set(doc)}"
    fat = {k: sorted(r) for k, r in doc["classes"].items()
           if not isinstance(r, dict) or set(r) != {"class", "reason"}}
    assert not fat, f"a map row is exactly class + reason: {fat}"
    text = CLASSES.read_text(encoding="utf-8")
    named = sorted(nid for nid in anatomy["nodes"] if nid in text)
    assert not named, (
        f"state/home-classes.yml names individual nodes {named[:5]} — per-node "
        f"facts belong in the anatomy graph, the map holds kinds only")


def test_the_generator_refuses_an_unmapped_kind():
    """The artifact being clean is not the generator enforcing it."""
    gen = _gen()
    anatomy, _, doc = _load()
    kinds = gen.kind_map(doc)
    kinds.pop(next(iter(kinds)))
    with pytest.raises(SystemExit):
        gen.project(anatomy, kinds)
