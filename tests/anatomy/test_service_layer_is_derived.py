"""`layer` — derived from the edges, and refused where the edges are not there.

Plan: docs/idea/13-relations.md §R2
Doctrine: docs/doctrine/layers.md §3 (the four layers), §4.1 (repair before
declare), §5 (where the derivation will disagree with intuition).

WHAT R2 IS. `layer` answers one question — *if this stops, what else stops?* —
and the answer is longest path over the dependency edges, the same arithmetic
`files/anatomy/face/src/lib/anatomy/graphLayout.ts::rankNodes` already runs for
the canvas. It is emitted as a DERIVED fact by tools/anatomy-graph-gen.py and
must never be hand-written; layers.md §4.1 refuses a hand-written layer table
by name, because it would be a fifth place the same fact lives and the first
one nothing compares.

THE REFUSAL THIS FILE EXISTS TO PIN, and it is the difference between an
inventory and an answer. `layer` runs on EDGES, and a node nobody surveyed
contributes exactly what a measured root contributes: nothing. The arithmetic
answers anyway, and MEASURED with the refusal disabled it answers wrong in both
directions at once — `service:traefik` derives **L2**, "a leaf whose failure is
felt where it happens", about the process that binds 80/443 and is the only
edge proxy on Linux; `service:grafana`, equally unsurveyed but depended on by
mcp_gateway, derives **L0 substrate**. So the generator withholds `layer` from
any node whose own upstreams were never read and stamps a `layer_withheld`
reason in its place. 38 of 63 services are withheld today and that count is
published in `counts` rather than rounded to "done".

TWO DISAGREEMENTS WITH THE OPERATOR'S OWN §3 EXAMPLES, both expected, neither
tuned away — arguing with the arithmetic is how a derived field stops being
derived:

  * §3 lists **Infisical** under L1 platform. It derives **L2**: nothing in
    this estate declares a dependency on it. It is a leaf that holds secrets.
  * §3 lists **Wing** under L0 substrate. It derives **L1**: it has four
    upstreams of its own (bone, keap, prometheus, authentik), so it is not
    substrate — something is underneath it.

And the one §5 predicted in advance: **Nextcloud derives L2**, beside Jellyfin,
because it has no dependents. `layer` measures consequence, not stature.

Offline: reads the committed artifact and re-derives from the generator.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
GRAPH = REPO / "state" / "anatomy-graph.json"

LAYERS = ("L0", "L1", "L2", "L3")


@pytest.fixture(scope="module")
def committed() -> dict:
    return json.loads(GRAPH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def gen():
    spec = importlib.util.spec_from_file_location(
        "anatomy_graph_gen", REPO / "tools" / "anatomy-graph-gen.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def services(graph: dict) -> dict[str, dict]:
    return {k: v for k, v in graph["nodes"].items() if v.get("kind") == "service"}


# ── the field exists, and its absence is a state ──────────────────────────


def test_every_service_carries_a_layer_or_a_reason_it_has_none(committed):
    """No third option. A missing key would read as fine, which is the one
    thing an unmeasured value must never do."""
    for nid, n in sorted(services(committed).items()):
        assert "layer" in n, f"{nid} carries no `layer` key at all"
        if n["layer"] is None:
            assert n.get("layer_withheld"), (
                f"{nid} has layer: null and no `layer_withheld` reason — a null that "
                f"does not say why it is null is indistinguishable from a bug"
            )
            assert "layer_basis" not in n, f"{nid} withholds a layer but keeps its basis"
        else:
            assert n["layer"] in LAYERS, f"{nid} carries layer={n['layer']!r}"
            assert set(n.get("layer_basis") or {}) == {"height", "dependents", "upstreams"}


def test_the_census_is_published_including_the_part_that_is_missing(committed):
    c = committed["counts"]
    for layer in LAYERS:
        assert f"services_layer_{layer}" in c
    assert "services_layer_withheld" in c, (
        "the withheld count is the honest majority today — publishing L0/L1/L2 without "
        "it would present a 25-node inventory as if it covered 63"
    )
    total = sum(c[f"services_layer_{k}"] for k in LAYERS) + c["services_layer_withheld"]
    assert total == c["nodes_service"], (
        f"layer states cover {total} of {c['nodes_service']} services"
    )
    assert c["services_layer_withheld"] > 0, (
        "every service now carries a layer; if the survey really is complete, delete "
        "this assertion deliberately rather than letting a silent zero certify it"
    )
    assert committed.get("layer_basis"), (
        "the artifact must state the arithmetic it ran — a derived field whose "
        "derivation is only in a docstring is a hand-written one with extra steps"
    )


def test_no_unsurveyed_service_is_assigned_a_layer(committed):
    """THE refusal. An unsurveyed node has no edges because nobody looked for
    any, and longest-path answers from that emptiness: with this disabled,
    traefik derives L2 and grafana derives L0 — the same absence of evidence,
    opposite verdicts, both stated in the voice of a measurement."""
    for nid, n in sorted(services(committed).items()):
        if n.get("dependency_survey") != "declared":
            assert n["layer"] is None, (
                f"{nid} is {n.get('dependency_survey')} and still carries "
                f"layer={n['layer']!r} — derived from an absence of evidence"
            )


def test_traefik_is_the_named_ceiling_and_not_a_substrate_node(committed):
    """Named rather than hidden, because it is the biggest gap in the input and
    R2 must not be read as having closed it: reachability dependencies
    (Traefik) are not in the edge set at all."""
    traefik = committed["nodes"].get("service:traefik")
    assert traefik, "service:traefik vanished — the ceiling this gate names is gone"
    assert traefik["layer"] is None and traefik["dependency_survey"] == "not-surveyed", (
        "traefik now carries a layer — if its upstreams were surveyed, good; then this "
        "gate should assert the new value and the doctrine's ceiling paragraph should "
        "be rewritten in the same commit"
    )
    assert not [e for e in committed["edges"] if "traefik" in e["from"] + e["to"]], (
        "traefik gained edges — re-read docs/doctrine/layers.md §4's ceiling"
    )


# ── the arithmetic ────────────────────────────────────────────────────────


def test_a_leaf_is_l2_and_a_root_with_dependents_is_l0(committed):
    """§3's definitions, checked against every emitted value rather than
    against a list of names. L2 = "no dependents"; L0 = "nothing in the estate
    runs without it", i.e. something depends on it and nothing is underneath."""
    for nid, n in sorted(services(committed).items()):
        if n["layer"] is None:
            continue
        b = n["layer_basis"]
        if n["layer"] == "L2":
            assert b["dependents"] == 0 and b["height"] == 0, (nid, b)
        elif n["layer"] == "L0":
            assert b["dependents"] > 0 and b["upstreams"] == 0, (nid, b)
        elif n["layer"] == "L1":
            assert b["dependents"] > 0 and b["upstreams"] > 0, (nid, b)


def test_no_l3_is_emitted_because_it_is_not_this_axis(committed):
    """§3 defines L3 by DELIVERY — "small per-tenant apps, manifest-shipped" —
    which is a different axis leaking into this one. It is not derivable from
    dependency depth, the Tier-2 apps have no `service:` node, and emitting a
    guess would have made the census look complete. Zero, deliberately."""
    assert committed["counts"]["services_layer_L3"] == 0
    assert not [n for n in services(committed).values() if n["layer"] == "L3"]


def test_the_databases_are_l0_and_authentik_is_l1(committed):
    """The two verdicts the doctrine and the arithmetic agree on, pinned so a
    change to the projection that flips them is loud."""
    n = services(committed)
    for db in ("mariadb", "postgresql", "redis"):
        assert n[f"service:{db}"]["layer"] == "L0", db
    assert n["service:authentik"]["layer"] == "L1"
    assert n["service:authentik"]["layer_basis"]["dependents"] >= 30, (
        "Authentik's dependents collapsed — the SSO chain "
        "service:authentik → authentik:<slug> → service:<x> is how its blast radius "
        "reaches the arithmetic, and without it Authentik derives as a leaf"
    )


def test_gitea_is_not_substrate(committed):
    """Gitea declares `depends_on: []` and the first derivation therefore seated
    it in L0 beside PostgreSQL — "nothing in the estate runs without it" — while
    the same artifact carried `authentik:gitea → service:gitea` and
    roles/pazny.gitea/tasks/post.yml:117-137 guarded against the case its own
    failure message calls LOCKOUT. `[]` is now scoped to "no DATA upstream", and
    the auth upstream reaches the arithmetic through the Authentik chain."""
    gitea = committed["nodes"]["service:gitea"]
    assert gitea["layer"] == "L1", (
        f"gitea derives {gitea['layer']} — L0 would mean the estate cannot run without "
        f"it, and the estate's own SSO chain says something is underneath it"
    )
    assert gitea["layer_basis"]["upstreams"] >= 1


# ── the disagreements, recorded rather than smoothed ──────────────────────


def test_nextcloud_lands_l2_exactly_as_the_doctrine_predicted(committed):
    """layers.md §5 wrote this down BEFORE the derivation existed: "Nextcloud
    has no dependents in this estate. By consequence it is L2, beside Jellyfin
    — not L1, where it feels like it belongs because it is important and widely
    used." The prediction held. If a future edge gives it a dependent it will
    move, and that move will be the finding."""
    nc = committed["nodes"]["service:nextcloud"]
    assert nc["layer"] == "L2" and nc["layer_basis"]["dependents"] == 0
    assert nc["layer_basis"]["upstreams"] >= 4, (
        "Nextcloud consumes mariadb, onlyoffice, mailpit and Authentik — a leaf with "
        "four upstreams, which is exactly why stature and consequence are two fields"
    )


def test_the_two_doctrine_examples_the_derivation_contradicts(committed):
    """Not smoothed. §3's example lists are the operator's own reading, and the
    whole reason to derive is that a reading can be wrong.

    Infisical: §3 says L1 platform. Nothing in this estate declares a
    dependency on it, so it derives L2 — a leaf that happens to hold secrets.
    The honest counter-argument is that the ESTATE's services fetch from it at
    converge, which no plugin declares; that is an argument with the edges, and
    the correct repair is to declare them, not to overrule the arithmetic.

    Wing: §3 says L0 substrate. It has four upstreams, so something IS
    underneath it, and it derives L1.
    """
    n = services(committed)
    assert n["service:infisical"]["layer"] == "L2", (
        "infisical no longer contradicts §3 — if an edge to it was declared, say so in "
        "layers.md §3 and delete this half of the gate"
    )
    assert n["service:wing"]["layer"] == "L1"
    assert n["service:wing"]["layer_basis"]["upstreams"] >= 3


# ── derived, never declared ───────────────────────────────────────────────


def test_layer_is_absent_from_every_declaration_site(gen):
    """§4.1's refusal, mechanised: the moment `layer:` appears in a plugin
    manifest or the service registry, it has stopped being derived and the
    disagreement between declaration and derivation becomes unfindable."""
    for path in sorted(REPO.glob("files/anatomy/plugins/*/plugin.yml")):
        text = path.read_text(encoding="utf-8")
        assert "\nlayer:" not in text, (
            f"{path.relative_to(REPO)} declares `layer:` — it is derived by "
            f"tools/anatomy-graph-gen.py::derive_layers from the dependency edges"
        )
    assert "\n  layer:" not in (REPO / "state" / "manifest.yml").read_text(
        encoding="utf-8")


def test_the_derivation_reproduces_the_committed_artifact(gen, committed):
    """Regenerate-and-diff, restricted to the field this file owns, so a stale
    artifact reads as a layer defect here rather than only as a diff there."""
    fresh = gen.build()
    for nid, n in sorted(services(fresh).items()):
        assert n.get("layer") == committed["nodes"][nid].get("layer"), nid


def test_a_node_with_no_survey_is_withheld_even_when_it_has_dependents(gen):
    """The refusal is about the node's OWN survey, not about its popularity.

    Grafana is depended on by mcp_gateway and still carries no `depends_on` of
    its own, so its upstreams are unknown and L0-vs-L1 is unanswerable. A
    derivation that seated it in L0 would be reporting "nothing runs without
    Grafana" on the strength of nobody having read roles/pazny.grafana.
    """
    nodes = {
        "service:a": {"kind": "service", "dependency_survey": "not-surveyed"},
        "service:b": {"kind": "service", "dependency_survey": "declared"},
    }
    edges = [{"from": "service:a", "to": "service:b", "kind": "data"}]
    gen.derive_layers(nodes, edges)
    assert nodes["service:a"]["layer"] is None
    assert nodes["service:a"]["layer_withheld"]
    assert nodes["service:b"]["layer"] == "L2"
