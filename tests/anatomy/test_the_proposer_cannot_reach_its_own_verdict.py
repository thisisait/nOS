"""Constraint A, at the tool level — and the tool that made proposing possible.

TWO THINGS MEASURED 2026-08-29, both on the loop's entry.

FIRST, it could not act. `tools/loop-propose.py` was moved onto AgentKit that
morning, for reasons its own header gives at length: the old spawn was
`claude --print --permission-mode bypassPermissions`, so the loop's entry ran
under the operator's identity with no session row, no ceiling and no binding.
The runner moved and the CAPABILITY did not — `skills/propose/SKILL.md` tells
the agent to `curl` the engine, `curl` is on `BashReadOnlyTool`'s banned list,
and `McpBoneTool` says of itself that it has no write plane. `loop:propose`
exited 1 at 01:34 and, in its own words, "the run bought nothing".

SECOND, and this is what the new tool must never undo: in a self-improvement
loop the verdict is the reward signal for the next modification. A proposer that
can reach its own verdict does not merely lie — it optimises against the lie.
The engine enforces that with two tokens; this file enforces it one layer up,
where the model chooses, by refusing `judge` BY NAME with a reason rather than
leaving it out of a list and answering "unknown subcommand".

Everything below drives the real class through a spawn stub. The stub replaces
the PROCESS, never the allowlist: the refusal is computed before anything is
spawned, which is the only reason a stub is honest here.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
WING = REPO / "files/anatomy/wing"
AUTOLOAD = WING / "vendor/autoload.php"

pytestmark = pytest.mark.skipif(
    not AUTOLOAD.is_file(),
    reason="php binary or wing vendor/autoload.php missing — run `composer "
           "install` in files/anatomy/wing",
)

PROBE = r"""
require __DIR__ . '/vendor/autoload.php';

use App\AgentKit\Tools\McpLoopTool;
use App\AgentKit\Tools\ToolContext;

// Records what WOULD have been spawned, and always succeeds — so anything the
// output calls a refusal came from the tool's own gate, not from a failure.
$seen = [];
$spawn = function (array $argv) use (&$seen): array {
    $seen[] = $argv;
    return ['exit' => 0, 'stdout' => 'ok', 'stderr' => ''];
};

$tool = new McpLoopTool($spawn);
$ctx = new ToolContext('sess-42', 'th', 'tr', 'sp', 'agent:proposer', 'tu');

$out = ['scopes' => $tool->requiredScopes(), 'id' => $tool->id()];
foreach (['judge', 'judge-status', 'forget', 'weaknesses', 'budget', 'propose', 'nonsense'] as $sub) {
    $r = $tool->execute(['subcommand' => $sub, 'args' => ['--weakness', 'w-1']], $ctx);
    $out[$sub] = [
        'error' => $r->isError,
        'reason' => $r->metadata['refused_reason'] ?? null,
        'content' => mb_strcut($r->content, 0, 120, 'UTF-8'),
    ];
}
$out['spawned'] = $seen;
echo json_encode($out);
"""


def _probe() -> dict:
    p = WING / "loop-tool-probe.php"
    p.write_text("<?php\n" + PROBE, encoding="utf-8")
    try:
        out = subprocess.run(["php", p.name], cwd=WING, capture_output=True,
                             text=True, timeout=60)
    finally:
        p.unlink(missing_ok=True)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_judging_is_refused_by_name_with_a_reason() -> None:
    got = _probe()
    for sub in ("judge", "judge-status"):
        assert got[sub]["error"] is True, f"the proposer can run `{sub}`"
        assert got[sub]["reason"] == "subcommand_not_in_scope"
        assert "constraint A" in got[sub]["content"], (
            f"`{sub}` is refused without saying why; a refusal the model cannot "
            "understand is one it will try to route around"
        )


def test_forgetting_a_retry_block_is_refused() -> None:
    """`forget` lifts the loop's memory of having failed."""
    got = _probe()["forget"]
    assert got["error"] is True and got["reason"] == "subcommand_not_in_scope"


def test_the_proposing_half_actually_works() -> None:
    """A tool that only refuses is not the fix for a proposer that could not act."""
    got = _probe()
    for sub in ("weaknesses", "budget", "propose"):
        assert got[sub]["error"] is False, f"`{sub}` is refused; the proposer still cannot propose"
    assert any(a[:2] == ["nos-loop", "propose"] for a in got["spawned"])


def test_an_unknown_subcommand_is_refused_too() -> None:
    """The allowlist is a list, not a filter on the three named refusals."""
    got = _probe()["nonsense"]
    assert got["error"] is True and got["reason"] == "subcommand_not_in_scope"


def test_the_session_is_stamped_by_the_tool_not_asked_of_the_model() -> None:
    """A proposal that names a session the MODEL chose names whatever the model
    chose. Stamping it from the ToolContext is what makes the ledger join a fact
    — and every proposal on record before this carried session_uuid NULL."""
    spawned = [a for a in _probe()["spawned"] if a[:2] == ["nos-loop", "propose"]]
    assert spawned, "propose never reached the spawn"
    argv = spawned[0]
    assert "--session-uuid" in argv, "the proposal would be recorded nameless"
    assert argv[argv.index("--session-uuid") + 1] == "sess-42", (
        "the stamped session is not this session's"
    )


def test_the_scope_is_its_own() -> None:
    """`loop.propose`, not `bone.read`: a tool that can record an intent is not
    a read tool wearing a different name."""
    got = _probe()
    assert got["id"] == "mcp-loop"
    assert "loop.propose" in got["scopes"]
