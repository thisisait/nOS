"""A playbook-end hook that runs and fails must not be silent.

WHAT WAS FOUND, 2026-08-08, answering an unrelated question ("do we use
subprocess.run?"). `callback_plugins/wing_telemetry.py` dispatches every
executable in `hooks/playbook-end.d/` and did this:

    subprocess.run([path], ..., check=False, capture_output=True)

No assignment. `check=False` means no exception on a non-zero exit, and
`capture_output=True` means the hook's own diagnosis was read off the pipe and
dropped on the floor. The `except` clause below it reports a failure to SPAWN —
a missing file, a bad interpreter — which is the rarer half of what goes wrong.
A hook that started, ran, printed why it was unhappy and exited 3 produced
exactly nothing.

WHY THIS ONE MATTERS MORE THAN A TYPICAL SWALLOWED RETURN CODE. This is the same
surface as the 2026-07-28 CVE-drift saga, one layer up. There, the drift hook
aborted inside `jq` on an ISO-8601 spelling it could not parse, printed nothing,
and `conductor:security-drift-watch` had never once produced a verdict — at exit
0, for months. That fix repaired the hook and left this dispatcher exactly as it
was, so the next hook to die the same way would have been just as quiet. The
estate's rule is *a step that cannot do its job must not exit 0*; a dispatcher
that cannot hear a non-zero exit makes the rule unenforceable for everything
downstream of it.

WHAT IS DELIBERATELY UNCHANGED. The hook failure is still NON-FATAL. Telemetry
may never wedge a run — that is settled doctrine (`docs/doctrine/observability.md`,
written after an HMAC desync spilled 258 MB into /tmp and crawled a release
blank). The change is loudness, not lethality. If this gate is ever read as
licence to raise from a hook, read that doctrine first.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CALLBACK = REPO / "callback_plugins/wing_telemetry.py"


def _is_subprocess_run(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "run"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "subprocess"
    )


def test_the_hook_result_is_assigned():
    """A discarded result cannot be inspected, whatever the comments say.

    Located by AST so a comment claiming the return code is checked cannot
    satisfy this gate — the estate's standing rule that a comment is not
    evidence, applied to the test that enforces it.

    ONE parse, deliberately: the first draft of this file parsed the module
    twice and compared nodes across the two trees by identity, which can never
    match. It failed against the FIXED code and would have passed against
    nothing at all — a gate whose own method was the defect it was written to
    catch.
    """
    tree = ast.parse(CALLBACK.read_text(encoding="utf-8"))
    runs = [n for n in ast.walk(tree) if _is_subprocess_run(n)]
    assert len(runs) == 1, (
        f"expected exactly one subprocess.run in {CALLBACK.name}, found "
        f"{len(runs)}. If a second dispatcher was added it needs the same "
        "treatment — teach this gate about it rather than loosening the count."
    )
    assigned = {
        id(sub)
        for node in ast.walk(tree)
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.NamedExpr))
        and node.value is not None
        for sub in ast.walk(node.value)
    }
    assert id(runs[0]) in assigned, (
        "callback_plugins/wing_telemetry.py calls subprocess.run for "
        "playbook-end hooks and discards the result. With check=False and "
        "capture_output=True that makes a hook which RAN and FAILED completely "
        "silent — the 2026-07-28 drift-check defect, one layer up."
    )


def test_a_non_zero_exit_is_reported():
    """The returncode must actually be branched on, and say something."""
    src = CALLBACK.read_text(encoding="utf-8")
    tree = ast.parse(src)
    checks_rc = any(
        isinstance(node, ast.Attribute) and node.attr == "returncode"
        for node in ast.walk(tree)
    )
    assert checks_rc, (
        "nothing in wing_telemetry.py reads `.returncode`. Capturing a hook's "
        "output and never comparing its exit code is indistinguishable from "
        "not running it."
    )
    assert "exited %d" in src or "exited {" in src, (
        "the non-zero branch does not report the exit code. 'hook failed' "
        "without the code sends the reader back to the hook to guess; the "
        "whole point is that the dispatcher already knows."
    )


def test_the_hook_failure_stays_non_fatal():
    """Loud, not lethal — pinned so a later reader cannot 'improve' it.

    Telemetry wedging a converge is a fault the estate has already paid for
    once. The dispatcher may write to stderr and must not raise.
    """
    src = CALLBACK.read_text(encoding="utf-8")
    start = src.find("import subprocess")
    end = src.find("\n    def ", start)
    block = src[start : end if end != -1 else len(src)]
    for forbidden in ("raise ", "sys.exit(", "check=True"):
        assert forbidden not in block, (
            f"the hook dispatcher now contains `{forbidden.strip()}`. A failing "
            "hook must not be able to fail the run — see "
            "docs/doctrine/observability.md, written after telemetry crawled a "
            "release blank."
        )
