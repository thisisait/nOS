"""Anatomy gates for the nOS Remediator agent (A9.3, 2026-05-17).

Pins the contracts so a future refactor can't silently regress the agent
into auto-resolve / write behavior or break the genericized
pulse-run-agent.sh runner.
"""

from __future__ import annotations

import pathlib
import stat
import subprocess

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]


# ── Generic pulse-run-agent.sh contract ────────────────────────────────


def test_pulse_run_agent_reads_nos_agent_env():
    """The runner accepts NOS_AGENT_* env (canonical post-A9.3) and
    falls back to NOS_CONDUCTOR_* for backward compat with existing
    Pulse jobs.
    """
    src = (REPO / "files/anatomy/scripts/pulse-run-agent.sh").read_text()
    assert "NOS_AGENT_NAME" in src
    assert "NOS_AGENT_CLIENT_ID" in src
    assert "NOS_AGENT_CLIENT_SECRET" in src
    assert "NOS_AGENT_PROFILE" in src
    assert "NOS_AGENT_TASK" in src
    # Backward-compat aliases (conductor's existing env still works).
    assert "NOS_CONDUCTOR_CLIENT_ID" in src
    assert "NOS_CONDUCTOR_CLIENT_SECRET" in src
    # AGENT_NAME drives the source/origin tagging.
    assert 'source":"%s"' in src   # printf into agent_run_start/end events
    assert "$AGENT_NAME" in src


def test_pulse_run_agent_bash_lint_clean():
    result = subprocess.run(
        ["bash", "-n", str(REPO / "files/anatomy/scripts/pulse-run-agent.sh")],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, f"bash -n failed: {result.stderr}"


def test_conductor_uses_nos_agent_env():
    """Conductor profile must use the canonical NOS_AGENT_* shape."""
    profile = yaml.safe_load(
        (REPO / "files/anatomy/agents/conductor.yml").read_text()
    )
    env = (profile["pulse"]["jobs"][0].get("env") or {})
    assert env.get("NOS_AGENT_NAME") == "conductor"
    assert env.get("NOS_AGENT_CLIENT_ID") == "nos-conductor"
    assert "NOS_AGENT_TASK" in env
    assert "NOS_AGENT_PROFILE" in env


# ── Remediator profile (pulse-runner-side + AgentKit-side) ─────────────


def test_remediator_pulse_profile_exists():
    profile_path = REPO / "files/anatomy/agents/remediator.yml"
    assert profile_path.is_file()
    profile = yaml.safe_load(profile_path.read_text())
    assert profile["name"] == "remediator"
    # On-demand only — Pulse row is paused-by-default.
    job = profile["pulse"]["jobs"][0]
    assert job["paused"] is True
    assert "remediator is on-demand" in (job.get("paused_reason") or "")


def test_remediator_pulse_profile_uses_nos_agent_env():
    profile = yaml.safe_load(
        (REPO / "files/anatomy/agents/remediator.yml").read_text()
    )
    env = profile["pulse"]["jobs"][0]["env"]
    assert env["NOS_AGENT_NAME"] == "remediator"
    assert env["NOS_AGENT_CLIENT_ID"] == "nos-remediator"
    assert env["NOS_AGENT_PROFILE"].endswith("/agents/remediator.yml")


def test_remediator_pulse_profile_declares_notification_routing():
    profile = yaml.safe_load(
        (REPO / "files/anatomy/agents/remediator.yml").read_text()
    )
    notif = profile["notification"]
    assert notif["on_critical"] == ["wing-inbox", "ntfy", "mail"]
    assert notif["on_high"] == ["wing-inbox", "ntfy"]
    assert notif["on_medium"] == ["wing-inbox"]


def test_remediator_pulse_profile_capabilities_read_only():
    """Remediator MUST NOT carry write scopes. nos:security:write would
    let it auto-resolve findings — that's the operator's call.
    """
    profile = yaml.safe_load(
        (REPO / "files/anatomy/agents/remediator.yml").read_text()
    )
    caps = profile["capabilities"]
    for cap in caps:
        assert "write" not in cap, f"remediator must not have write scope; got {cap}"
        assert "scan" not in cap, f"remediator must not trigger scans; got {cap}"


def test_remediator_system_prompt_bans_writes():
    """system_prompt must explicitly forbid POST/PUT/DELETE and file
    modifications. Defense-in-depth alongside the capability scopes.
    """
    profile = yaml.safe_load(
        (REPO / "files/anatomy/agents/remediator.yml").read_text()
    )
    # Collapse whitespace so phrases that wrap in YAML still match.
    prompt = " ".join(profile["system_prompt"].split())
    assert "READ-ONLY" in prompt
    assert "Never POST" in prompt
    assert "Never modify repo files" in prompt
    assert "/api/v1/gitleaks_findings/{id}/resolve" in prompt
    assert "operator does that from Wing /inbox" in prompt


# ── AgentKit (A14) side ─────────────────────────────────────────────────


def test_remediator_agentkit_profile_exists():
    for fname in ("agent.yml", "system.md", "rubric.md"):
        path = REPO / "files/anatomy/agents/remediator" / fname
        assert path.is_file(), f"missing {fname}"


def test_remediator_agentkit_agent_yml_model_uri():
    """AgentKit naming convention (test_agentkit_naming.py) enforces the
    URI scheme — verify our model URIs match.
    """
    agent = yaml.safe_load(
        (REPO / "files/anatomy/agents/remediator/agent.yml").read_text()
    )
    assert agent["model"]["primary"] == "anthropic-claude-opus-4-7"
    assert agent["model"]["fallback"] == "openclaw-qwen-coder-32b"


def test_remediator_agentkit_system_md_has_no_write_section():
    """system.md must include the no-auto-resolve rule + describe the
    output contract operator depends on.
    """
    src = (REPO / "files/anatomy/agents/remediator/system.md").read_text()
    assert "## Remediation report" in src
    assert "Summary" in src
    assert "Per-finding analysis" in src
    assert "Recommendations" in src
    # No-auto-resolve rule + clear operator-decides framing.
    assert "No auto-resolve" in src
    assert "Do NOT call" in src
    assert "operator decides" in src.lower() or "operator does that" in src.lower()


def test_remediator_rubric_pins_structure():
    src = (REPO / "files/anatomy/agents/remediator/rubric.md").read_text()
    assert "## Structure" in src
    # Five required fields per finding.
    for field in ("Fingerprint", "Severity", "Evidence",
                  "Proposed fix", "Operator action"):
        assert field in src
    # Failure on auto-resolve claims.
    assert "auto-resolved" in src or "auto-resolve" in src


# ── Authentik client + credential wiring ───────────────────────────────


def test_authentik_client_nos_remediator_registered():
    """Parse the YAML so we read the remediator's capabilities cleanly
    (regex over a multi-row YAML list was too fragile)."""
    raw = (REPO / "default.config.yml").read_text()
    # Authentik agent_clients block carries the row.
    assert 'slug: "nos-remediator"' in raw
    assert 'client_id: "nos-remediator"' in raw

    cfg = yaml.safe_load(raw)
    clients = cfg.get("authentik_agent_clients") or []
    rem = next((c for c in clients if c.get("slug") == "nos-remediator"), None)
    assert rem is not None
    caps = rem.get("capabilities") or []
    # No write/scan scopes — would let it auto-resolve findings.
    for cap in caps:
        assert "write" not in cap, f"remediator client has write scope: {cap}"
        assert "scan" not in cap, f"remediator client has scan scope: {cap}"


def test_remediator_wing_api_token_credential_declared():
    creds = (REPO / "default.credentials.yml").read_text()
    assert "remediator_wing_api_token:" in creds


# ── tools/run-remediator.sh wrapper ────────────────────────────────────


def test_run_remediator_wrapper_present_and_executable():
    path = REPO / "tools/run-remediator.sh"
    assert path.is_file()
    assert path.stat().st_mode & stat.S_IXUSR


def test_run_remediator_wrapper_bash_lint_clean():
    result = subprocess.run(
        ["bash", "-n", str(REPO / "tools/run-remediator.sh")],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr


def test_run_remediator_wrapper_probes_required_surfaces():
    src = (REPO / "tools/run-remediator.sh").read_text()
    assert "/api/health" in src
    assert "BONE_API_URL" in src
    assert "triage-open-findings" in src
    # Post-flight verifier.
    assert "EVENT_DELTA" in src
    assert "NOTIF_DELTA" in src
    assert "origin_agent = 'remediator'" in src
    # Verdict layers.
    assert "**GREEN**" in src
    assert "**REVIEW**" in src
    assert "**RED**" in src
