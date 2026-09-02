"""Anatomy CI gate — one field answers "how do I know this edge is true".

MEASURED 2026-09-02, while reading Graphify (Apache-2.0) for ideas. The graph
carried TWO provenance vocabularies and no universal field:

    236 edges   derived: <generator>
     50 edges   measured: <date>  +  declared: <verb>

A consumer asking the one question that matters had to know both spellings, and
nothing refused an edge carrying neither. That is the estate's recurring defect —
two representations of one fact — the same shape as the two ISO-8601 spellings
that made the CVE drift hook print nothing for months at exit 0.

The distinction is kept rather than flattened, because it predicts different
failure:

    derived    recomputed from a declaration every run; CANNOT go stale
    measured   a human read the code on a date; rots when that code moves,
               and nothing noticed until tools/graph-report.py asked git

Graphify's own third tier (AMBIGUOUS) is deliberately NOT minted here. It would
have exactly zero members, which is the defect this gate exists to prevent — the
cortex ontology already carries `status`/`source` fields whose 442 rows all say
`confirmed`/`manual`. A tier with no members is decoration.
"""

from __future__ import annotations

import collections
import json
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]
GRAPH = REPO / "state" / "anatomy-graph.json"
GEN = REPO / "tools" / "anatomy-graph-gen.py"


def _edges() -> list[dict]:
    return json.loads(GRAPH.read_text(encoding="utf-8"))["edges"]


def test_every_edge_carries_evidence():
    missing = [f'{e["from"]} -{e["kind"]}-> {e["to"]}'
               for e in _edges() if not e.get("evidence")]
    assert not missing, (
        f"{len(missing)} edge(s) do not say how they are known. An edge with no "
        "provenance is a claim with no evidence:\n  " + "\n  ".join(missing[:10]))


def test_the_generator_refuses_an_unattested_edge():
    """The artifact being clean is not the same as the compiler enforcing it.
    Without the refusal the next hand-added edge lands unattested and green."""
    src = "\n".join(ln for ln in GEN.read_text(encoding="utf-8").splitlines()
                    if not ln.lstrip().startswith("#"))
    assert 'e["evidence"] = (' in src, (
        "the generator no longer stamps `evidence` on every edge")
    assert "orphans" in src and "_die(" in src, (
        "the generator computes evidence but does not REFUSE an edge that has "
        "neither derived: nor measured:. A field nothing enforces drifts to "
        "optional on the first edge somebody adds by hand")


def test_both_values_have_members():
    """The rule this gate is named for. `evidence` must describe a real split,
    not a vocabulary — the cortex ontology's `status`/`source` fields have 442
    rows and one value each, which is what decoration looks like."""
    seen = collections.Counter(e.get("evidence") for e in _edges())
    assert set(seen) >= {"derived", "measured"}, (
        f"evidence has values {sorted(seen)}. With one value it distinguishes "
        "nothing and every consumer can ignore it")
    for value, n in seen.items():
        assert n > 0, f"{value} has no members"
