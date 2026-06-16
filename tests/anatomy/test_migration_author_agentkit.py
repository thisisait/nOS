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
  2. tools/run-migration-author.sh fires the native AgentKit run-agent path
     (php <wing>/bin/run-agent.php --agent=migration-author --trigger=operator)
     as the DEFAULT runtime, with the legacy pulse-CLI retained as a selectable
     fallback (--cli / NOS_MIGRATION_AUTHOR_RUNTIME) — "CLI fallback retained".
  3. The MR-open stays a controlled post-step, NOT an LLM tool: the agent has
     no forge/git tool, and the native run does not push from inside the
     session. (Pinned via the agent.yml roster + the system prompt narrative.)
  4. The flat CLI profile (files/anatomy/agents/migration-author.yml) survives
     — both runtimes coexist by design; deleting either is a regression.

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


@pytest.fixture(scope="module")
def run_script() -> str:
    if not RUN_SCRIPT.is_file():
        pytest.fail("tools/run-migration-author.sh is missing")
    return RUN_SCRIPT.read_text()


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


# ---------- (2) run-migration-author.sh = native default + CLI fallback ----------


def test_run_script_default_runtime_is_agentkit(run_script: str):
    """The default runtime is AgentKit-native (was the pulse CLI). Pinned so a
    future edit can't silently regress the primary path back to the CLI."""
    assert re.search(
        r'RUNTIME="?\$\{NOS_MIGRATION_AUTHOR_RUNTIME:-agentkit\}"?', run_script
    ), (
        "run-migration-author.sh must default RUNTIME to 'agentkit' "
        "(NOS_MIGRATION_AUTHOR_RUNTIME:-agentkit)"
    )


def test_run_script_fires_native_run_agent(run_script: str):
    """The agentkit path invokes run-agent.php for the migration-author agent
    with --trigger=operator — the native Runner path that writes
    agent_sessions/threads/iterations + OTel."""
    assert "run-agent.php" in run_script, (
        "run-migration-author.sh must invoke the Wing bin/run-agent.php (native AgentKit)"
    )
    assert "--agent=migration-author" in run_script, (
        "run-migration-author.sh must run --agent=migration-author"
    )
    assert "--trigger=operator" in run_script, (
        "run-migration-author.sh must pass --trigger=operator (operator-trigger lineage)"
    )


def test_run_script_retains_cli_fallback(run_script: str):
    """The legacy pulse-CLI path is retained as a selectable fallback — Q8/A2
    keeps it for operator/CI use where the deployed Wing PHP runtime is absent.
    Both a --cli flag and the env knob must exist, and the pulse job command
    must still be reachable."""
    assert "--cli" in run_script, "run-migration-author.sh must keep a --cli fallback flag"
    assert "RUNTIME=cli" in run_script, "the --cli path must select RUNTIME=cli"
    assert "$JOB_CMD" in run_script, (
        "the CLI fallback must still invoke the registered pulse_jobs command ($JOB_CMD)"
    )


def test_run_script_branches_on_runtime(run_script: str):
    """The run block branches on the runtime — the two paths carry OPPOSITE
    exit-1 meanings, so a single shared invocation would mis-verdict."""
    assert re.search(r'if\s*\[\[\s*"\$RUNTIME"\s*==\s*agentkit\s*\]\]', run_script), (
        "run-migration-author.sh must branch the run on RUNTIME == agentkit"
    )


def test_run_script_agentkit_preflights_the_wing_bin(run_script: str):
    """The agentkit path pre-flights the deployed run-agent.php (fail-clear if
    Wing isn't deployed) — directs the operator to --cli rather than crashing."""
    assert "RUN_AGENT_BIN" in run_script, (
        "run-migration-author.sh must resolve the Wing run-agent.php path (RUN_AGENT_BIN)"
    )
    assert re.search(r"use --cli", run_script), (
        "the agentkit preflight must point the operator at the --cli fallback on failure"
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


# ---------- (4) both runtimes coexist — flat CLI profile survives ----------


def test_flat_cli_profile_survives():
    """The flat migration-author.yml (CLI runtime) is NOT deleted — flat = CLI
    fallback, dir = AgentKit runtime, both coexist by design."""
    assert FLAT_PROFILE.is_file(), (
        "files/anatomy/agents/migration-author.yml (flat CLI profile) must survive — "
        "it is the CLI-runtime fallback"
    )
    flat = yaml.safe_load(FLAT_PROFILE.read_text())
    assert flat.get("name") == "migration-author", (
        "the flat profile must still name the migration-author agent"
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
