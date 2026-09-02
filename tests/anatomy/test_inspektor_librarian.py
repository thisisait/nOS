"""Anatomy gates for the Inspektor + Librarian agent profiles.

Inspektor ships AgentKit-side only — its Pulse runner is explicitly
deferred until its tooling lands (trivy/grype/nuclei substrate). The
contract-only profile still validates against the AgentKit schema and
surfaces in the /agents catalog. Librarian's runner is LIVE and, since 2026-08-28, nightly.

Scout lived in this file from A9.4 (2026-05-17) until the 2026-08-26
roster close retired it (zero agent:scout events in the wing.db epoch;
its brief runs nightly as conductor:security-drift-watch plus the scan).
Its gates were deleted with their subject; test_agent_roster_close.py
pins the retirement.
"""


from __future__ import annotations

import pathlib
import re

import yaml

from test_agentkit_keap_tool import PROPOSAL_ONLY_POST_PATHS, keap_post_allowlist

REPO = pathlib.Path(__file__).resolve().parents[2]
AGENTS = REPO / "files/anatomy/agents"


# ── Inspektor (contract-only) + Librarian (live, nightly) ─────────────


def test_inspektor_agentkit_only():
    """Inspektor ships as an AgentKit-side profile (agent.yml + system.md
    + rubric.md) but NO Pulse profile — its runner depends on a
    trivy/grype/nuclei substrate that hasn't landed yet. Explicit
    `runner_status: deferred` in agent.yml metadata documents the gap."""
    d = AGENTS / "inspektor"
    for f in ("agent.yml", "system.md", "rubric.md"):
        assert (d / f).is_file(), f"inspektor/{f} missing"
    # Top-level inspektor.yml MUST NOT exist (no Pulse profile = no runner).
    assert not (AGENTS / "inspektor.yml").is_file(), (
        "inspektor.yml exists but the runner is documented as deferred — "
        "either ship the Pulse profile OR remove the .yml file. "
        "Half-shipped state is the worst of both worlds."
    )
    agent = yaml.safe_load((d / "agent.yml").read_text())
    meta = agent.get("metadata") or {}
    assert meta.get("runner_status") == "deferred"
    assert meta.get("deferred_reason"), (
        "inspektor/agent.yml must explain WHY the runner is deferred "
        "(metadata.deferred_reason)"
    )


def test_librarian_runner_live_on_demand():
    """Librarian's runner went LIVE 2026-07-11 (cortex Layer 2): flat
    Pulse profile librarian.yml + AgentKit profile. Unpaused 2026-08-28:
    the three ceremonies run nightly through the bound runner.
    This gate pins the whole shape so neither half regresses to the
    pre-runner state (and the ceremony keeps its taxonomy-growth leg)."""
    d = AGENTS / "librarian"
    for f in ("agent.yml", "system.md", "rubric.md"):
        assert (d / f).is_file(), f"librarian/{f} missing"
    profile_path = AGENTS / "librarian/agent.yml"
    assert profile_path.is_file(), (
        "librarian/agent.yml missing — one file per agent since 2026-08-28; "
        "removing it kills both the AgentKit contract and the Pulse schedule"
    )
    flat = yaml.safe_load(profile_path.read_text())
    jobs = ((flat.get("pulse") or {}).get("jobs")) or []
    by_name = {j.get("name"): j for j in jobs}
    # All three ceremonies must exist and run on the bound runner.
    # THE TIER PIN IS GONE, 2026-08-29. These jobs carried NOS_AGENT_MODEL and
    # the bound runner never reached it — `ClaudeCliAdapter` passes `--model`
    # only when there is no binding (ruling 3), and every scheduled ceremony is
    # bound. `describe-taxonomy` said haiku and ran on the sonnet-tier model.
    # The tier now lives where it is read: agent.yml `model.primary` plus the
    # backend's model_env table, pinned by
    # test_the_effective_model_is_decided_where_it_is_read.py.
    for name in ("judge-lint-queue", "describe-taxonomy", "brief-taxonomy"):
        job = by_name.get(name)
        assert job, f"librarian/agent.yml must declare the {name} pulse job"
        # Unpaused 2026-08-28. What replaces the pause as the property worth
        # pinning: a SCHEDULED ceremony must go through the runner that can
        # receive the backend binding. The claude CLI cannot, so a nightly job
        # on that path spends on the default backend for ever, unasked.
        assert job.get("command", "").endswith("/tools/run-agent.sh"), (
            f"{name} runs on a schedule, so it must use the bound runner"
        )
        assert "--agent=librarian" in (job.get("args") or []), (
            f"{name} must name its agent — run-agent.sh has no default"
        )
        assert "NOS_AGENT_MODEL" not in (job.get("env") or {}), (
            f"{name} carries a model pin the bound runner does not read; it "
            "reads like a cost guarantee and decides nothing"
        )
    # The prompt lives in system.md — the ONE spelling since the merge. The
    # dir copy used to describe an abandoned Qdrant RAG contract while the real
    # ceremony sat in the flat file, so a bound run read the wrong prompt.
    prompt = (d / "system.md").read_text(encoding="utf-8")
    # The three ceremony legs: verdicts, promotions, taxonomy growth.
    assert "/agent/v1/lint/verdict" in prompt
    assert "/agent/v1/promotions" in prompt
    assert "/agent/v1/taxonomy/propose" in prompt, (
        "librarian's system prompt lost the taxonomy-growth leg "
        "(frog-depth node proposals, Track T)"
    )
    agent = yaml.safe_load((d / "agent.yml").read_text())
    meta = agent.get("metadata") or {}
    # `scheduled` left the enum (ruling 2, docs/doctrine/agentkit.md §6);
    # the cadence is a pulse edge, the field carries evidence.
    assert meta.get("runner_status") == "proven"


def test_inspektor_carries_write_scope():
    """Inspektor is the canonical pentest substrate — write scope
    pre-declared so when the runner lands it can write findings
    without a capability widening. (Distinct from remediator, which is
    explicitly read-only.)"""
    agent = yaml.safe_load((AGENTS / "inspektor/agent.yml").read_text())
    scopes = (agent.get("audit") or {}).get("capability_scopes") or []
    assert any("write" in s for s in scopes)
    assert any("scan" in s for s in scopes)
    assert any("pentest" in s for s in scopes)


def test_librarian_is_read_only():
    """Librarian surfaces context, never writes findings or proposes fixes.

    `wing.write` (2026-08-28) is NOT a widening and is allowed only under a
    condition asserted here: it loads `mcp-wing-write`, whose route allowlist
    is `/api/v1/events` and nothing else — the report leg `events.write`
    already named. Add a second route to that allowlist and this gate goes red,
    which is the point: the scope's meaning lives in the allowlist, so the
    doctrine has to be checked there rather than in the scope's spelling.

    `keap.write` (2026-08-29) is the same argument for the cortex. It is not
    new capability: this agent has filed lint verdicts and briefs into KEAP's
    moderation queue since 2026-08-16 under `keap.read`, because mcp-keap
    served POST without asking for a scope that named it. Declaring the scope
    made the write visible; it did not create it. The condition is that every
    writable KEAP path stays a PROPOSAL a moderator decides — no approve path.
    """
    agent = yaml.safe_load((AGENTS / "librarian/agent.yml").read_text())
    scopes = (agent.get("audit") or {}).get("capability_scopes") or []
    for s in scopes:
        assert "write" not in s or s in ("events.write", "wing.write", "keap.write"), (
            f"librarian must not have write scope: {s}"
        )
        assert "scan" not in s
        assert "pentest" not in s

    if "wing.write" in scopes:
        src = (
            REPO / "files/anatomy/wing/app/AgentKit/Tools/McpWingWriteTool.php"
        ).read_text(encoding="utf-8")
        block = src[src.index("GRANTED_ROUTES = ["):]
        routes = re.findall(r"'(/api/[^']+)'", block[: block.index("]")])
        assert routes == ["/api/v1/events"], (
            f"librarian holds wing.write and the write plane now reaches {routes}. "
            "That is a widening past 'files its own report', which is the only "
            "write this agent is allowed."
        )

    if "keap.write" in scopes:
        # The list is imported, not restated: a widening has to be argued in
        # the one place that pins it, and it reds here too.
        assert keap_post_allowlist() == PROPOSAL_ONLY_POST_PATHS, (
            "librarian holds keap.write and mcp-keap's POST allowlist has "
            f"drifted to {keap_post_allowlist()}. The scope is allowed only "
            "while every writable path is a proposal a moderator decides."
        )
