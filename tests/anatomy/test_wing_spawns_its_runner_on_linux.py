"""Wing on Linux names the PHP CLI that runs bin/run-agent.php.

mini (2026-11-02): every agent session POST answered 500 "No PHP CLI binary found
for the agent runner (set WING_PHP_BIN)" and the face BFF turned it into a 502.
FrankenPHP's PHP_BINARY is empty, Ubuntu has no /usr/bin/php, and wing.env never
set WING_PHP_BIN. The PHP CLI there is the nos-php shim (wing_php_cli).
CEILING: names, not the running env; the effect is a 202 from POST /agents/<a>/sessions.
"""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ENVFILE = REPO / "roles/pazny.wing/templates/wing.env.j2"
TRIGGER = REPO / "files/anatomy/wing/app/AgentKit/OperatorTrigger.php"


def test_wing_env_names_the_php_cli():
    env = ENVFILE.read_text(encoding="utf-8")
    assert re.search(r"^WING_PHP_BIN=\{\{ wing_php_cli \}\}$", env, re.M), (
        "wing.env.j2 does not set WING_PHP_BIN={{ wing_php_cli }}: Wing on Linux cannot spawn an agent")


def test_the_trigger_reads_it_first():
    assert "$phpBin = getenv('WING_PHP_BIN') ?:" in TRIGGER.read_text(encoding="utf-8"), (
        "OperatorTrigger no longer resolves WING_PHP_BIN first: re-point this gate")


def test_wing_php_cli_on_linux_is_the_shim_the_role_installs():
    cfg = (REPO / "default.config.yml").read_text(encoding="utf-8")
    line = next(x for x in cfg.splitlines() if x.startswith("wing_php_cli:"))
    assert "/.local/bin/nos-php" in line, line
    tasks = (REPO / "roles/pazny.wing/tasks/main.yml").read_text(encoding="utf-8")
    assert "/.local/bin/nos-php\"" in tasks and "php-cli \"$@\"" in tasks, "pazny.wing no longer installs nos-php"
