"""Anatomy CI gate — AgentKit naming consistency (A14, 2026-05-07).

Locks the naming surface so a refactor that renames part of the system
fails CI before it strands documentation, audit-log filters, or external
integrations that depend on the names.

Pinned contracts:
  * Tables: agent_sessions, agent_threads, agent_iterations,
    agent_vaults, agent_credentials, agent_subscriptions
  * PHP namespace: App\\AgentKit\\*
  * Agent directory layout: files/anatomy/agents/<name>/{agent.yml, ...}
  * URI separator: dash, not colon (anthropic-claude-opus-4-7)
  * Event types in EventRepository::VALID_TYPES include the A14 set
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
WING_APP = REPO_ROOT / "files" / "anatomy" / "wing" / "app"
SCHEMA_EXT = REPO_ROOT / "files" / "anatomy" / "wing" / "db" / "schema-extensions.sql"
EVENT_REPO = WING_APP / "Model" / "EventRepository.php"


def test_all_agentkit_tables_declared():
    """All six AgentKit tables exist in schema-extensions.sql."""
    sql = SCHEMA_EXT.read_text()
    for table in ("agent_sessions", "agent_threads", "agent_iterations",
                  "agent_vaults", "agent_credentials", "agent_subscriptions"):
        assert re.search(
            rf"CREATE TABLE IF NOT EXISTS\s+{re.escape(table)}\b",
            sql, re.IGNORECASE,
        ), f"schema-extensions.sql missing CREATE TABLE for {table}"


def test_php_namespace_is_App_AgentKit():
    """Every file under app/AgentKit/ declares App\\AgentKit\\... namespace.
    Nette PSR-4 autoloader requires this to match the directory layout."""
    root = WING_APP / "AgentKit"
    if not root.is_dir():
        pytest.skip("app/AgentKit not present yet")
    failures = []
    for php in root.rglob("*.php"):
        rel = php.relative_to(WING_APP / "AgentKit").parent
        expected_ns = "App\\AgentKit"
        if str(rel) != ".":
            expected_ns += "\\" + str(rel).replace("/", "\\")
        src = php.read_text()
        if f"namespace {expected_ns};" not in src:
            failures.append(f"{php.relative_to(REPO_ROOT)}: expected `namespace {expected_ns};`")
    assert not failures, "namespace mismatches:\n  - " + "\n  - ".join(failures)


def test_event_repository_carries_agentkit_types():
    """A14 added 12 agent_* event types. Locking them so a removal is loud."""
    src = EVENT_REPO.read_text()
    required = [
        "agent_session_start", "agent_session_end",
        "agent_thread_start", "agent_thread_end",
        "agent_iteration_start", "agent_iteration_end",
        "agent_tool_use", "agent_tool_result",
        "agent_message", "agent_grader_decision",
        "agent_webhook_dispatch", "agent_vault_resolved",
    ]
    for ev in required:
        assert f"'{ev}'" in src, (
            f"EventRepository::VALID_TYPES missing '{ev}' (A14 contract)"
        )


def test_uri_scheme_uses_dash_separator():
    """Conductor agent (and all built-in agents) declare model URIs with
    dashes between provider and model id. Not colons. The schema regex
    pins this; we double-check on the conductor agent.yml to avoid silent
    drift."""
    conductor = REPO_ROOT / "files" / "anatomy" / "agents" / "conductor" / "agent.yml"
    if not conductor.is_file():
        pytest.skip("conductor agent.yml not present yet")
    src = conductor.read_text()
    # Must have a `primary:` line whose value matches the dash scheme.
    m = re.search(r"^\s*primary:\s*(\S+)", src, re.MULTILINE)
    assert m, "conductor agent.yml has no model.primary"
    primary = m.group(1).strip().strip('"').strip("'")
    assert re.match(r"^(anthropic|openclaw|openai|local)-[a-z0-9.-]+$", primary), (
        f"conductor model.primary '{primary}' violates dash-separator scheme"
    )


def test_runner_emits_required_audit_events():
    """Static check that Runner.php fires the canonical lifecycle events.
    Doesn't run PHP; just regex-greps to lock the contract."""
    runner = WING_APP / "AgentKit" / "Runner.php"
    if not runner.is_file():
        pytest.skip("Runner.php not present yet")
    src = runner.read_text()
    required_emits = [
        "'agent_session_start'",
        "'agent_session_end'",
        "'agent_message'",
        "'agent_tool_use'",
        "'agent_tool_result'",
    ]
    for ev in required_emits:
        assert ev in src, (
            f"Runner.php no longer emits {ev} — audit lineage broken"
        )


def test_llm_client_protocol_is_minimal():
    """The LLMClientInterface contract is deliberately small. If a method is
    added, both adapters must implement it. This test asserts the surface
    has exactly two methods (identifier, send) so accidental scope creep
    surfaces as a code review concern, not a hidden lock-in."""
    iface = WING_APP / "AgentKit" / "LLMClient" / "LLMClientInterface.php"
    if not iface.is_file():
        pytest.skip("LLMClientInterface.php not present")
    src = iface.read_text()
    methods = re.findall(r"public function (\w+)\(", src)
    assert sorted(methods) == ["identifier", "send"], (
        f"LLMClientInterface surface drifted: {methods}. "
        "If you add a method, update test + both adapters."
    )


def test_anthropic_and_openclaw_adapters_implement_interface():
    """Both adapters declare `implements LLMClientInterface`. Without this
    Factory::fromUri can't return a typed value."""
    for adapter in ("AnthropicAdapter.php", "OpenClawAdapter.php"):
        path = WING_APP / "AgentKit" / "LLMClient" / adapter
        if not path.is_file():
            pytest.skip(f"{adapter} not present yet")
        src = path.read_text()
        assert "implements LLMClientInterface" in src, (
            f"{adapter} must `implements LLMClientInterface` to honour the protocol"
        )
