"""`tools/stale-config-status.py` reports; it never restarts anything.

The tool's whole value is that an operator or a converge can run it without
weighing consequences first. A reader that might restart a container is a
reader nobody runs on a live estate, and then the state it was built to surface
goes back to being invisible.

Same contract as `test_the_red_reader_only_reads.py`, for the same reason: it
must also exit 0 whatever it finds. A stale container is a report, not this
tool's verdict, and a non-zero exit would make every caller treat "found
something" as "the tool broke".
"""

from __future__ import annotations

import ast
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools/stale-config-status.py"

#: Anything that could change the estate. `docker` itself is allowed — the tool
#: has to ask — so the check is on the SUBCOMMAND, parsed out of the argument
#: list rather than grepped for, since a comment mentioning `docker restart` is
#: not a call to it.
FORBIDDEN_DOCKER_SUBCOMMANDS = {
    "restart", "stop", "kill", "rm", "start", "exec", "run", "compose", "update",
}


def _docker_calls(tree: ast.AST) -> list[list[str]]:
    """Every literal argv list handed to subprocess whose head is `docker`."""
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        first = node.args[0]
        if not isinstance(first, ast.List):
            continue
        argv = [e.value for e in first.elts if isinstance(e, ast.Constant)]
        if argv and argv[0] == "docker":
            found.append(argv)
    return found


def test_it_issues_no_mutating_docker_command() -> None:
    tree = ast.parse(TOOL.read_text(encoding="utf-8"))
    calls = _docker_calls(tree)
    assert calls, "no docker invocation found — the tool cannot be reading containers"
    for argv in calls:
        sub = argv[1] if len(argv) > 1 else ""
        assert sub not in FORBIDDEN_DOCKER_SUBCOMMANDS, (
            f"tools/stale-config-status.py runs `docker {sub}` — it is a reader, "
            "and a reader that mutates is one nobody dares run on a live estate")


def test_it_exits_zero_whatever_it_finds() -> None:
    proc = subprocess.run([sys.executable, str(TOOL), "--json"],
                          capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, (
        f"exited {proc.returncode}. Finding stale config is a REPORT, not a "
        f"failure of the tool.\nstderr: {proc.stderr[:400]}")
