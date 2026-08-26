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


def test_the_face_vendored_copy_is_identical(committed):
    """The face container's build context is files/anatomy/face/ ONLY
    (roles/pazny.face synchronize), so the definition screen imports a
    vendored copy. Two copies of one artifact are tolerable exactly as long
    as a gate makes divergence impossible."""
    face = REPO / "files/anatomy/face/src/lib/anatomy/anatomy-graph.json"
    assert face.exists(), "the face vendored graph copy is missing"
    assert face.read_text(encoding="utf-8") == GRAPH.read_text(encoding="utf-8")


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
    ba7a9471). The pairs must exist and every one must be derived, never
    declared. `nos_entity` is deliberately ABSENT since 2026-08-20: the judges'
    machine-wide mutex was retired (per-set sandboxes isolate the file, and the
    lock starved the engine's own gates — test_the_engine_judges_its_own_gates
    owns that claim); a mutex edge reappearing for it means someone re-declared
    the resource without re-proving the recursion safe."""
    mutex = [e for e in committed["edges"] if e["kind"] == "mutex"]
    assert mutex, "no mutex pairs derived — the claims harvest broke"
    assert all(e.get("derived") == "claims" for e in mutex)
    resources = {e["resource"] for e in mutex}
    assert "agent-run-lock" in resources
    assert "nos_entity" not in resources


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
    63 services; core-substrate extension same day: 4 repo surfaces, 1 tofu
    state root, 43 authentik registry rows, 6 KEAP tables — no `ideas`
    table exists, the operator brief's mention of one was stale). Floors,
    not equalities — the estate grows."""
    c = committed["counts"]
    assert c["nodes_pulse"] >= 25
    assert c["nodes_judge"] >= 5
    assert c["nodes_gateset"] >= 4
    assert c["nodes_weakness"] >= 7
    assert c["nodes_daemon"] >= 11
    assert c["nodes_service"] >= 60
    assert c["nodes_repo"] >= 4
    assert c["nodes_tofu"] >= 1
    assert c["nodes_authentik"] >= 40
    assert c["nodes_table"] >= 6
    assert c["nodes_doctrine"] >= 10
    # face apps (2026-08-07): 4 views + 1 widget from the face's own registry.
    # Frames are deliberately NOT nodes — a hub service already has a
    # `service:` address and a second one would be padding.
    assert c["nodes_faceapp"] >= 5
    assert c["edges_governed_by"] >= 15


def test_the_face_app_harvest_dies_rather_than_emitting_nothing(gen, monkeypatch, tmp_path):
    """Repair before declare, harvest edition. If the registry is refactored
    past the parse, the compiler must FAIL — a silent zero would delete five
    nodes and three edges from the address space and nothing would say so."""
    empty = tmp_path / "registry.ts"
    empty.write_text("export const nothing = 1;\n", encoding="utf-8")
    monkeypatch.setattr(gen, "FACE_REGISTRY", empty)
    with pytest.raises(SystemExit):
        gen.harvest_faceapps({})


# ── the constitution layer: governed_by edges, per-block attribution ──────


def test_governed_by_edges_point_at_real_paragraphs(committed):
    gb = [e for e in committed["edges"] if e["kind"] == "governed_by"]
    assert gb, "the doctrine layer produced no edges — derive_doctrine broke"
    for e in gb:
        target = committed["nodes"][e["to"]]
        assert target["kind"] == "doctrine", f"{e['to']} is not a doctrine node"
        assert e.get("via", "").startswith("cited at "), (
            f"{e['from']} -> {e['to']}: a governed_by edge must name the "
            f"citing line — the citation IS the evidence"
        )
        assert e.get("citations", 0) >= 1


def test_attribution_is_per_block_not_per_file(committed):
    """The measured case: M7 (the nos_entity collision) is cited inside
    genome-codegen's block and NOWHERE in ansible-lint's — a file-level smear
    would hand all five judges every paragraph, which is picture-filling.
    And the comment-above-the-key convention: DECISION 2e sits ABOVE
    cortex-corpus-diff's key (judge-sets.yml:194) and belongs to it — the
    naive ranges handed it to nos-smoke."""
    gb = {(e["from"], e["to"].split("#")[1])
          for e in committed["edges"] if e["kind"] == "governed_by"}
    froms_of = {k: {t for f, t in gb if f == k} for k, _ in gb}
    assert ("judge:genome-codegen", "M7") in gb
    assert "M7" not in froms_of.get("judge:ansible-lint", set())
    assert ("judge:cortex-corpus-diff", "DECISION-2e") in gb


def test_doctrine_nodes_carry_the_paragraph(committed):
    for nid, n in committed["nodes"].items():
        if n["kind"] != "doctrine":
            continue
        assert n["source"].endswith(".md"), f"{nid}: source is not a document"
        assert n.get("section"), f"{nid}: no section key"
        # heading may legitimately be empty only for table-row addresses
        assert "Constitution paragraph" in n["description"]


# ── KEAP-import shaping: anchor + body per node ───────────────────────────
#    (2026-08-06: an unanchored KEAP object is an `orphan-object` — measured:
#    keap-lint reported 26/27 fixture findings as exactly that — and a body of
#    `{"kind": "daemon"}` gives hybrid search nothing to embed. The anchor is
#    a REFERENCE, and a dangling reference is already refusal class 1.)


def test_every_node_has_a_resolving_anchor_and_a_body(committed):
    bundle = json.loads(
        (REPO / "state/fable/taxonomy-bundle.json").read_text(encoding="utf-8"))
    valid = {a["id"] for a in bundle["anchor"]}
    assert len(valid) >= 300, "the taxonomy bundle shrank — re-check before trusting it"
    for nid, n in committed["nodes"].items():
        assert n.get("anchor") in valid, (
            f"{nid}: anchor {n.get('anchor')!r} resolves to no taxonomy anchor — "
            f"an import would file this node as orphan-object, invisible to "
            f"KEAP search and panels"
        )
        desc = str(n.get("description") or "").strip()
        assert len(desc) >= 20, (
            f"{nid}: description {desc!r} is not a body worth embedding — "
            f"semantic scoping over it returns noise"
        )
        assert "\n" not in desc, f"{nid}: description must be one line"


def test_kind_prefixed_ids_survive(committed):
    """cortex-corpus-diff.py classifies any object id NOT starting with `fs:`
    as not-a-mirror-row and withdraws it from the fs clause — so kind-prefixed
    ids are what keeps an anatomy import from zeroing the agree-streak. Bare
    ids would have. This pins the property the import depends on."""
    for nid in committed["nodes"]:
        kind, _, rest = nid.partition(":")
        assert kind and rest and not kind.startswith("fs"), nid
        assert kind == committed["nodes"][nid]["kind"]


# ── the writes channel: actor-declared outputs, same refusals ─────────────


def test_a_dangling_writes_target_is_refused(gen):
    nodes = _one_edge_nodes(gen)
    raw = [("pulse:a:up", {"target": "table:typod", "via": "x",
                           "measured": "2026-08-06"}, "src")]
    with pytest.raises(SystemExit):
        gen.compile_writes(raw, nodes)


def test_a_writes_edge_without_an_artifact_is_refused(gen):
    nodes = _one_edge_nodes(gen)
    nodes["table:t"] = {"kind": "table"}
    raw = [("pulse:a:up", {"target": "table:t", "via": "  ",
                           "measured": "2026-08-06"}, "src")]
    with pytest.raises(SystemExit):
        gen.compile_writes(raw, nodes)


def test_an_unmeasured_writes_edge_is_refused(gen):
    nodes = _one_edge_nodes(gen)
    nodes["table:t"] = {"kind": "table"}
    raw = [("pulse:a:up", {"target": "table:t", "via": "x"}, "src")]
    with pytest.raises(SystemExit):
        gen.compile_writes(raw, nodes)


# ── core-substrate positive controls, each with its code pin ──────────────
#    (repair before declare: every declared write/read edge below is paired
#    with an assertion that the code still performs the wiring the edge
#    describes — the halt-edge rule, applied to the 2026-08-06 extension)


def _data_edges(committed):
    return {(e["from"], e["to"]) for e in committed["edges"] if e["kind"] == "data"}


def test_scan_data_write_edge_is_backed_by_code(committed):
    assert ("pulse:conductor:scan-state-record", "repo:scan-data") in _data_edges(committed)
    tool = (REPO / "tools" / "scan-state-snapshot.py").read_text(encoding="utf-8")
    assert 'BRANCH = "scan-data"' in tool, (
        "scan-state-snapshot.py no longer targets the scan-data branch — the "
        "declared write edge describes wiring the code stopped performing"
    )
    # The edge says the ref move is LOCAL. That is true only while the job
    # passes no --push: the manifest's job entry must carry no args.
    import yaml
    doc = yaml.safe_load(
        (REPO / "files/anatomy/agents/conductor.yml").read_text(encoding="utf-8"))
    job = next(j for j in doc["pulse"]["jobs"] if j["name"] == "scan-state-record")
    assert not job.get("args"), (
        "scan-state-record now passes args — if one of them is --push, the "
        "edge's 'local ref only' claim and repo:github-origin's empty "
        "automated_writers list are both stale; re-measure and restamp"
    )


def test_roadmap_write_edge_is_backed_by_code(committed):
    assert ("pulse:discovery:contradiction-scan", "table:roadmap") in _data_edges(committed)
    import yaml
    doc = yaml.safe_load(
        (REPO / "files/anatomy/plugins/discovery/plugin.yml").read_text(encoding="utf-8"))
    job = next(j for j in doc["pulse"]["jobs"] if j["name"] == "contradiction-scan")
    assert "--file" in (job.get("args") or []), (
        "contradiction-scan no longer passes --file — report-only mode files "
        "no rows, so the declared roadmap write edge is a lie; delete the "
        "edge or restore the flag"
    )
    # The tool and the roadmap seeder must still address the SAME table.
    scan = (REPO / "tools" / "discovery-scan.py").read_text(encoding="utf-8")
    seed = (REPO / "tools" / "roadmap-seed.py").read_text(encoding="utf-8")
    import re as _re
    t_scan = _re.search(r'TABLE = "([0-9a-f-]+)"', scan)
    t_seed = _re.search(r'TABLE = "([0-9a-f-]+)"', seed)
    assert t_scan and t_seed and t_scan.group(1) == t_seed.group(1), (
        "discovery-scan.py and roadmap-seed.py address different table uuids — "
        "the 'table:roadmap' target no longer names where the rows go"
    )


def test_forge_write_edge_left_with_its_agent(committed):
    """Until 2026-08-26 this pinned the promote-migration → gitlab-forge
    write edge against the flat profile's migration-pr.sh --open-pr task.
    The roster close parked migration-author and removed the flat profile
    and pulse job, so the honest assertion INVERTS: a forge write edge
    with no code behind it would describe wiring nothing performs."""
    assert ("pulse:migration-author:promote-migration", "repo:gitlab-forge") \
        not in _data_edges(committed), (
        "the promote-migration forge edge is back in the graph — if the "
        "migration-author was un-parked, restore the positive form of this "
        "gate (git history, 2026-08-26) so the edge is backed by code again"
    )
    assert not (REPO / "files/anatomy/agents/migration-author.yml").exists(), (
        "the flat migration-author profile reappeared; see "
        "test_agent_roster_close.py"
    )


def test_tofu_read_edge_is_backed_by_code(committed):
    assert ("tofu:authentik-state", "pulse:authentik-tofu-drift:tofu-drift-plan") \
        in _data_edges(committed)
    script = (REPO / "files/anatomy/plugins/authentik-tofu-drift-base/skills/"
              "run-tofu-drift.sh").read_text(encoding="utf-8")
    for needle in ("NOS_TOFU_DIR", "nos.auto.tfvars.json"):
        assert needle in script, (
            f"run-tofu-drift.sh no longer contains {needle!r} — the declared "
            f"read edge describes a plan path the script stopped taking"
        )


def test_github_origin_has_no_automated_writer(committed):
    """The absence IS the fact: nothing automated may push the public trunk.
    promote-public.sh is gh-auth-gated operator-only (:39-40). If a job ever
    gains a push to origin, this list must be updated deliberately — a silent
    flip from 'no automated writer' to 'one' is exactly what this pins."""
    node = committed["nodes"].get("repo:github-origin")
    assert node is not None, "repo:github-origin vanished from the graph"
    assert node["automated_writers"] == []
    writers = [f for (f, t) in _data_edges(committed) if t == "repo:github-origin"]
    assert writers == [], f"automated writers appeared for github-origin: {writers}"


def test_every_registry_row_has_a_node_and_bindings_resolve(committed):
    """43 rows in state/tofu-authentik-services.yml on 2026-08-06. Every slug
    gets an authentik: node; slugs that map onto a manifest service carry the
    binding edge; the ones that do not (Tier-2 apps + uninstalled) say
    `service: null` rather than pointing at nodes that do not exist."""
    import yaml
    reg = yaml.safe_load(
        (REPO / "state/tofu-authentik-services.yml").read_text(encoding="utf-8"))
    slugs = [r["slug"] for r in reg["tofu_authentik_services"]]
    assert len(slugs) >= 40
    data = _data_edges(committed)
    for slug in slugs:
        node = committed["nodes"].get(f"authentik:{slug}")
        assert node is not None, f"registry row {slug} has no authentik: node"
        if node["service"] is not None:
            assert (f"authentik:{slug}", f"service:{node['service']}") in data, (
                f"authentik:{slug} names service {node['service']} but the "
                f"binding edge is missing"
            )
            assert f"service:{node['service']}" in committed["nodes"]
    unmatched = sorted(s for s in slugs
                       if committed["nodes"][f"authentik:{s}"]["service"] is None)
    # Measured 2026-08-06: Tier-2 apps (documenso/qdrant/roundcube/twofauth),
    # spacetimedb (excluded service). A new unmatched slug is a new gap to
    # look at, not an error — but shrinkage below the known set means a
    # binding was lost, which is.
    for expected in ("documenso", "qdrant", "roundcube", "spacetimedb", "twofauth"):
        assert expected in unmatched or f"service:{expected}" in committed["nodes"], (
            f"{expected} was unmatched on 2026-08-06 and is now neither "
            f"unmatched nor a service node — a binding silently vanished"
        )
