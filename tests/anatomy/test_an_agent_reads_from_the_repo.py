"""An agent's relative paths must mean what the task author meant.

MEASURED 2026-08-16, on the first cycle where a MODEL authored the diff.

The task said: read `docs/llm/security/remediation-queue.json`, read
`default.config.yml`, emit a one-line diff. Every path missed:

    jq   … remediation-queue.json  -> No such file or directory
    grep … default.config.yml      -> No such file or directory
    pwd                            -> /Users/pazny/wing/app

`BashReadOnlyTool` spawned with `proc_open($argv, …, null, $env)` — a null cwd,
which inherits the Wing daemon's own directory. Every agent task in this estate
is written against the CHECKOUT, so the agent spent **63,112 input tokens**
exploring the filesystem and hit its ceiling having read nothing it was asked
about. The measurement that run was supposed to produce — what a cycle costs —
measured the cost of being lost instead.

WHY IT HID: nothing was broken. The tool worked, the verbs were allowed, the
guards held, the errors were honest. The environment simply pointed somewhere
no task refers to, and an agent that cannot find a file looks exactly like an
agent working on a hard problem.

WHAT IS PINNED: that the tool anchors to `NOS_REPO_ROOT` and falls back to
inheriting only when it is unset — the state `tools/run-agent.sh` refuses to
start in, so on the supervised path the fallback is unreachable.
"""

from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
TOOL = REPO / "files/anatomy/wing/app/AgentKit/Tools/BashReadOnlyTool.php"


def _src() -> str:
    return TOOL.read_text(encoding="utf-8")


def test_the_spawn_site_is_still_the_one_this_gate_describes():
    """Positive control — a renamed spawn would make the check below vacuous."""
    src = _src()
    assert src.count("proc_open(") >= 1, "BashReadOnlyTool no longer spawns via proc_open"


def test_the_command_runs_in_the_repo_not_the_daemon_directory():
    src = _src()
    spawn = re.search(r"proc_open\(\s*\$argv[^;]*;", src)
    assert spawn, "the proc_open call is no longer recognisable"
    call = spawn.group(0)
    assert "$cwd" in call, (
        "proc_open's cwd argument is not a variable — if it is null again, "
        "every relative path in every agent task resolves against the Wing "
        "daemon's directory and misses."
    )
    assert "NOS_REPO_ROOT" in src, (
        "the tool no longer reads NOS_REPO_ROOT, so it cannot anchor anywhere."
    )


def test_an_absent_repo_root_falls_back_rather_than_crashing():
    """The wrapper refuses to start without NOS_REPO_ROOT, so this branch is
    unreachable on the supervised path — but a direct `php bin/run-agent.php`
    must not die inside a tool because an env var is missing."""
    src = _src()
    body = src[src.index("$cwd = getenv('NOS_REPO_ROOT');"):]
    body = body[: body.index("proc_open(")]
    assert "is_dir(" in body, (
        "the cwd is used without checking it exists; proc_open with a bad cwd "
        "fails the spawn and the agent gets a spawn error instead of a file."
    )
    assert ": null" in body, "there is no fallback when NOS_REPO_ROOT is unset"


def test_a_model_never_hand_writes_a_hunk_header():
    """The gap that turned a correct decision into an unjudgeable one.

    MEASURED 2026-08-16: the agent chose the right fix for the right reason and
    emitted a hunk claiming seven lines over a body of five. Both judges
    returned `indeterminate` — correctly, since a malformed patch is not a bad
    change but an unjudgeable one. `tools/loop-diff.py` moves the format burden
    off the model: it states FILE/OLD/NEW, the patch is built from the file on
    disk, and the tool REFUSES to emit one that does not `git apply --check`.
    Same decision, re-proposed as attempt 2: pass.
    """
    tool = REPO / "tools/loop-diff.py"
    assert tool.is_file(), "tools/loop-diff.py is gone"
    src = tool.read_text(encoding="utf-8")
    assert "git" in src and "apply" in src and "--check" in src, (
        "loop-diff.py no longer proves the patch applies before printing it; "
        "it would emit the same unjudgeable hunks the model did."
    )
    assert "matches" in src and "be specific" in src, (
        "the ambiguous-match refusal is gone. A replacement that could land in "
        "two places is a proposal nobody can review."
    )
