"""The anatomy graph's refusals — what a declared edge is not allowed to be.

The graph (state/anatomy-graph.json, compiled by tools/anatomy-graph-gen.py
from the pulse manifests + judge-sets + weaknesses reader + state/manifest.yml
+ launchd labels) exists to make the estate's implicit wiring declared. A
declaration layer earns its keep only if it cannot lie, so this gate holds the
refusals from docs/archive/nos-anatomy-graph.md §2(c):

  1. dangling edge      — `upstream:` must resolve against the compiled node set
  2. per-kind cycle     — no cycle through data/trigger/temporal alone; a
                          union-kind cycle is a WARNING (a real feedback loop
                          crosses a night boundary — the corpus-diff halt)
  3. temporal staleness — a temporal edge whose recorded `schedules` no longer
                          match the jobs' cron expressions is an incomplete
                          edit; margin_min is mandatory (offline schedule-hash
                          check, deliberately NOT wall-clock — "14 days old"
                          decays into the drift-baseline lie fixed 2026-07-28)
  4. pairwise mutex     — refused as a declaration; `claims:` on the node,
                          pairs derived (N claimants need N(N-1)/2 edges to
                          stay truthful and nobody maintains triangle counts)
  5. artifact-less data — a data edge with no `via:` is schedule adjacency
                          with better clothes
  6. findings ambiguity — `expects: succeeded` at an upstream that declares
                          findings_exit_codes must say whether findings
                          satisfy it (gitleaks exits 1 ON SUCCESS with
                          findings; a consumer must not read that as failure)

Plus the two meta-rules:
  * regenerate-and-diff — the committed JSON must equal a fresh build()
  * repair before declare — the halt trigger edge may exist ONLY while
    cortex-fs-sync.py actually reads the ledger flag (commit 97abdb7c). An
    edge describing wiring the code stopped performing is the estate's
    signature sin, and it is the one class the compiler cannot catch.

Offline-safe: no wing.db, no network. Same source walk as
test_every_job_declares_what_it_is.py.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
GRAPH = REPO / "state" / "anatomy-graph.json"


def _gen():
    spec = importlib.util.spec_from_file_location(
        "anatomy_graph_gen", REPO / "tools" / "anatomy-graph-gen.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def gen():
    return _gen()


@pytest.fixture(scope="module")
def committed() -> dict:
    assert GRAPH.exists(), (
        "state/anatomy-graph.json is missing — the manifests declare edges "
        "that were never compiled; run tools/anatomy-graph-gen.py"
    )
    return json.loads(GRAPH.read_text(encoding="utf-8"))


# ── meta-rule: regenerate-and-diff ────────────────────────────────────────


def test_the_committed_graph_matches_a_fresh_build(gen, committed):
    fresh = gen.render(gen.build())
    assert fresh == GRAPH.read_text(encoding="utf-8"), (
        "state/anatomy-graph.json is stale against the manifests — "
        "run tools/anatomy-graph-gen.py (regenerate-and-diff, the estate's "
        "fourth instance of this pattern)"
    )


def test_the_graph_is_byte_stable(gen):
    """Two builds must agree exactly — a nondeterministic artifact churns
    every commit and trains people to rubber-stamp its diffs."""
    assert gen.render(gen.build()) == gen.render(gen.build())


# ── refusal 1: dangling edge ──────────────────────────────────────────────


def _one_edge_nodes(gen):
    return {
        "pulse:a:up": {"kind": "pulse", "schedule": "0 4 * * *",
                       "jitter_min": 0, "max_runtime_s": 60,
                       "paused": False, "claims": [], "findings_exit_codes": None},
        "pulse:a:down": {"kind": "pulse", "schedule": "30 4 * * *",
                         "jitter_min": 0, "max_runtime_s": 60,
                         "paused": False, "claims": [], "findings_exit_codes": None},
    }


def test_a_dangling_upstream_is_refused(gen):
    nodes = _one_edge_nodes(gen)
    raw = [("pulse:a:down",
            {"upstream": "pulse:a:typod-name", "kind": "data", "via": "x"}, "src")]
    with pytest.raises(SystemExit):
        gen.compile_declared(raw, nodes)


# ── refusal 2: per-kind cycle ─────────────────────────────────────────────


def test_a_data_cycle_is_found(gen):
    edges = [{"from": "a", "to": "b", "kind": "data"},
             {"from": "b", "to": "a", "kind": "data"}]
    assert gen.find_cycle(edges, {"data"}) is not None


def test_the_live_graph_has_no_per_kind_cycle(gen, committed):
    for kind in ("data", "trigger", "temporal"):
        assert gen.find_cycle(committed["edges"], {kind}) is None, (
            f"cycle through {kind} edges in the committed graph"
        )


def test_the_halt_feedback_loop_is_a_warning_not_a_refusal(committed):
    """The corpus-diff halt closes a loop ACROSS kinds (data forward, trigger
    back). That is a real feedback loop crossing a night boundary — reviewed,
    not refused — and the graph must say so out loud."""
    assert any("union-kind cycle" in w for w in committed["warnings"]), (
        "the halt loop vanished from warnings — either the halt edge was "
        "deleted (see repair-before-declare below) or the warning path broke"
    )


# ── refusal 3: temporal staleness ─────────────────────────────────────────


def test_a_temporal_edge_without_margin_is_refused(gen):
    nodes = _one_edge_nodes(gen)
    raw = [("pulse:a:down",
            {"upstream": "pulse:a:up", "kind": "temporal",
             "schedules": ["0 4 * * *", "30 4 * * *"]}, "src")]
    with pytest.raises(SystemExit):
        gen.compile_declared(raw, nodes)


def test_a_schedule_change_without_remeasure_is_refused(gen):
    """The exact failure the chain lives one jitter_min away from: someone
    moves a cron minute and the recorded margin silently describes a spacing
    that no longer exists."""
    nodes = _one_edge_nodes(gen)
    nodes["pulse:a:up"]["schedule"] = "15 4 * * *"   # moved after measurement
    raw = [("pulse:a:down",
            {"upstream": "pulse:a:up", "kind": "temporal", "margin_min": 10.0,
             "schedules": ["0 4 * * *", "30 4 * * *"]}, "src")]
    with pytest.raises(SystemExit):
        gen.compile_declared(raw, nodes)


def test_every_committed_temporal_edge_is_stamped(committed):
    for e in committed["edges"]:
        if e["kind"] != "temporal":
            continue
        assert e.get("margin_min") is not None, f"{e['from']} -> {e['to']}: no margin"
        assert e.get("schedules"), f"{e['from']} -> {e['to']}: no schedule pair"
        assert e.get("measured"), f"{e['from']} -> {e['to']}: nobody measured this"


# ── refusal 4: pairwise mutex ─────────────────────────────────────────────


def test_a_declared_mutex_edge_is_refused(gen):
    nodes = _one_edge_nodes(gen)
    raw = [("pulse:a:down",
            {"upstream": "pulse:a:up", "kind": "mutex"}, "src")]
    with pytest.raises(SystemExit):
        gen.compile_declared(raw, nodes)


def test_mutex_pairs_are_derived_from_claims(committed):
    """Eleven claude-spawning jobs share one lock (agent-run-lock.sh, commit
    ba7a9471) and two judges share nos_entity. The pairs must exist and every
    one must be derived, never declared."""
    mutex = [e for e in committed["edges"] if e["kind"] == "mutex"]
    assert mutex, "no mutex pairs derived — the claims harvest broke"
    assert all(e.get("derived") == "claims" for e in mutex)
    resources = {e["resource"] for e in mutex}
    assert "agent-run-lock" in resources
    assert "nos_entity" in resources


# ── refusal 5: artifact-less data edge ────────────────────────────────────


def test_a_data_edge_without_an_artifact_is_refused(gen):
    nodes = _one_edge_nodes(gen)
    raw = [("pulse:a:down",
            {"upstream": "pulse:a:up", "kind": "data", "via": "  "}, "src")]
    with pytest.raises(SystemExit):
        gen.compile_declared(raw, nodes)


# ── refusal 6: findings ambiguity ─────────────────────────────────────────


def test_findings_semantics_must_be_named_by_the_edge(gen):
    nodes = _one_edge_nodes(gen)
    nodes["pulse:a:up"]["findings_exit_codes"] = [1]
    raw = [("pulse:a:down",
            {"upstream": "pulse:a:up", "kind": "data", "via": "x",
             "expects": "succeeded"}, "src")]
    with pytest.raises(SystemExit):
        gen.compile_declared(raw, nodes)
    raw[0][1]["on_findings"] = "proceed"
    edges = gen.compile_declared(raw, nodes)
    assert edges[0]["on_findings"] == "proceed"


# ── the YAML 1.1 trap the survey's own field name walked into ─────────────


def test_the_on_key_trap_is_refused(gen):
    """yaml.safe_load('on: x') == {True: 'x'} — a bare `on:` key is boolean
    True in YAML 1.1. An edge authored with the survey's spelling would
    compile with a silently absent upstream; refuse it by name instead."""
    nodes = _one_edge_nodes(gen)
    raw = [("pulse:a:down", {True: "pulse:a:up", "kind": "data", "via": "x"}, "src")]
    with pytest.raises(SystemExit):
        gen.compile_declared(raw, nodes)


# ── positive controls: the nightly chain is actually declared ─────────────


def _edge_set(committed, kind):
    return {(e["from"], e["to"]) for e in committed["edges"] if e["kind"] == kind}


def test_the_nightly_chain_is_declared(committed):
    data = _edge_set(committed, "data")
    for pair in [
        ("pulse:keap:keap-consolidate", "pulse:cortex:cortex-fs-sync"),
        ("pulse:cortex:cortex-fs-sync", "pulse:keap:keap-embed-sync"),
        ("pulse:keap:keap-embed-sync", "pulse:keap:keap-features-sync"),
        ("pulse:keap:keap-embed-sync", "pulse:keap:keap-lint"),
        ("pulse:keap:keap-embed-sync", "pulse:cortex:cortex-corpus-diff"),
    ]:
        assert pair in data, f"nightly chain data edge missing: {pair}"
    assert len(_edge_set(committed, "temporal")) >= 5, (
        "the five measured temporal edges (survey §1.4) are not all declared"
    )


def test_the_temporal_debt_is_computed_and_honest(committed):
    """§1.4 col 4: four of the five chain edges are PERMITTED to invert by
    their own declared budgets. The graph must carry that fact — it is the
    definition screen's temporal-debt panel and the reason the margins tool
    exists. If schedules or budgets change, regeneration recomputes this;
    if the count drops below 3 something widened silently — re-measure."""
    temporal = [e for e in committed["edges"] if e["kind"] == "temporal"]
    assert all("can_invert" in e and "declared_margin_min" in e for e in temporal)
    invertible = [e for e in temporal if e["can_invert"]]
    assert len(invertible) >= 3, (
        f"only {len(invertible)} temporal edges are flagged invertible — the "
        f"debt computation changed; verify against the manifests' budgets"
    )


# ── repair before declare: the halt edge exists only while the code does ──


def test_the_halt_edge_is_backed_by_code(committed):
    trigger = _edge_set(committed, "trigger")
    assert ("pulse:cortex:cortex-corpus-diff", "pulse:cortex:cortex-fs-sync") in trigger, (
        "the halt trigger edge is gone from the graph — if the halt was "
        "unwired, delete this test WITH the wiring's gate "
        "(test_the_halt_can_actually_halt.py), not before it"
    )
    fs_sync = (REPO / "files/anatomy/scripts/cortex-fs-sync.py").read_text(encoding="utf-8")
    for needle in ("halted", "--clear-halt"):
        assert needle in fs_sync, (
            f"cortex-fs-sync.py no longer contains {needle!r} — the declared "
            f"halt edge describes wiring the code stopped performing, which is "
            f"the exact sin the graph exists to end (repair before declare)"
        )


# ── address space ─────────────────────────────────────────────────────────


def test_every_edge_endpoint_resolves(committed):
    nodes = committed["nodes"]
    for e in committed["edges"]:
        assert e["from"] in nodes, f"edge from unknown node {e['from']}"
        assert e["to"] in nodes, f"edge to unknown node {e['to']}"


def test_the_node_counts_are_sane(committed):
    """Positive control with measured floors (2026-08-06: 29 pulse jobs,
    5 judges, 4 gate sets, 7 weakness sources, 12 declared daemon labels,
    63 services). Floors, not equalities — the estate grows."""
    c = committed["counts"]
    assert c["nodes_pulse"] >= 25
    assert c["nodes_judge"] >= 5
    assert c["nodes_gateset"] >= 4
    assert c["nodes_weakness"] >= 7
    assert c["nodes_daemon"] >= 11
    assert c["nodes_service"] >= 60
