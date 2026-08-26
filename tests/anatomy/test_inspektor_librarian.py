"""Anatomy gates for the Inspektor + Librarian agent profiles.

Inspektor ships AgentKit-side only — its Pulse runner is explicitly
deferred until its tooling lands (trivy/grype/nuclei substrate). The
contract-only profile still validates against the AgentKit schema and
surfaces in the /agents catalog. Librarian's runner is LIVE, on demand.

Scout lived in this file from A9.4 (2026-05-17) until the 2026-08-26
roster close retired it (zero agent:scout events in the wing.db epoch;
its brief runs nightly as conductor:security-drift-watch plus the scan).
Its gates were deleted with their subject; test_agent_roster_close.py
pins the retirement.
"""


from __future__ import annotations

import pathlib

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
AGENTS = REPO / "files/anatomy/agents"


# ── Inspektor (contract-only) + Librarian (live, on-demand) ───────────


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
    Pulse profile librarian.yml + AgentKit profile, fired on demand by
    tools/run-librarian.sh — the Pulse row stays paused by doctrine.
    This gate pins the whole shape so neither half regresses to the
    pre-runner state (and the ceremony keeps its taxonomy-growth leg)."""
    d = AGENTS / "librarian"
    for f in ("agent.yml", "system.md", "rubric.md"):
        assert (d / f).is_file(), f"librarian/{f} missing"
    flat_path = AGENTS / "librarian.yml"
    assert flat_path.is_file(), (
        "librarian.yml (flat Pulse profile) missing — the runner shipped "
        "2026-07-11; removing it silently kills tools/run-librarian.sh"
    )
    flat = yaml.safe_load(flat_path.read_text())
    jobs = ((flat.get("pulse") or {}).get("jobs")) or []
    by_name = {j.get("name"): j for j in jobs}
    # All three ceremonies must exist, stay paused (on-demand), and pin a
    # cost-tier model — dropping NOS_AGENT_MODEL silently reverts a bulk job
    # to the operator's flagship default (the point of the model-tier commit).
    expected_tiers = {
        "judge-lint-queue": "sonnet",
        "describe-taxonomy": "haiku",
        "brief-taxonomy": "sonnet",
    }
    for name, tier in expected_tiers.items():
        job = by_name.get(name)
        assert job, f"librarian.yml must declare the {name} pulse job"
        assert job.get("paused") is True, (
            f"{name} must stay paused=true (on-demand doctrine — "
            "tools/run-librarian.sh is the trigger, not cron)"
        )
        assert (job.get("env") or {}).get("NOS_AGENT_MODEL") == tier, (
            f"{name} must pin NOS_AGENT_MODEL={tier} so the bulk ceremony "
            "never inherits the operator's flagship default"
        )
    prompt = flat.get("system_prompt") or ""
    # The three ceremony legs: verdicts, promotions, taxonomy growth.
    assert "/agent/v1/lint/verdict" in prompt
    assert "/agent/v1/promotions" in prompt
    assert "/agent/v1/taxonomy/propose" in prompt, (
        "librarian's system prompt lost the taxonomy-growth leg "
        "(frog-depth node proposals, Track T)"
    )
    agent = yaml.safe_load((d / "agent.yml").read_text())
    meta = agent.get("metadata") or {}
    assert meta.get("runner_status") == "on-demand"


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
    """Librarian surfaces context, never writes findings or proposes
    fixes. Read-only scopes only."""
    agent = yaml.safe_load((AGENTS / "librarian/agent.yml").read_text())
    scopes = (agent.get("audit") or {}).get("capability_scopes") or []
    for s in scopes:
        assert "write" not in s or s == "events.write", (
            f"librarian must not have write scope: {s}"
        )
        assert "scan" not in s
        assert "pentest" not in s
