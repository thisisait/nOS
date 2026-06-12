"""Anatomy gate — AgentKit runner works under BOTH deploy nestings + FrankenPHP.

Two live failures from the 2026-06-12 release sweep (first time the AgentKit
native trigger paths were exercised on a deployed box — the pulse claude-CLI
runtime had masked them):

1. CLI `bin/run-agent.php` resolved the agents root via common.neon's
   ``%appDir%``-relative default. Nette derives %appDir% from the Configurator
   CALLER's directory, which differs between the web bootstrap
   (app/Bootstrap/Booting.php → resolves to <wing>/agents, correct) and the
   CLI (bin/ → resolved to <wing>/../agents → "agent.yml not found" on every
   deployed run). Fix: the CLI overrides ``agentsDir`` with
   ``__DIR__/../../agents`` — valid in the repo tree (files/anatomy/agents)
   AND the deployed tree (~/wing/agents).
2. The operator-trigger HTTP surface (POST /api/v1/agents/<name>/sessions)
   spawned the runner with ``PHP_BINARY`` as argv[0] — EMPTY under
   FrankenPHP's embedded SAPI → proc_open ValueError → 500. Fix: WING_PHP_BIN
   env → non-empty PHP_BINARY → executable brew/system php fallback.
"""

from __future__ import annotations

import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]
WING = REPO / "files" / "anatomy" / "wing"
RUN_AGENT = WING / "bin" / "run-agent.php"
COMMON_NEON = WING / "app" / "config" / "common.neon"
AGENTS_PRESENTER = WING / "app" / "Presenters" / "Api" / "AgentsPresenter.php"


def test_common_neon_uses_agents_dir_parameter():
    src = COMMON_NEON.read_text()
    assert "agentsDir: %appDir%/../../../agents" in src, (
        "common.neon lost the agentsDir parameter default — the CLI override "
        "in bin/run-agent.php keys off this parameter name."
    )
    assert "App\\AgentKit\\AgentLoader(%agentsDir%)" in src, (
        "AgentLoader must consume %agentsDir% (a named parameter the CLI can "
        "override), not an inline %appDir%-relative path."
    )


def test_run_agent_cli_overrides_agents_dir():
    src = RUN_AGENT.read_text()
    assert "addConfig(['parameters' => ['agentsDir' => __DIR__ . '/../../agents']])" in src, (
        "bin/run-agent.php must override agentsDir with __DIR__/../../agents — "
        "the %appDir%-relative neon default resolves to <wing>/../agents under "
        "the CLI bootstrap (deploy nesting) and every deployed run dies with "
        "'agent.yml not found'."
    )


def test_spawn_runner_never_uses_bare_php_binary():
    src = AGENTS_PRESENTER.read_text()
    assert "WING_PHP_BIN" in src, (
        "AgentsPresenter::spawnRunner lost the WING_PHP_BIN resolution — "
        "PHP_BINARY is empty under FrankenPHP's embedded SAPI and proc_open "
        "throws 'First element must contain a non-empty program name' (500 on "
        "every operator trigger)."
    )
    # argv[0] must come from the resolved $phpBin, never the raw constant.
    import re

    argv_blocks = re.findall(r"\$argv\s*=\s*\[\s*([^,]+),", src)
    assert argv_blocks, "no $argv array found in AgentsPresenter"
    for first in argv_blocks:
        assert first.strip() != "PHP_BINARY", (
            "argv[0] is the raw PHP_BINARY constant again — empty under "
            "FrankenPHP; use the resolved $phpBin."
        )
