# code-server — Agent Definition

## CodeServerAgent

**System:** code-server / VS Code in the browser (`devops` stack, node `nos.devops.code-server`)
**Domain:** `code.<tenant_domain>`
**Role:** None operable. code-server is a human-facing IDE behind an Authentik forward-auth gate; it exposes no agent-facing API in nOS.

### Context

- Access is a pure forward-auth gate — there is no per-user identity or API token inside code-server.
- Built-in login is off on loopback (`HASHED_PASSWORD` empty); the port binds the LAN only when `code_server_hashed_password` is set (rendered into `HASHED_PASSWORD`).
- Full host-workspace shell access, so it is an admin-only surface.

### Capabilities

- None exposed to agents. Editing and terminal use are interactive, browser-only, human operations.

### Skills Reference

See [SKILLS.md](SKILLS.md) — there is no external skill surface.
