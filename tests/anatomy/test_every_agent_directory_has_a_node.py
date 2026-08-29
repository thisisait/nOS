"""An agent ceremony is an ADDRESS, and the address says what the profile says.

Until 2026-08-29 the anatomy graph knew agents only as the pulse jobs that
fire them: `pulse:librarian:brief-taxonomy` was in the address space, the
librarian was not. So the questions the graph exists to answer — what does
this ceremony need, whose identity does it run as, which orchestrator serves
it — had no node to be asked of, and the three parked agents (contract-only,
no pulse job at all) had no address whatsoever.

This gate reads the EMITTED artifact against the filesystem, in both
directions, and refuses:

  * a profile directory with no node — the silent-zero failure a regex
    harvest fails at (harvest_agents is a yaml walk, but a glob that stops
    matching still emits nothing);
  * a node with no profile — a stale address outliving its file;
  * a node whose facts disagree with its own agent.yml. Every attribute is
    re-read here from the source of truth rather than compared against a
    literal, so the gate cannot be satisfied by editing the gate;
  * a declared tool, backend binding or machine identity with no edge.

`runner_status` is checked against the ENUM in state/schema/agent.schema.yaml
rather than a list retyped here, because tests/anatomy/test_agent_schema.py
SKIPS when jsonschema is absent and this is then the only reader holding that
vocabulary. An absent runner_status is UNKNOWN — permitted, and required to
render as unknown, never as one of the five states.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
GRAPH = REPO / "state" / "anatomy-graph.json"
AGENTS = REPO / "files" / "anatomy" / "agents"
SCHEMA = REPO / "state" / "schema" / "agent.schema.yaml"
BACKENDS = REPO / "state" / "llm-backends.yml"


@pytest.fixture(scope="module")
def graph() -> dict:
    return json.loads(GRAPH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def profiles() -> dict[str, dict]:
    out = {}
    for path in sorted(AGENTS.glob("*/agent.yml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        out[str(doc.get("name") or path.parent.name)] = doc
    return out


def _agent_nodes(graph: dict) -> dict[str, dict]:
    return {k: v for k, v in graph["nodes"].items() if v["kind"] == "agent"}


def _edges(graph: dict, derived: str) -> set[tuple[str, str]]:
    return {(e["from"], e["to"]) for e in graph["edges"] if e.get("derived") == derived}


def test_there_are_agents_to_find(profiles):
    """Positive control: an empty corpus must not read as full coverage."""
    assert len(profiles) >= 7, f"only {len(profiles)} agent profiles found under {AGENTS}"


def test_every_agent_directory_has_a_node(graph, profiles):
    nodes = _agent_nodes(graph)
    missing = sorted(n for n in profiles if f"agent:{n}" not in nodes)
    assert not missing, (
        f"agent profiles with no node in the graph: {missing} — regenerate with "
        f"tools/anatomy-graph-gen.py, or fix harvest_agents if it emitted nothing")


def test_every_agent_node_has_a_directory(graph, profiles):
    for nid, n in _agent_nodes(graph).items():
        name = nid.split(":", 1)[1]
        assert name in profiles, f"{nid} names no profile under {AGENTS}"
        assert (REPO / n["source"]).is_file(), f"{nid}: source {n['source']} does not exist"


def test_the_node_repeats_the_profile_rather_than_asserting(graph, profiles):
    for nid, n in _agent_nodes(graph).items():
        doc = profiles[nid.split(":", 1)[1]]
        meta, model = doc.get("metadata") or {}, doc.get("model") or {}
        assert n["charter"] == meta.get("ceremony_role"), nid
        assert n["runner_status"] == meta.get("runner_status"), nid
        assert n["primary_model"] == model.get("primary"), nid
        assert n["backend_declared"] is (model.get("backend") is not None), nid
        assert n["tools"] == sorted({t["id"] for t in doc.get("tools") or []}), nid


def test_runner_status_is_the_schema_vocabulary_or_absent(graph, profiles):
    schema = yaml.safe_load(SCHEMA.read_text(encoding="utf-8"))
    allowed = schema["properties"]["metadata"]["properties"]["runner_status"]["enum"]
    assert set(allowed) == {"unproven", "scheduled", "parked", "deferred", "proven"}, (
        "the runner_status vocabulary changed — decide deliberately, then update "
        "this gate AND the graph's description of an absent status")
    for nid, n in _agent_nodes(graph).items():
        status = n["runner_status"]
        assert status is None or status in allowed, f"{nid}: runner_status={status!r}"
        if status is None:
            assert "UNDECLARED" in n["description"], (
                f"{nid} has no declared runner_status and its description does not "
                f"say so — absence must render as absence, never as calm")


def test_every_declared_tool_is_an_edge(graph, profiles):
    edges = _edges(graph, "agent-tools")
    for name, doc in profiles.items():
        for tool in {t["id"] for t in doc.get("tools") or []}:
            assert (f"resource:{tool}", f"agent:{name}") in edges, (
                f"{name} declares tool {tool} with no edge — the grant is invisible "
                f"to every reader of the graph")


def test_every_agent_is_served_by_a_register_row(graph, profiles):
    """A ceremony with no orchestrator edge is one whose serving set nothing
    can read — including the compliance question of where its prompts go."""
    register = yaml.safe_load(BACKENDS.read_text(encoding="utf-8"))["backends"]
    edges = _edges(graph, "agent-backend")
    for name, doc in profiles.items():
        served = [f for f, t in edges if t == f"agent:{name}"]
        assert len(served) == 1, f"{name}: expected one backend edge, got {served}"
        row = served[0].removeprefix("resource:backend-")
        assert row in register, f"{name} is bound to {row}, which the register lacks"
        declared = (doc.get("model") or {}).get("backend")
        assert row == (declared or next(k for k, v in register.items() if v.get("default")))


def test_a_reserved_machine_identity_reaches_its_agent(graph, profiles):
    """The roster reserves `nos-<agent>` clients for agents that have no pulse
    job at all (the parked three). Where the row exists, the edge must."""
    edges = _edges(graph, "agent-identity")
    for name in profiles:
        client = f"authentik:nos-{name}"
        if client in graph["nodes"]:
            assert (client, f"agent:{name}") in edges, (
                f"{client} is provisioned but reaches no agent node")


def test_a_dispatching_job_points_at_the_agent_it_runs(graph):
    """The trigger edge is derived from the job's own --agent= / NOS_AGENT_NAME,
    so a job renamed away from its ceremony loses the edge rather than keeping
    a stale one."""
    edges = _edges(graph, "agent-dispatch")
    assert edges, "no pulse job dispatches any agent — the derivation stopped matching"
    for src, dst in edges:
        assert graph["nodes"][src]["kind"] == "pulse"
        assert graph["nodes"][dst]["kind"] == "agent"
        assert graph["nodes"][src]["runs_agent"] == dst.split(":", 1)[1]
