"""The loop-harness graph is a faithful, drift-proof projection of ledger.py.

state/loop-graph.json (compiled by tools/loop-graph-gen.py by IMPORTING
files/anatomy/bone/ledger.py and reading its live constants) is what the
planner's Loops view renders — the propose→judge→apply flow, the four roles and
what each may write, the intent classes, the config toggle, and the measured
agent write-grants. A projection earns its keep only if it cannot drift from its
source, so this gate is the anatomy-graph gate's shape applied to the loop:

  * regenerate-and-diff — the committed JSON equals a fresh build()
  * face-copy identity   — the vendored face copy is byte-identical (the face
                           build context is files/anatomy/face/ only)
  * byte-stable          — two builds agree (no timestamps / unordered sets)

Plus loop-specific truths the render must not soften: the harness intent is
present-but-refused (sayable, never auto-run), the propose→judge→apply spine
exists, and the refusals (no POST /verdicts, harness refused, proposer≠judge
tables) are carried — the estate's negative space, drawn not dropped.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
GRAPH = REPO / "state" / "loop-graph.json"
FACE = REPO / "files/anatomy/face/src/lib/anatomy/loop-graph.json"


def _gen():
    spec = importlib.util.spec_from_file_location(
        "loop_graph_gen", REPO / "tools" / "loop-graph-gen.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def gen():
    return _gen()


@pytest.fixture(scope="module")
def committed():
    return json.loads(GRAPH.read_text(encoding="utf-8"))


def test_the_committed_graph_matches_a_fresh_build(gen):
    assert gen.render(gen.build()) == GRAPH.read_text(encoding="utf-8"), (
        "state/loop-graph.json is stale vs ledger.py — run tools/loop-graph-gen.py")


def test_the_graph_is_byte_stable(gen):
    assert gen.render(gen.build()) == gen.render(gen.build())


def test_the_face_vendored_copy_is_identical(committed):
    assert FACE.read_text(encoding="utf-8") == GRAPH.read_text(encoding="utf-8"), (
        "the face's vendored loop-graph.json diverged from state/ — regenerate")


def test_the_flow_spine_exists(committed):
    ids = {n["id"] for n in committed["nodes"]}
    assert {"stage:propose", "stage:judge", "stage:apply"} <= ids
    flow = {(e["source"], e["target"]) for e in committed["edges"] if e["kind"] == "flow"}
    assert ("stage:propose", "stage:judge") in flow
    assert ("stage:judge", "stage:apply") in flow


def test_the_harness_intent_is_present_but_refused(committed):
    harness = next((n for n in committed["nodes"] if n["id"] == "intent:harness"), None)
    assert harness is not None, "harness must be SHOWN (sayable), not hidden"
    assert harness.get("disabled") is True, "harness must render as refused"


def test_a_loop_is_a_selection_declared_on_every_node(committed):
    """Roadmap: "a loop is a selection, not a filter — draw one at a time".
    Every node/edge is tagged with which loop it belongs to, and the loop
    catalog (id/label/blurb) is a real top-level list, not hardcoded markup."""
    loops = committed.get("loops")
    assert loops and all({"id", "label", "blurb"} <= set(l) for l in loops)
    ids = {l["id"] for l in loops}
    assert committed.get("default_loop") in ids
    assert all(n.get("loop") in ids for n in committed["nodes"])
    assert all(e.get("loop") in ids for e in committed["edges"])


def test_the_refusals_are_carried(committed):
    blob = " ".join(committed["refusals"]).lower()
    assert "post /verdicts" in blob  # Constraint A
    assert "harness" in blob
    assert committed["engine_actor"] == "engine:judge-runner"


# ── Operational loops from manifests (loop-definition-model) ─────────────────


def test_a_manifest_loop_is_registered_and_drawn(committed):
    """An operational loop declared as a data manifest appears in the catalog
    AND contributes nodes/edges tagged with its id — the data path beside the
    code-defined SERE."""
    ids = {l["id"] for l in committed["loops"]}
    assert "news-scout" in ids, "the news-scout manifest is not in the loop catalog"
    assert [n for n in committed["nodes"] if n["loop"] == "news-scout"], \
        "news-scout is in the catalog but drew no nodes"
    assert any(e["loop"] == "news-scout" for e in committed["edges"])


def test_a_for_each_step_expands_to_one_node_per_item(committed):
    """Node parametrisation: a step declared ONCE with `for_each` is drawn as
    one node per param item — the property news-scout exists to exercise."""
    import yaml
    m = yaml.safe_load(
        (REPO / "files/anatomy/loops/news-scout.loop.yml").read_text(encoding="utf-8"))
    fe_steps = [s for s in m["steps"] if s.get("for_each")]
    assert fe_steps, "the fixture manifest must exercise at least one for_each step"
    for s in fe_steps:
        n_items = len(m["params"][s["for_each"]])
        drawn = [n for n in committed["nodes"]
                 if n["loop"] == m["id"]
                 and n["id"].startswith(f"step:{m['id']}:{s['id']}:")]
        assert len(drawn) == n_items, (
            f"step {s['id']} for_each {s['for_each']} has {n_items} items but "
            f"drew {len(drawn)} nodes — parametrisation is off")


def test_an_invalid_manifest_is_refused_at_generation(gen):
    """A manifest a runner could not execute is refused at GEN time, not left to
    fail a converge (loop-generator gate)."""
    with pytest.raises(ValueError):
        gen._validate_manifest({"id": "x"}, "bad.loop.yml")  # missing required keys
    with pytest.raises(ValueError):
        gen._validate_manifest(  # for_each names a param that isn't declared
            {"id": "x", "label": "l", "blurb": "b",
             "trigger": {"cadence": "* * * * *"},
             "steps": [{"id": "s", "runner": "tool", "for_each": "nope"}]},
            "bad.loop.yml")
    with pytest.raises(ValueError):
        gen._validate_manifest(  # `sere` is reserved for the code loop
            {"id": "sere", "label": "l", "blurb": "b",
             "trigger": {"cadence": "* * * * *"},
             "steps": [{"id": "s", "runner": "tool"}]},
            "bad.loop.yml")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
