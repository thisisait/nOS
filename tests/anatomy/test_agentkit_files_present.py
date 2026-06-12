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
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
AK = REPO / "files" / "anatomy" / "wing" / "app" / "AgentKit"
WING_BIN = REPO / "files" / "anatomy" / "wing" / "bin"
COMMON_NEON = REPO / "files" / "anatomy" / "wing" / "app" / "config" / "common.neon"
# Nette sets %appDir% to the dir of the file that calls `new Configurator`,
# i.e. app/Bootstrap (see app/Bootstrap/Booting.php). The neon AgentLoader path
# is resolved relative to THIS dir, not the app/ root.
APP_DIR = REPO / "files" / "anatomy" / "wing" / "app" / "Bootstrap"
AGENTS_DIR = REPO / "files" / "anatomy" / "agents"
WING_TASKS = REPO / "roles" / "pazny.wing" / "tasks" / "main.yml"

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


def test_agentloader_neon_path_resolves_to_agents_dir():
    """The neon AgentLoader path must resolve to files/anatomy/agents.

    Regression guard for the 2026-05-26 off-by-one: the path was
    `%appDir%/../../agents`, which from the Bootstrap dir (%appDir%) lands on
    the nonexistent files/anatomy/wing/agents — so the Wing /agents catalog was
    always empty and every /agents/<name> detail/session 404'd, in dev AND on
    deployed hosts. The correct expression is `%appDir%/../../../agents`.
    """
    neon = COMMON_NEON.read_text(encoding="utf-8")
    # 2026-06-12: the loader consumes the named %agentsDir% parameter (so the
    # CLI bootstrap can override it — see test_agentkit_runner_paths.py); the
    # web-resolved default lives in the parameters block.
    assert "AgentLoader(%agentsDir%)" in neon, (
        "AgentLoader must consume the %agentsDir% parameter (CLI-overridable)"
    )
    m = re.search(r"agentsDir:\s*%appDir%/(\S+)", neon)
    assert m, "agentsDir: %appDir%/... parameter default not found in common.neon"
    resolved = (APP_DIR / m.group(1)).resolve()
    assert resolved == AGENTS_DIR.resolve(), (
        f"agentsDir default resolves to {resolved}, not {AGENTS_DIR}. The neon "
        f"default `%appDir%/{m.group(1)}` is wrong — %appDir% is the Bootstrap "
        "dir, so the agent definitions are three levels up + /agents."
    )
    assert (resolved / "conductor" / "agent.yml").is_file(), (
        "resolved agents dir has no conductor/agent.yml — the loader root is empty."
    )


def test_wing_role_deploys_agent_definitions():
    """The wing role must rsync files/anatomy/agents to the host.

    The repo layout (agents as a sibling of wing/) only holds on the deployed
    host if the role explicitly syncs the definitions — otherwise %appDir%/
    ../../../agents (= ~/wing/agents deployed) is empty and the catalog 404s
    even though the neon path is correct. Pins the deploy half of the fix.
    """
    tasks = WING_TASKS.read_text(encoding="utf-8")
    assert "files/anatomy/agents/" in tasks and "/agents/" in tasks, (
        "roles/pazny.wing/tasks/main.yml does not rsync files/anatomy/agents/ to "
        "the host — AgentLoader's deployed root (~/wing/agents) will be empty."
    )
