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


def test_the_refusals_are_carried(committed):
    blob = " ".join(committed["refusals"]).lower()
    assert "post /verdicts" in blob  # Constraint A
    assert "harness" in blob
    assert committed["engine_actor"] == "engine:judge-runner"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
