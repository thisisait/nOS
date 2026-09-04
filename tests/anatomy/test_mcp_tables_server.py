"""Anatomy gate — the external DataTables MCP server (dtt harness, movement 4).

tools/mcp-tables-server.py is the stdio MCP server that hands Cursor / Codex /
Claude Code the same DataTables verbs the in-process McpTablesTool gives
AgentKit. Two consumers, ONE contract — so this gate pins that the two verb
sets are identical, that the server is stdlib-only (the tools/ no-deps
convention), and that its protocol shape holds via the script's own --selftest.

What it cannot see: a live round-trip to KEAP (the selftest routes every verb
without touching the network on purpose). That is the live estate's job, once
the KEAP door changes are committed and converged.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SERVER = REPO / "tools" / "mcp-tables-server.py"
TOOL_PHP = REPO / "files/anatomy/wing/app/AgentKit/Tools/McpTablesTool.php"


def _server_verbs() -> dict[str, str]:
    src = SERVER.read_text(encoding="utf-8")
    block = re.search(r"^VERBS = \{(.*?)^\}", src, re.DOTALL | re.MULTILINE)
    assert block, "mcp-tables-server.py must declare a VERBS map"
    return dict(re.findall(r'"([a-z-]+)": "(read|write)"', block.group(1)))


def _php_verbs() -> dict[str, str]:
    src = TOOL_PHP.read_text(encoding="utf-8")
    block = re.search(r"const VERBS = \[(.*?)\];", src, re.DOTALL)
    assert block, "McpTablesTool must declare a VERBS map"
    return dict(re.findall(r"'([a-z-]+)' => '(read|write)'", block.group(1)))


def test_selftest_passes():
    """The script's own protocol-shape check: initialize echoes the version,
    tools/list carries all eight verbs, a bad verb is a fail-soft tool error."""
    proc = subprocess.run(
        [sys.executable, str(SERVER), "--selftest"],
        capture_output=True, text=True, timeout=30,
    )
    assert proc.returncode == 0, f"selftest failed:\n{proc.stdout}\n{proc.stderr}"


def test_verb_parity_with_the_in_process_tool():
    """One contract, two consumers: the external server and McpTablesTool must
    expose the SAME verbs on the SAME planes, or an agent's habits do not carry
    between the two doors."""
    server, php = _server_verbs(), _php_verbs()
    assert server == php, (
        f"the DataTables verb surface diverged between the external MCP server "
        f"and the in-process tool.\n  server: {sorted(server.items())}\n  tool:   "
        f"{sorted(php.items())}"
    )


def test_the_server_is_stdlib_only():
    """tools/ scripts carry no third-party deps (the estate reader convention),
    and the `mcp` SDK in particular is deliberately not used."""
    src = SERVER.read_text(encoding="utf-8")
    imports = re.findall(r"^\s*(?:import|from)\s+([\w.]+)", src, re.MULTILINE)
    stdlib_roots = {"json", "os", "sys", "urllib", "__future__"}
    foreign = [m for m in imports if m.split(".")[0] not in stdlib_roots]
    assert not foreign, (
        f"mcp-tables-server.py imports non-stdlib module(s) {foreign}; the tools/ "
        "readers are stdlib-only, and MCP stdio is small enough to hand-roll"
    )
