"""The architect writes a recipe; something OTHER than the architect opens the MR.

Two halves, and the split is the point. `upgrade-architect/system.md` has always
instructed the agent to write `upgrades/<service>.yml` and open a merge request —
while its tools were `bash-read-only` + `mcp-wing`, neither of which can write a
file or run a script. The prompt asked for something the runtime forbade, which
is the same shape as `spine-tools-vs-cli-refusal`: three correct decisions and no
path through them.

What is pinned:

  1. `MigrationWriteTool` accepts `upgrades/<service>.yml` and still refuses a
     path outside its allowlist — exercised against the real PHP, not read off
     the source, because an allowlist that is only described is not one.
  2. The agent has no forge tool. A session that can push is a session that can
     merge its own work, so the MR is opened by the RUNNER, from what the write
     tool recorded (`metadata.path_written`) rather than from the model's own
     account of what it wrote.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
WING = REPO / "files/anatomy/wing"
RUNNER = REPO / "tools/run-agent.sh"
ARCHITECT = REPO / "files/anatomy/agents/upgrade-architect/agent.yml"

PROBE = r"""
require __DIR__ . '/vendor/autoload.php';

use App\AgentKit\Tools\MigrationWriteTool;
use App\AgentKit\Tools\ToolContext;

$root = sys_get_temp_dir() . '/nos-write-probe-' . bin2hex(random_bytes(4));
mkdir($root . '/upgrades', 0700, true);
mkdir($root . '/files/anatomy/migrations', 0700, true);
touch($root . '/default.config.yml');

$tool = new MigrationWriteTool($root);
$ctx = new ToolContext('s-1', 'th-1', 't-1', 'sp-1', 'probe', 'tu-1');
$out = [];
foreach ([
    'recipe'   => 'upgrades/gitlab.yml',
    'nested'   => 'upgrades/deep/gitlab.yml',
    'outside'  => 'roles/pazny.wing/defaults/main.yml',
] as $label => $path) {
    $r = $tool->execute(['path' => $path, 'content' => "id: x\n"], $ctx);
    $out[$label] = ['error' => $r->isError, 'path_written' => $r->metadata['path_written'] ?? null];
}
$out['on_disk'] = file_exists($root . '/upgrades/gitlab.yml');
echo json_encode($out);
"""


def _probe() -> dict:
    probe = WING / "write-probe.php"
    probe.write_text("<?php\n" + PROBE, encoding="utf-8")
    try:
        out = subprocess.run(["php", probe.name], cwd=WING,
                             capture_output=True, text=True, timeout=60)
    finally:
        probe.unlink(missing_ok=True)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


# Only the probe needs php+vendor; the yaml/shell gates below keep running.
# In a declaring environment the contract aborts instead — this skip is honest
# only on a fresh worktree with no NOS_TEST_PROVIDES.
@pytest.mark.skipif(
    shutil.which("php") is None or not (WING / "vendor/autoload.php").is_file(),
    reason="php binary or wing vendor/autoload.php missing — run `composer "
           "install` in files/anatomy/wing",
)
def test_a_recipe_path_is_writable_and_everything_else_is_not() -> None:
    got = _probe()
    assert got["recipe"]["error"] is False, "upgrades/<service>.yml must be writable"
    assert got["recipe"]["path_written"] == "upgrades/gitlab.yml"
    assert got["on_disk"] is True, "the tool reported success without writing"
    assert got["nested"]["error"] is True, "a nested recipe path must be refused"
    assert got["outside"]["error"] is True, "the allowlist no longer refuses an outside path"


def test_the_architect_can_write_but_cannot_push() -> None:
    doc = yaml.safe_load(ARCHITECT.read_text(encoding="utf-8"))
    tools = {t["id"] for t in doc["tools"]}
    assert "migration-file-write" in tools, "the architect cannot write its own recipe"
    assert "nos.migration.write" in doc["audit"]["capability_scopes"], (
        "the registry refuses to load the write tool without its scope"
    )
    forbidden = {"forge", "git", "shell", "bash"} & {t.split("-")[0] for t in tools}
    assert forbidden <= {"bash"}, f"the architect holds a push-capable tool: {forbidden}"
    assert "bash-read-only" in tools or "bash" not in forbidden


def test_the_runner_opens_the_mr_from_what_the_tool_recorded() -> None:
    src = RUNNER.read_text(encoding="utf-8")
    assert "recipe-pr.sh" in src, "no MR post-step — a written recipe would sit in the tree"
    assert "path_written" in src, (
        "the post-step does not read the write tool's own record; deriving the "
        "path from the model's prose is trusting the thing being audited"
    )
    assert "--open-pr" in src
    # Recipes only — a migration MR needs its version bump in the same MR.
    assert "'upgrades/%'" in src or "upgrades/%" in src
