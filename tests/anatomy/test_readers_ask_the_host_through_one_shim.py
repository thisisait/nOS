"""No tool under tools/ asks the host's service manager or socket table itself.

WHY. nOS runs on macOS (launchd) and Ubuntu (systemd --user) with the same
organ labels (docs/cross-platform.md: platform is a fact, not a toggle). Every
reader that called `launchctl`, `netstat`, `lsof` or `log` directly worked on
the Mac it was written on and died on the DGX Spark — `caddy-status.py` and
`permission-status.py` with a FileNotFoundError traceback in the control
centre, `undeclared-status.py` with two sources UNKNOWN for good. A
`systemctl` or `ss` call written beside them is the same fork the other way.

The structural fix is one shim, `tools/nos_host.py`, that answers per platform
(an organ's state by label, its definition and environment, its log, the
listening TCP ports with their owners). This gate keeps it the only place:

  * Python: an argv literal (list or tuple) whose first element is one of the
    host binaries, or a call whose first positional argument is one (the
    `_run("launchctl", "list")` spelling). AST, so a regex in a string that
    merely NAMES launchctl (prepush-score.py) is not a call.
  * Shell: a non-comment line that invokes one of them as a command word.

Shown red against dev 2026-10-22 (caddy, permission, thalamus, openhuman,
undeclared, red-status, app-slots, nos-ops-harness, run-agent.sh), green after
the readers moved onto the shim.
"""

from __future__ import annotations

import ast
import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
TOOLS = REPO / "tools"
SHIM = TOOLS / "nos_host.py"

#: The host's service managers, socket tables and the macOS unified log.
HOST_BINARIES = {"launchctl", "netstat", "lsof", "log", "systemctl", "journalctl", "ss"}

#: Limbs that ACT on a host, with the reason. The shim only reads; a tool that
#: starts or stops something is not a reader and does not belong in it.
ACTS = {
    "tools/cloud/bootstrap.sh": "starts dockerd inside a fresh cloud sandbox (docs/cloud-e2e.md)",
}

SHELL_CALL = re.compile(
    r"(^|[\s;&|(`$])(launchctl|netstat|lsof|systemctl|journalctl)(\s|$)"
    r"|(^|[\s;&|(`$])log\s+(show|stream|collect)\b"
    r"|(^|[\s;&|(`$])ss\s+-")


def _first_const(node: ast.AST) -> str | None:
    if isinstance(node, (ast.List, ast.Tuple)) and node.elts:
        head = node.elts[0]
        if isinstance(head, ast.Constant) and isinstance(head.value, str):
            return head.value
    return None


def python_offenders(path: pathlib.Path) -> list[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return []
    hits = []
    for node in ast.walk(tree):
        # ["launchctl", "print", ...] / ("netstat", "-an") — an argv literal.
        if isinstance(node, (ast.List, ast.Tuple)) and len(node.elts) >= 2:
            name = _first_const(node)
            if name in HOST_BINARIES:
                hits.append(f"{path.relative_to(REPO)}:{node.lineno} argv [{name!r}, ...]")
        # _run("launchctl", "list") — the varargs spelling.
        if isinstance(node, ast.Call) and node.args:
            a0 = node.args[0]
            if (isinstance(a0, ast.Constant) and a0.value in HOST_BINARIES and len(node.args) >= 2
                    and all(isinstance(a, ast.Constant) for a in node.args[:2])):
                hits.append(f"{path.relative_to(REPO)}:{node.lineno} call ({a0.value!r}, ...)")
    return hits


def shell_offenders(path: pathlib.Path) -> list[str]:
    hits = []
    for n, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        code = line.split("#", 1)[0] if not line.lstrip().startswith("#") else ""
        # echo/printf text names a tool for a human; it does not run it.
        if re.match(r"\s*(echo|printf)\b", code):
            continue
        if SHELL_CALL.search(code):
            hits.append(f"{path.relative_to(REPO)}:{n} {code.strip()[:80]}")
    return hits


def test_the_shim_is_the_only_tool_that_asks_the_host():
    offenders = []
    for path in sorted(TOOLS.rglob("*.py")):
        if path != SHIM and "__pycache__" not in path.parts:
            offenders += python_offenders(path)
    for path in sorted([*TOOLS.rglob("*.sh"), *TOOLS.rglob("*.bash")]):
        if str(path.relative_to(REPO)) not in ACTS:
            offenders += shell_offenders(path)
    assert not offenders, (
        "a tool calls a host service-manager / socket / log binary directly — on the "
        "other platform that is a FileNotFoundError or a source UNKNOWN forever. Ask "
        "tools/nos_host.py (service_state, service_definition, service_env, "
        "service_log, loaded_services, unit_files, listeners, sockets, unified_log):\n  "
        + "\n  ".join(offenders))


def test_the_gate_sees_both_spellings(tmp_path):
    """The detector itself, against the shapes it must catch and must not."""
    py = tmp_path / "x.py"
    py.write_text(
        'import subprocess\n'
        'subprocess.run(["launchctl", "print", "gui/1/x"])\n'
        '_run("netstat", "-anv")\n'
        'PATTERN = r"launchctl\\s+(load|bootstrap)"\n'
        'src = "lsof -nP -i"\n')
    global REPO
    saved, REPO = REPO, tmp_path
    try:
        hits = python_offenders(py)
        sh = tmp_path / "x.sh"
        sh.write_text('# launchctl print in a comment\n'
                      'echo "launchctl is not here"\n'
                      'X="$(launchctl print gui/1/x)"\n'
                      'log show --last 1d\n'
                      'ss -ltn\n'
                      'logger -t x hi\n')
        sh_hits = shell_offenders(sh)
    finally:
        REPO = saved
    assert len(hits) == 2, hits
    assert [h.split(":")[1].split()[0] for h in sh_hits] == ["3", "4", "5"], sh_hits
