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
    # Env-export for the discover script.
    assert "NOS_SCOUT_WING_API_TOKEN" in src


def test_discover_pulse_catalog_substitutes_scout_token():
    src = (REPO / "files/anatomy/scripts/discover-pulse-catalog.py").read_text()
    assert '{{ scout_wing_api_token }}' in src
    assert "NOS_SCOUT_WING_API_TOKEN" in src


# ── Inspektor + Librarian (contract-only) ─────────────────────────────


def test_inspektor_librarian_agentkit_only():
    """Both ship as AgentKit-side profiles (agent.yml + system.md +
    rubric.md) but NO Pulse profile — their runners depend on tooling
    (trivy/grype/nuclei for inspektor; Qdrant corpus for librarian)
    that hasn't landed yet. Explicit `runner_status: deferred` in
    agent.yml metadata documents the gap."""
    for name in ("inspektor", "librarian"):
        d = AGENTS / name
        for f in ("agent.yml", "system.md", "rubric.md"):
            assert (d / f).is_file(), f"{name}/{f} missing"
        # Top-level <name>.yml MUST NOT exist (no Pulse profile = no runner).
        assert not (AGENTS / f"{name}.yml").is_file(), (
            f"{name}.yml exists but the runner is documented as deferred — "
            f"either ship the Pulse profile OR remove the .yml file. "
            f"Half-shipped state is the worst of both worlds."
        )
        # AgentKit metadata declares the deferred status.
        agent = yaml.safe_load((d / "agent.yml").read_text())
        meta = agent.get("metadata") or {}
        assert meta.get("runner_status") == "deferred"
        assert meta.get("deferred_reason"), (
            f"{name}/agent.yml must explain WHY the runner is deferred "
            f"(metadata.deferred_reason)"
        )


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
