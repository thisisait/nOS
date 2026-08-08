"""`uvx <pkg>` fetches the latest of everything, every time it runs.

WHAT HAPPENED, measured 2026-08-08. Three of Hermes's five MCP servers were
dead on every start, and had been for as long as anyone had looked:

    ImportError: cannot import name 'McpError' from 'mcp.shared.exceptions'
                 (...) Did you mean: 'MCPError'?
    ERROR:mcp_server_git.server:/Users/pazny/projects is not a valid Git repository

The `mcp` SDK reached **2.0.0** and renamed `McpError` -> `MCPError`.
`mcp-server-time` and `mcp-server-fetch` still import the old name. Because the
role invoked them as bare `uvx mcp-server-time`, uv re-resolved the dependency
set on EVERY start and was guaranteed to pair a stale server with a new SDK.
Nothing in the estate pinned it, and nothing noticed: `hermes doctor` printed
the tracebacks and then reported "Found 3 issue(s)", none of which was "three of
your MCP servers crash on startup". The failures were above the summary; the
summary was calm. The estate's oldest defect, this time inside someone else's
tool.

WHAT THIS GATE PINS, and what it deliberately does not.

It pins the CLASS — an unpinned `uvx` invocation — not the specific `mcp<2`
bound, which will be wrong the day those servers catch up. A pin that is merely
present is enough; choosing it is a human's job. The gate's message says so, so
that whoever hits it does not just widen the regex.

It cannot check that the git repository path is a real working tree: that is a
runtime property of the operator's machine. `hermes_git_repository` defaults to
`playbook_dir`, which is a git tree by construction — the previous value,
`~/projects`, was the PARENT of the repo and had never been one.

THE `npx` SERVERS ARE NOT COVERED, on purpose. They have not broken, and a pin
nobody has a reason for is a maintenance burden wearing the costume of rigour.
When one of them breaks the same way, add it here with the evidence.
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
DEFAULTS = REPO / "roles/pazny.hermes/defaults/main.yml"


def mcp_servers() -> list[dict]:
    # The defaults carry `{{ ... }}` Jinja, which is fine for a YAML load —
    # they are just strings until Ansible renders them.
    doc = yaml.safe_load(DEFAULTS.read_text(encoding="utf-8"))
    servers = doc.get("hermes_mcp_servers")
    assert isinstance(servers, list) and servers, (
        "roles/pazny.hermes/defaults/main.yml no longer defines "
        "hermes_mcp_servers as a non-empty list."
    )
    return servers


def test_every_uvx_server_pins_its_dependency_set():
    """The bare form re-resolves on every start and WILL break again."""
    unpinned = []
    for srv in mcp_servers():
        if srv.get("command") != "uvx":
            continue
        args = [str(a) for a in (srv.get("args") or [])]
        if "--with" not in args and not any(
            a.startswith("--from") or "==" in a or "<" in a or ">" in a for a in args
        ):
            unpinned.append(srv.get("name"))
    assert not unpinned, (
        f"uvx MCP server(s) with no pin: {unpinned}.\n"
        "`uvx <pkg>` resolves the LATEST of the package AND its dependencies on "
        "every invocation, so an upstream major release breaks the server "
        "silently at next start.\n"
        "Add a bound (`--with 'mcp<2'` is the current one) — but CHOOSE it "
        "rather than copying: the right bound is whatever these servers were "
        "actually written against, and it changes when they catch up."
    )


def test_the_git_server_is_pointed_at_a_variable_not_a_guess():
    """The path must be configurable, because it was wrong as a literal.

    `~/projects` is the parent of the repository. mcp-server-git logged
    `not a valid Git repository` on every start and answered nothing, for as
    long as it had been configured.
    """
    servers = {s.get("name"): s for s in mcp_servers()}
    git = servers.get("git")
    assert git is not None, "the git MCP server was removed — if deliberate, delete this test"
    args = [str(a) for a in (git.get("args") or [])]
    assert "--repository" in args, "the git server no longer takes --repository"
    path = args[args.index("--repository") + 1]
    assert "{{" in path, (
        f"the git repository path is the literal {path!r}. It must come from a "
        "variable an operator can set; the last literal pointed one directory "
        "above the repository and nothing ever read it."
    )
    assert "/projects'" not in path and not path.rstrip("}").rstrip().endswith("/projects"), (
        "the git repository path still resolves to ~/projects, which is the "
        "PARENT of the repo and not a git working tree."
    )


def test_the_breakage_is_recorded_where_the_pin_lives():
    """A bound with no reason gets widened by the next person who hits it."""
    src = DEFAULTS.read_text(encoding="utf-8")
    assert "McpError" in src and "MCPError" in src, (
        "the defaults no longer record WHY the uvx servers are pinned. The "
        "next reader sees an arbitrary-looking bound and relaxes it."
    )
