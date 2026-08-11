"""Anatomy gates for the Scout + Inspektor + Librarian agent profiles
(Anatomy A9.4, 2026-05-17).

Scout ships fully (Pulse profile + AgentKit dir + runner script).
Inspektor + Librarian ship AgentKit-side only — their Pulse runners
are explicitly deferred until their tooling lands (trivy/grype/nuclei
for Inspektor; Qdrant corpus pipeline for Librarian). The contract-
only profiles still validate against the AgentKit schema and surface
in the /agents catalog.
"""

from __future__ import annotations

import pathlib
import stat
import subprocess

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
AGENTS = REPO / "files/anatomy/agents"


# ── Scout (fully shipped) ─────────────────────────────────────────────


def test_scout_pulse_profile_present():
    profile = AGENTS / "scout.yml"
    assert profile.is_file()
    data = yaml.safe_load(profile.read_text())
    assert data["name"] == "scout"
    job = data["pulse"]["jobs"][0]
    # On-demand only.
    assert job["paused"] is True
    assert job["name"] == "drift-scan"


def test_scout_pulse_profile_uses_nos_agent_env():
    data = yaml.safe_load((AGENTS / "scout.yml").read_text())
    env = data["pulse"]["jobs"][0]["env"]
    assert env["NOS_AGENT_NAME"] == "scout"
    assert env["NOS_AGENT_CLIENT_ID"] == "nos-scout"
    assert "{{ scout_wing_api_token }}" in env["WING_API_TOKEN"]


def test_scout_capabilities_read_only():
    data = yaml.safe_load((AGENTS / "scout.yml").read_text())
    caps = data["capabilities"]
    for cap in caps:
        assert "write" not in cap, f"scout must not have write scope: {cap}"
        assert "scan" not in cap, f"scout must not trigger scans: {cap}"
        assert "execute" not in cap, f"scout must not execute pentest: {cap}"


def test_scout_agentkit_dir_complete():
    d = AGENTS / "scout"
    for f in ("agent.yml", "system.md", "rubric.md"):
        assert (d / f).is_file(), f"scout/{f} missing"
    agent = yaml.safe_load((d / "agent.yml").read_text())
    assert agent["name"] == "scout"


def test_scout_wrapper_script_present_and_executable():
    p = REPO / "tools/run-scout.sh"
    assert p.is_file()
    assert p.stat().st_mode & stat.S_IXUSR


def test_scout_wrapper_bash_lint_clean():
    p = REPO / "tools/run-scout.sh"
    result = subprocess.run(["bash", "-n", str(p)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_scout_wing_api_token_declared():
    src = (REPO / "default.credentials.yml").read_text()
    assert "scout_wing_api_token" in src


def test_wing_post_yml_provisions_scout_token():
    src = (REPO / "roles/pazny.wing/tasks/post.yml").read_text()
    # Token-provisioning task present.
    assert "--name=scout" in src
    # The playbook no longer exports the token's VALUE to the discover script:
    # the catalog emits a reference and the daemon resolves it. Asserting the
    # ABSENCE keeps the direction pinned — a re-added export would mean the
    # value is travelling again.
    assert "NOS_SCOUT_WING_API_TOKEN" not in src, (
        "the playbook exports the scout token to the catalog task again; it is "
        "resolved at exec time now and does not belong in that process env"
    )


def test_discover_pulse_catalog_points_at_the_scout_token():
    """The token is REFERENCED, not substituted (changed 2026-08-11).

    This asserted the catalog reads `NOS_SCOUT_WING_API_TOKEN` and writes the
    VALUE into the job's env. That is what put nineteen credentials in the clear
    into `pulse_jobs.env_json`; the catalog now emits `secret:scout_wing_api_token`
    and `pulse/daemon.py` resolves it at exec time from the 0600 store. The env
    var is gone from the playbook too — an unused secret in flight is still a
    secret in flight.
    """
    src = (REPO / "files/anatomy/scripts/discover-pulse-catalog.py").read_text()
    assert '{{ scout_wing_api_token }}' in src, "the substitution key is gone"
    assert '"secret:scout_wing_api_token"' in src, (
        "the scout token is no longer emitted as a reference — check whether it "
        "went back to being a value"
    )
    assert "NOS_SCOUT_WING_API_TOKEN" not in src, (
        "the catalog reads the token's VALUE from the environment again"
    )


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
