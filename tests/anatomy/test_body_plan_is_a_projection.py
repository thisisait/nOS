"""The body plan is a projection of the anatomy graph, never a second graph.

state/body-plan.json places anatomy KINDS on biology's ladder (genome → cell →
tissue → organ → organ system → organism → habitat, plus sense / limb /
memory / law / reflex) through the one word that names each kind in
state/genome/lexicon.yml (`names: graph_kind`). The failure this guards is the
one the estate keeps paying for: two representations of one fact — which is
why state/body-levels.yml was folded into the lexicon. If the map grew per-node rows, or
the artifact held a node the anatomy graph does not, the body plan would start
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
PLAN = REPO / "state" / "body-plan.json"
LEVELS = REPO / "state" / "genome" / "lexicon.yml"
GEN = REPO / "tools" / "body-plan-gen.py"


def _gen():
    spec = importlib.util.spec_from_file_location("_body_plan_gen", GEN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load():
    return (json.loads(ANATOMY.read_text(encoding="utf-8")),
            json.loads(PLAN.read_text(encoding="utf-8")),
            yaml.safe_load(LEVELS.read_text(encoding="utf-8")))


def _level_of(doc: dict, word: str) -> str:
    """The class a kind gets: the naming word's level, or the word when it is `cross`."""
    level = doc["words"][word]["level"]
    return word if level == "cross" else level


def test_every_anatomy_kind_has_a_level():
    anatomy, _, doc = _load()
    rows = _gen().kind_rows(doc)
    kinds = {n["kind"] for n in anatomy["nodes"].values()}
    unmapped = sorted(kinds - set(rows))
    assert not unmapped, (
        f"anatomy kinds with no level: {unmapped}. Name each under one word's "
        f"`names: graph_kind` in state/genome/lexicon.yml (+ one-line reason), "
        f"then run tools/body-plan-gen.py")
    bad = {k: _level_of(doc, w) for k, (w, _) in rows.items()
           if _level_of(doc, w) not in _gen().ALL_LEVELS}
    assert not bad, f"levels outside the vocabulary: {bad}"


def test_every_body_node_resolves_to_an_anatomy_node():
    anatomy, plan, doc = _load()
    rows = _gen().kind_rows(doc)
    stray = sorted(set(plan["nodes"]) - set(anatomy["nodes"]))
    assert not stray, f"body-plan nodes the anatomy graph does not hold: {stray[:10]}"
    wrong = [nid for nid, n in plan["nodes"].items()
             if n["kind"] != anatomy["nodes"][nid]["kind"]
             or n["level"] != _level_of(doc, rows[n["kind"]][0])]
    assert not wrong, f"nodes whose kind/level disagree with the source: {wrong[:10]}"
    real = {(e["from"], e["to"], e["kind"]) for e in anatomy["edges"]}
    for e in plan["edges"]:
        assert (e["from"], e["to"], e["kind"]) in real, f"edge not in the anatomy graph: {e}"
        for end in (e["from"], e["to"]):
            assert plan["nodes"][end]["level"] != "internal", f"edge touches internal {end}"


def test_check_is_clean():
    got = subprocess.run([sys.executable, str(GEN), "--check"], cwd=REPO,
                         capture_output=True, text=True, timeout=60)
    assert got.returncode == 0, got.stderr or got.stdout


def test_the_map_holds_no_per_node_facts():
    anatomy, _, doc = _load()
    assert set(doc) == {"version", "order", "words"}, f"unexpected top-level keys: {set(doc)}"
    fat = {k: sorted(r) for k, (_, r) in _gen().kind_rows(doc).items()
           if not isinstance(r, dict) or set(r) != {"graph_kind", "reason"}}
    assert not fat, f"a kind row is exactly graph_kind + reason: {fat}"
    text = LEVELS.read_text(encoding="utf-8")
    named = sorted(nid for nid in anatomy["nodes"] if nid in text)
    assert not named, (
        f"state/genome/lexicon.yml names individual nodes {named[:5]} — per-node "
        f"facts belong in the anatomy graph, the lexicon holds kinds only")
    assert not (REPO / "state" / "body-levels.yml").exists(), (
        "state/body-levels.yml is back — the kind → level map lives in the lexicon only")


def test_an_empty_level_is_counted_not_hidden():
    """tissue and organism hold nothing today; absence must read as absence."""
    _, plan, _ = _load()
    missing = [lv for lv in _gen().ALL_LEVELS if lv not in plan["counts"]]
    assert not missing, f"levels absent from counts (an empty level must say 0): {missing}"
    assert plan["counts"]["tissue"] == 0 and plan["counts"]["organism"] == 0, (
        "tissue/organism gained nodes — update tools/body.py's EMPTY lines and this pin")


def test_law_and_organ_system_are_populated():
    """Both were added on the operator's ruling (2026-10-06); an empty one is a
    harvest that silently stopped, not a level nobody fills."""
    _, plan, _ = _load()
    empty = [lv for lv in ("law", "organ system") if plan["counts"].get(lv, 0) < 1]
    assert not empty, f"levels with no node: {empty}"


#: Connected nodes per level a newcomer walks first. Measured at increment 2
#: (2026-10-05); before it, `sense` was judges alone (5). tissue, organism and
#: habitat carry no floor: the first two are empty by declaration. limb's own
#: floor: the 2026-10-06 resource split left it the 8 acting grants it truly has.
CONNECTED_FLOOR = 10
LEVEL_FLOOR = {"limb": 8}
WALKED = ("genome", "cell", "organ", "organ system", "sense", "limb", "memory", "law", "reflex")


def test_every_walked_level_is_a_graph_not_a_list():
    """A level of isolated nodes is a list, not a graph a model can walk."""
    _, plan, _ = _load()
    touched = {end for e in plan["edges"] for end in (e["from"], e["to"])}
    thin = {lv: n for lv in WALKED
            if (n := sum(1 for t in touched if plan["nodes"][t]["level"] == lv))
            < LEVEL_FLOOR.get(lv, CONNECTED_FLOOR)}
    assert not thin, (
        f"levels below their connected-node floor: {thin}. Add the "
        f"missing kind to tools/anatomy-graph-gen.py from the file that already "
        f"declares it, with its declared edges — never a hand list in the projection")


def test_the_generator_refuses_an_unmapped_kind():
    """The artifact being clean is not the generator enforcing it."""
    gen = _gen()
    anatomy, _, doc = _load()
    kinds = gen.kind_map(doc)
    kinds.pop(next(iter(kinds)))
    with pytest.raises(SystemExit):
        gen.project(anatomy, kinds)
