"""Anatomy CI gate — the apex public projection and its ruling.

The public site at the apex is a projection of the internal anatomy
artifact through files/anatomy/apex/ruling.yml, and the ruling is an
ALLOW-LIST ON BOTH AXES: every field and every node the artifact carries
must be ruled, and everything defaults to WITHHELD. The gate this file
pins is deliberately not self-satisfying — the forbidden set is derived
from the INPUT artifact, so it cannot be met by editing the output, and
meeting it by editing the ruling is a visible edit to a signable file.

What is pinned, and why:

  1. The real artifact + ruling pass the gate (a broken ruling never
     ships silently), and the declared 6/9/57 split matches the table.
  2. Mutation, forward direction: a NEW artifact field/node halts the
     build — a generator commit is not a public-surface review.
  3. Mutation, reverse direction: a STALE ruling (field or node that no
     longer exists) halts too — the frozen published set may not rot.
  4. The leak check actually fires: an injected service name, node id,
     or withheld string value raises LeakError.
  5. The public document's shape is frozen — organs and atoms have NO
     `facts` member; tooltips can only inherit what does not exist.
  6. Counts are recomputed over the published set — corrupting the
     artifact's own `counts` changes nothing in the output.
  7. Byte determinism — building twice is identical, so no timestamp,
     no live state, no converge oracle can be hiding in the output.
  8. No click-through: the page links only to the operator's manifest
     site; no service, no subdomain, ever (operator ruling D2).
"""

from __future__ import annotations

import copy
import importlib.util
import json
import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
APEX = REPO / "files" / "anatomy" / "apex"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"apex_{name}", APEX / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


P = _load("projection")
R = _load("render")


@pytest.fixture(scope="module")
def artifact():
    return P.load_artifact()


@pytest.fixture(scope="module")
def ruling():
    return P.load_ruling()


# ---------------------------------------------------------------------------
# 1. the real inputs pass, and the ledger matches the table
# ---------------------------------------------------------------------------

def test_gate_passes_on_the_real_artifact(artifact, ruling):
    P.gate(artifact, ruling)


def test_declared_split_is_6_9_69(ruling):
    # The phase-1 ruling: 6 fields leave verbatim, 9 transformed, 57
    # withheld. Changing any of these numbers is a public-surface
    # decision and must touch the signable ruling AND this pin.
    # 2026-08-29: +12 withheld — the agent kind's fields (charter, tool
    # grants, backend binding, machine-identity scopes). Withheld-only, so
    # the published set is unchanged; the atoms pin below is the proof.
    assert ruling["splits"] == {"verbatim": 6, "transformed": 9, "withheld": 69}


def test_published_set_is_the_ruled_63_in_13(artifact, ruling):
    doc = P.project(artifact, ruling)
    assert doc["counts"] == {"organs": 13, "atoms": 63, "veins": 14}


# ---------------------------------------------------------------------------
# 2+3. mutation-verify the field gate, both directions
# ---------------------------------------------------------------------------

def test_new_node_field_halts_the_build(artifact, ruling):
    mutated = copy.deepcopy(artifact)
    next(iter(mutated["nodes"].values()))["zz_probe"] = "anything"
    with pytest.raises(P.GateError, match="zz_probe"):
        P.gate(mutated, ruling)


def test_new_edge_field_halts_the_build(artifact, ruling):
    mutated = copy.deepcopy(artifact)
    mutated["edges"][0]["zz_probe"] = "anything"
    with pytest.raises(P.GateError, match="zz_probe"):
        P.gate(mutated, ruling)


def test_new_top_level_field_halts_the_build(artifact, ruling):
    mutated = copy.deepcopy(artifact)
    mutated["zz_probe"] = {}
    with pytest.raises(P.GateError, match="zz_probe"):
        P.gate(mutated, ruling)


def test_stale_field_ruling_halts_the_build(artifact, ruling):
    mutated = copy.deepcopy(artifact)
    for edge in mutated["edges"]:
        edge.pop("can_invert", None)
    with pytest.raises(P.GateError, match="STALE"):
        P.gate(mutated, ruling)


def test_new_node_halts_the_build(artifact, ruling):
    mutated = copy.deepcopy(artifact)
    mutated["nodes"]["service:zz_new"] = {"kind": "service", "source": "x",
                                          "anchor": "0", "description": "x"}
    with pytest.raises(P.GateError, match="UNRULED node"):
        P.gate(mutated, ruling)


def test_vanished_ruled_node_halts_the_build(artifact, ruling):
    mutated = copy.deepcopy(artifact)
    del mutated["nodes"]["table:apps"]
    with pytest.raises(P.GateError, match="no longer in the artifact"):
        P.gate(mutated, ruling)


def test_amnesty_may_never_cover_a_service_name(artifact, ruling):
    mutated = copy.deepcopy(ruling)
    mutated["vocabulary_amnesty"].append({"term": "keap"})
    with pytest.raises(P.GateError, match="service name"):
        P.gate(artifact, mutated)


# ---------------------------------------------------------------------------
# 4. the leak check fires on real violations
# ---------------------------------------------------------------------------

def _built_page(artifact, ruling):
    doc = json.loads(P.public_json(artifact, ruling))
    seed = f"{ruling['ruling']}:{ruling['version']}"
    return R.page_html(doc, seed)


def test_injected_service_mark_is_caught(artifact, ruling):
    html = _built_page(artifact, ruling)
    with pytest.raises(P.LeakError):
        P.leak_check(html + "\n<p>powered by Traefik</p>", artifact, ruling)


def test_injected_node_id_is_caught(artifact, ruling):
    html = _built_page(artifact, ruling)
    with pytest.raises(P.LeakError):
        P.leak_check(html + "\n<!-- pulse:gitleaks:nightly-scan -->", artifact, ruling)


def test_injected_withheld_value_is_caught(artifact, ruling):
    # a real `via` value from the artifact must never survive in output
    via = next(
        s for e in artifact["edges"] for s in P._iter_strings(e.get("via"))
        if P._harvestable(s)
    )
    html = _built_page(artifact, ruling)
    with pytest.raises(P.LeakError):
        P.leak_check(html + "\n" + via, artifact, ruling)


def test_the_shipped_surfaces_are_clean(artifact, ruling):
    P.leak_check(P.public_json(artifact, ruling), artifact, ruling)
    P.leak_check(_built_page(artifact, ruling), artifact, ruling)
    P.leak_check((APEX / "assets" / "ait.css").read_text(), artifact, ruling)


# ---------------------------------------------------------------------------
# 5. the public shape is frozen — nothing to inherit
# ---------------------------------------------------------------------------

def test_public_document_shape_is_frozen(artifact, ruling):
    doc = P.project(artifact, ruling)
    assert set(doc) == {"schema", "version", "counts", "organs", "veins"}
    for organ in doc["organs"]:
        assert set(organ) == {"id", "title", "tells", "limb", "order", "atoms"}
        for atom in organ["atoms"]:
            assert set(atom) == {"speaks"}   # no `facts`, no id, nothing else
    for vein in doc["veins"]:
        assert set(vein) == {"between", "kind"}


# ---------------------------------------------------------------------------
# 6. counts are recomputed, never copied
# ---------------------------------------------------------------------------

def test_artifact_counts_do_not_reach_the_output(artifact, ruling):
    mutated = copy.deepcopy(artifact)
    mutated["counts"] = {k: 99999 for k in mutated["counts"]}
    assert P.public_json(mutated, ruling) == P.public_json(artifact, ruling)


# ---------------------------------------------------------------------------
# 7. determinism — no clock, no live state, no converge oracle
# ---------------------------------------------------------------------------

def test_output_is_byte_deterministic(artifact, ruling):
    assert P.public_json(artifact, ruling) == P.public_json(artifact, ruling)
    doc = json.loads(P.public_json(artifact, ruling))
    seed = f"{ruling['ruling']}:{ruling['version']}"
    assert R.page_html(doc, seed) == R.page_html(doc, seed)


# ---------------------------------------------------------------------------
# 8. no click-through (operator ruling D2)
# ---------------------------------------------------------------------------

def test_page_links_only_to_the_manifest(artifact, ruling):
    html = _built_page(artifact, ruling)
    hrefs = set(re.findall(r'href="([^"]+)"', html))
    allowed = {"https://thisisait.eu", "assets/ait.css"}
    assert hrefs <= allowed | {h for h in hrefs if h.startswith("#")}, hrefs
