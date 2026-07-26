# Hermes — Skills

> Callable actions for Hermes. All are CLI verbs of the `hermes` binary in the
> role venv (`~/agents/hermes/.venv/bin/hermes`). The FastAPI dashboard is a
> loopback web UI, not a documented agent-facing REST API, so the skills below
> are command-based.

## Invocation

- **Method:** CLI (`hermes <verb>`), run on the host as the operator user.
- **Binary:** `~/agents/hermes/.venv/bin/hermes` (or `hermes` if the venv bin is on PATH).
- **Config:** `~/.hermes/` (model, MCP servers, skills, FTS5 memory).

---

## start-dashboard

**Trigger:** "start the hermes dashboard", "bring hermes web ui online", "open hermes dashboard"
**Method:** CLI
**Command:** `hermes dashboard --host 127.0.0.1 --port 18790 --no-open`
**Effect:** Starts the FastAPI web UI bound to loopback `18790`. When `hermes_daemon_mode: true` the launchd unit runs exactly this verb; otherwise run it manually.

---

## chat

**Trigger:** "chat with hermes", "interactive hermes session", "open hermes chat"
**Method:** CLI
**Command:** `hermes chat`
**Effect:** Opens the interactive chat TUI against the primary model (`hermes3:8b`), with terminal/file/web toolsets and delegation to `qwen2.5-coder:32b` for heavy tasks.

---

## serve-mcp

**Trigger:** "expose hermes as an mcp server", "run hermes mcp", "serve hermes conversations over mcp"
**Method:** CLI
**Command:** `hermes mcp serve`
**Effect:** Exposes Hermes conversations/tools as an MCP server so other MCP clients can consume them.

---

## add-mcp-server

**Trigger:** "add an mcp server to hermes", "register a new mcp tool"
**Method:** CLI
**Command:** `hermes mcp add <name> --command <cmd> [args...]`
**Effect:** Registers a new MCP server in the Hermes config (interactive alternative to editing `mcp_servers` in the CLI config).

---

## install-gateway

**Trigger:** "install the hermes cross-channel gateway", "connect telegram to hermes", "set up hermes messaging"
**Method:** CLI
**Command:** `hermes gateway install`
**Effect:** Installs the launchd plist for cross-channel messaging (Telegram/Discord/Signal). This stays a deliberate manual step — it is never auto-fired by a playbook run.
