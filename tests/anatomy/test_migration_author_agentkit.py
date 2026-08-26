"""Anatomy gate — migration-author runs natively in AgentKit (Q8/A2, 2026-06-16).

Adjustment step A2 makes the migration-author agent run through the AgentKit
Runner (agent_sessions / threads / iterations + OTel spans → Wing /agents +
Grafana 22-ai-agents + Tempo) instead of only the pulse-run-agent.sh CLI. This
gate pins the A2 wiring contract — the *visibility* half of Q8 (A1's gate
test_agentkit_write_tool_scope.py pins the *security* half, the write tool).

What A2 must structurally guarantee, pinned here:

  1. The migration-author DIR profile (the AgentKit-native one) declares the
     gated migration-file-write tool in its tools roster — so the native run
     can actually author — alongside its read + Wing tools. The scope was
     already provisioned (A1 gate covers that); this pins the *roster* edit.
  2. The MR-open stays a controlled post-step, NOT an LLM tool: the agent has
     no forge/git tool, and the native run does not push from inside the
     session. (Pinned via the agent.yml roster + the system prompt narrative.)

ROSTER CLOSE (2026-08-26) — the agent is PARKED. A2's rule 4 ("the flat CLI
profile survives; deleting either is a regression") is SUPERSEDED: the flat
profile, tools/run-migration-author.sh, the pulse job and the Wing bearer are
gone, and this gate now pins the opposite — the park must be total and honest.
One spelling remains (the dir profile), it says `runner_status: parked`, and
no launcher-facing apparatus survives half-removed. The Q8/A2 run-script
tests left with the launcher; the native entry point (run-agent.php) is still
pinned because un-parking rides it.

Static inspection (regex / YAML / text), NO PHP or bash interpreter — runs in
CI without PHP or a shell.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
AGENTS_DIR = REPO_ROOT / "files" / "anatomy" / "agents"
DIR_PROFILE = AGENTS_DIR / "migration-author" / "agent.yml"
FLAT_PROFILE = AGENTS_DIR / "migration-author.yml"
SYSTEM_MD = AGENTS_DIR / "migration-author" / "system.md"
RUN_SCRIPT = REPO_ROOT / "tools" / "run-migration-author.sh"
RUN_AGENT_PHP = REPO_ROOT / "files" / "anatomy" / "wing" / "bin" / "run-agent.php"


@pytest.fixture(scope="module")
def dir_profile() -> dict:
    if not DIR_PROFILE.is_file():
        pytest.fail("migration-author/agent.yml is missing")
    return yaml.safe_load(DIR_PROFILE.read_text())


# ---------- (1) the dir profile declares the write tool in its roster ----------


def test_dir_profile_declares_migration_file_write(dir_profile: dict):
    """The AgentKit-native dir profile lists migration-file-write in its tools
    roster — without it the native run has no write surface (Q8/A2)."""
    tool_ids = {t.get("id") for t in (dir_profile.get("tools") or [])}
    assert "migration-file-write" in tool_ids, (
        "migration-author/agent.yml tools roster must declare migration-file-write "
        "(A2 — the AgentKit-native write surface)"
    )


def test_dir_profile_keeps_read_and_wing_tools(dir_profile: dict):
    """The write tool is ADDED, not swapped — the read + Wing tools stay so the
    agent can still cat recipes/manifest and call the Wing API (extend, not
    rewrite)."""
    tool_ids = {t.get("id") for t in (dir_profile.get("tools") or [])}
    assert "bash-read-only" in tool_ids, "bash-read-only must remain in the roster"
    assert "mcp-wing" in tool_ids, "mcp-wing must remain in the roster"


def test_dir_profile_scope_covers_the_write_tool(dir_profile: dict):
    """nos.migration.write ⊆ capability_scopes so ToolRegistry::forAgent will
    not throw the missing-scope RuntimeException at session start."""
    scopes = set(dir_profile.get("audit", {}).get("capability_scopes") or [])
    assert "nos.migration.write" in scopes, (
        "audit.capability_scopes must carry nos.migration.write for the tool to load"
    )


def test_dir_profile_has_no_forge_or_git_tool(dir_profile: dict):
    """The MR-open is a deterministic post-step, NOT an LLM tool. The agent must
    have no shell-write / forge / git capability inside the AgentKit sandbox —
    its only write surface is the path-allowlisted migration-file-write."""
    tool_ids = {t.get("id") for t in (dir_profile.get("tools") or [])}
    forbidden = {"bash-write", "mcp-bone"}  # no general shell-write; no Bone write reach
    leaked = tool_ids & forbidden
    assert not leaked, (
        f"migration-author roster must not declare {leaked} — the MR-open is a "
        "trigger-layer post-step, the agent has no forge/git/shell-write tool"
    )


# ---------- (3) the native runner path actually exists ----------


def test_run_agent_php_exists_and_takes_trigger():
    """The native entry point exists and accepts --agent / --trigger so the
    script's invocation is real, not aspirational."""
    assert RUN_AGENT_PHP.is_file(), "files/anatomy/wing/bin/run-agent.php is missing"
    txt = RUN_AGENT_PHP.read_text()
    assert "agent" in txt and "trigger" in txt, (
        "run-agent.php must accept --agent and --trigger (it backs the native path)"
    )


# ---------- (4) the park is total and honest (roster close 2026-08-26) ----------


def test_the_park_left_one_spelling():
    """The dual declaration is collapsed: the flat CLI profile and the
    launcher are GONE. A resurrected copy would be the second spelling of
    one truth — the defect class behind the cAdvisor scrape and the
    dialectOptions bug. Un-parking re-declares deliberately (plan_ref)."""
    assert not FLAT_PROFILE.exists(), (
        "files/anatomy/agents/migration-author.yml reappeared — the 2026-08-26 "
        "park removed it; un-parking must re-declare via the epic plan "
        "(metadata.plan_ref), not resurrect the old copy"
    )
    assert not RUN_SCRIPT.exists(), (
        "tools/run-migration-author.sh reappeared — the park removed the "
        "launcher-facing apparatus; see metadata.deferred_reason"
    )


def test_the_parked_profile_says_so(dir_profile: dict):
    """A parked agent must SAY it is parked in its own file (the inspektor
    pattern): metadata.runner_status + a plan_ref naming the un-parking epic."""
    meta = dir_profile.get("metadata") or {}
    assert meta.get("runner_status") == "parked", (
        "migration-author/agent.yml metadata.runner_status must be 'parked' "
        "while no runner apparatus exists — absence must not read as live"
    )
    assert meta.get("plan_ref"), (
        "a parked agent names the epic that un-parks it (metadata.plan_ref)"
    )


# ---------- (5) system prompt narrative matches the native contract ----------


def test_system_prompt_uses_the_write_tool_not_freeform_write():
    """The dir-profile system prompt instructs the agent to author via the
    migration_file_write tool and states the MR is opened by the trigger layer
    post-session (not an LLM action) — the A2 narrative contract."""
    if not SYSTEM_MD.is_file():
        pytest.fail("migration-author/system.md is missing")
    md = SYSTEM_MD.read_text()
    assert "migration_file_write" in md, (
        "system.md must instruct the agent to use migration_file_write"
    )
    # The MR-open is described as automatic / trigger-layer, not an agent push.
    assert re.search(r"trigger layer", md, re.IGNORECASE), (
        "system.md must state the MR is opened by the trigger layer post-session"
    )
    assert re.search(r"no\s+forge/git", md, re.IGNORECASE), (
        "system.md must state the agent has no forge/git tool (no push from the session)"
    )
