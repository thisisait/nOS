"""A pipe written as separate args gets a legible error, not git's.

MEASURED 2026-09-04, proposer session af942a1d (REM-249): the model reached for
a shell pipeline through the no-shell tool — `{verb: git, args: [log, "|",
grep, rustfs_]}` — and git answered `unknown command '|'`, which reads as git's
own failure rather than "there is no shell here". The proposer burned much of
its budget fumbling the tool shape and never reached `propose`.

The tool still runs one command with no shell (the security property is
untouched). It now RECOGNISES the habit: a standalone shell-operator token is
never a legitimate single argv element, so it is refused with a message that
says pipes/redirects do not work and to filter in a follow-up call. A `|` INSIDE
one arg (a grep pattern, a `--grep=a|b`) is not a standalone operator and is
left alone.

Executes the real tool. Retro: without the SHELL_OPERATORS check the pipe arg
reaches proc_open and the error is git's `unknown command`, not this one.
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

use App\AgentKit\Tools\BashReadOnlyTool;
use App\AgentKit\Tools\ToolContext;

$ctx = new ToolContext('s', 't', 'tr', 'sp', 'agent:test', 'tu');
$tool = new BashReadOnlyTool();

function run($tool, $ctx, array $input): array {
    $r = $tool->execute($input, $ctx);
    return ['is_error' => $r->isError, 'content' => $r->content];
}

$out = [];
// A pipe written as separate args.
$out['pipe_as_args'] = run($tool, $ctx,
    ['verb' => 'git', 'args' => ['log', '|', 'grep', 'rustfs_']]);
// A redirect operator.
$out['redirect'] = run($tool, $ctx,
    ['verb' => 'cat', 'args' => ['a.txt', '>', 'b.txt']]);
// A pipe INSIDE one arg — a legitimate grep pattern, must NOT be caught by the
// shell-operator rule (it may still fail for other reasons; we only assert the
// message is not the shell-habit one).
$out['pipe_in_one_arg'] = run($tool, $ctx,
    ['verb' => 'git', 'args' => ['log', '--grep=a|b', '--max-count=1']]);

echo json_encode($out);
"""


def _probe() -> dict:
    p = WING / "bash-shell-habit-probe.php"
    p.write_text("<?php\n" + PROBE, encoding="utf-8")
    try:
        out = subprocess.run(["php", p.name], cwd=WING, capture_output=True,
                             text=True, timeout=60)
    finally:
        p.unlink(missing_ok=True)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_a_pipe_written_as_args_is_named_not_run():
    got = _probe()["pipe_as_args"]
    assert got["is_error"] is True
    assert "no shell" in got["content"] and "follow-up" in got["content"], (
        "the pipe arg was not caught with a legible message — the model gets "
        "git's `unknown command` and reads it as git's fault")


def test_a_redirect_operator_is_named_too():
    got = _probe()["redirect"]
    assert got["is_error"] is True and "no shell" in got["content"]


def test_a_pipe_inside_one_arg_is_not_the_shell_habit():
    got = _probe()["pipe_in_one_arg"]
    # It may error for other reasons (running in the wing cwd), but never with
    # the shell-operator message — `a|b` inside one arg is a real pattern.
    assert "shell operator" not in got["content"], (
        "a `|` inside a single arg was wrongly rejected as a shell pipeline — "
        "grep patterns and --grep=a|b are legitimate")
