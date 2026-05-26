"""Anatomy gate — AgentKit shipped-file manifest.

Many AgentKit tests guard each assertion with `pytest.skip("<file> not present
yet")` — a dev-era pattern from when the runtime was being built incrementally.
Now that AgentKit is SHIPPED (A14), that pattern silently turns a DELETED file
into a green *skip* instead of a failure, hiding a regression. This gate closes
the hole: the core AgentKit contract files MUST exist, or CI fails loudly.

Scope = the load-bearing contract surface the other AgentKit tests skip-guard
(LLM client interface + adapters, Coordinator/ProcessPool/Runner/Loader, the
Dreams memory subsystem, vault resolver, OTel exporter, the MCP tool, the
webhook dispatcher, the two CLIs, the conductor profile). Added 2026-05-26 in
the reality-vs-promises review.
"""

from __future__ import annotations

import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
AK = REPO / "files" / "anatomy" / "wing" / "app" / "AgentKit"
WING_BIN = REPO / "files" / "anatomy" / "wing" / "bin"

SHIPPED = [
    AK / "Agent.php",
    AK / "Coordinator.php",
    AK / "ProcessPool.php",
    AK / "Runner.php",
    AK / "AgentLoader.php",
    AK / "LLMClient" / "LLMClientInterface.php",
    AK / "LLMClient" / "AnthropicAdapter.php",
    AK / "LLMClient" / "OpenClawAdapter.php",
    AK / "Memory" / "Dreamer.php",
    AK / "Memory" / "MemoryStore.php",
    AK / "Vault" / "CredentialResolver.php",
    AK / "Telemetry" / "OtelExporter.php",
    AK / "Tools" / "McpWingTool.php",
    AK / "Webhook" / "WebhookDispatcher.php",
    WING_BIN / "run-agent.php",
    WING_BIN / "dream-agent.php",
    REPO / "files" / "anatomy" / "agents" / "conductor" / "agent.yml",
]


@pytest.mark.parametrize("path", SHIPPED, ids=lambda p: p.name)
def test_agentkit_shipped_file_present(path):
    assert path.is_file(), (
        f"AgentKit contract file missing: {path.relative_to(REPO)} — it is "
        "documented as SHIPPED, so its deletion must fail loudly here rather "
        "than silently green-skip the tests that guard it with skip('not present')."
    )
