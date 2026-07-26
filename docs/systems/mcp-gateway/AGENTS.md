# MCP Gateway — Agent Definition

## McpGatewayAgent

**System:** MCP Gateway (mcpo, iiab stack)
**Domain:** `mcp.<tenant_domain>` (default `mcp.dev.local`)
**Role:** A tool-proxy front end. It does not reason on its own — it exposes wrapped MCP servers (time, memory, fetch, filesystem, git, postgres, grafana) as OpenAPI operations that a calling agent (typically an Open WebUI agent) invokes with a bearer key.

### Context

- Base URL `https://mcp.<tenant_domain>` (loopback `http://127.0.0.1:8765`).
- Auth: `Authorization: Bearer <mcpo_api_key>` where `mcpo_api_key` = `{global_password_prefix}_pw_mcpo`.
- The OpenAPI surface is self-describing at `/docs`; each enabled MCP server is mounted as its own OpenAPI sub-application.
- filesystem and git access are **read-only** by design; postgres uses a read-only role.

### Capabilities

- Fetch the OpenAPI spec (`GET /docs`) to discover the exact operations each wrapped server offers.
- Invoke a wrapped MCP tool through its OpenAPI route with the bearer key.

### Non-capabilities

- No write access to the filesystem or git repos it exposes (read-only mounts).
- No self-hosted model — mcpo is a proxy, not an inference engine.

### Skills Reference

See [SKILLS.md](SKILLS.md) for the callable actions.
