"""56 pairwise lines between things that are not connected to each other.

THE MUTEX LAYER'S PROBLEM. `state/anatomy-graph.json` holds **56 mutex edges**
over **5 resource nodes**. A mutex edge says "A and B may never run at once",
which is true — but it is not a relationship between A and B. It is a
consequence of both claiming the same thing. Drawn literally, five shared
claims become fifty-six lines criss-crossing the canvas between jobs that have
nothing to do with one another, and the layer reads as noise.

The projection has known this since it was written: `mutexSpokes()` derives
claim→resource spokes. The CANVAS did not — it drew a resource as the same
150×24 rectangle as every service and every job, so the one node kind that
constrains WHEN OTHER THINGS MAY RUN looked exactly like the things it
constrains.

WHAT THIS GATE HOLDS, and the second half is the part that makes the first
honest:

  1. a resource renders as its own shape, not as another rectangle;
  2. the collapse is REVERSIBLE — every claimant is listed in the inspector.

Collapsing 56 into 5 is a summary. A summary you cannot expand is a claim that
the detail did not matter, and this repository has spent two days closing
exactly that shape: the denominator has to stay reachable.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
GRAPH = REPO / "state/anatomy-graph.json"
VIEW = REPO / "files/anatomy/face/src/lib/apps/native/anatomy/GraphView.svelte"
PROJECTION = REPO / "files/anatomy/face/src/lib/anatomy/graph.ts"


def _graph() -> dict:
    return json.loads(GRAPH.read_text(encoding="utf-8"))


def test_the_collapse_is_worth_making():
    """Guard the premise. If the artifact ever had as many resources as mutex
    edges, the hexagon would be ceremony rather than a simplification, and this
    gate should be re-derived instead of defended."""
    g = _graph()
    resources = [n for n in g["nodes"] if n.startswith("resource:")]
    mutex = [e for e in g["edges"] if e.get("kind") == "mutex"]
    assert resources, "no resource nodes — the mutex layer has no claims to collapse to"
    assert len(mutex) > 2 * len(resources), (
        f"{len(mutex)} mutex edges over {len(resources)} resources — the "
        f"pairwise form is no longer the thing worth collapsing"
    )


def test_a_resource_is_not_drawn_as_another_rectangle():
    src = VIEW.read_text(encoding="utf-8")
    assert "n.kind === 'resource'" in src, (
        "the canvas no longer distinguishes a resource node, so a claim renders "
        "identically to the jobs it constrains"
    )
    assert "HEX_PATH" in src and "class=\"hex\"" in src, (
        "the resource branch no longer draws its own shape"
    )
    assert "claimantCount" in src, (
        "the hexagon does not say how many claimants it stands for — a "
        "collapsed shape without its count is a picture with no denominator"
    )


def test_the_collapse_can_be_expanded():
    """The inspector must list every claimant of the selected resource."""
    src = VIEW.read_text(encoding="utf-8")
    block = src[src.find("selected.kind === 'resource'"):]
    block = block[:1400]
    assert block, "the inspector has no resource branch"
    assert "spokes.filter" in block, (
        "the inspector does not enumerate the claimants, so the 56→5 collapse "
        "hides what it collapsed"
    )
    assert "claimed by" in block


def test_the_law_is_quoted_where_it_binds():
    """`governingParagraphs` was computed and never rendered. A rule an operator
    cannot read at the node it governs is a rule they will not read."""
    src = VIEW.read_text(encoding="utf-8")
    assert "governingParagraphs(graph" in src, (
        "the inspector no longer resolves the doctrine that governs a node"
    )
    assert "lawcard" in src, "the governing paragraphs render with no shape of their own"
    assert "law.heading" in src, (
        "only the section NUMBER is rendered. A bare number tells an operator "
        "nothing at 03:00 — 'docs/idea/11-agentic-loop-contract.md §2.4' means "
        "something only because the heading behind it says 'Fail closed: "
        "absence is never success'. The heading is the half that carries "
        "meaning, and it is what makes the citation checkable."
    )


def test_the_projection_still_exports_what_the_view_consumes():
    """Positive control: a view that imports a function the projection dropped
    fails at build, not here — but a projection that quietly stopped deriving
    spokes would leave the hexagon standing over an empty count."""
    ts = PROJECTION.read_text(encoding="utf-8")
    for symbol in ("export function mutexSpokes", "export function governingParagraphs"):
        assert symbol in ts, f"graph.ts no longer provides {symbol.split()[-1]}"
