# MCP Gateway — Skills

> Callable actions for mcpo. The surface is a bearer-authenticated OpenAPI proxy over the wrapped MCP servers.

## Authentication

- **Bearer key:** `Authorization: Bearer <mcpo_api_key>`, where `mcpo_api_key` = `{global_password_prefix}_pw_mcpo` (set on the container via `--api-key`).
- **Base URL:** `https://mcp.<tenant_domain>` (loopback `http://127.0.0.1:8765`).
- **Edge:** additionally behind Authentik forward-auth at the Traefik perimeter.

---

## get-openapi-spec

**Trigger:** "list available MCP tools", "what can mcpo do", "get the OpenAPI spec"
**Method:** API (bearer)
**Endpoint:** `GET /docs` (interactive) / `GET /openapi.json` per sub-app
**Input:** none beyond the bearer header.
**Output:** the OpenAPI description. mcpo mounts each enabled MCP server as its own OpenAPI sub-application (named after the server — `time`, `memory`, `fetch`, `filesystem`, `git`, `postgres`, `grafana`); the exact operations of each are self-described there. Discover routes from the spec rather than hard-coding them, since the set follows `config.json`.

---

## invoke-tool

**Trigger:** "call the [time/fetch/memory/git/...] MCP tool", "run an MCP operation through mcpo"
**Method:** API (bearer)
**Endpoint:** `POST /<server>/<operation>` — the concrete path and body come from the OpenAPI spec of the target sub-application (see `get-openapi-spec`).
**Input:** JSON body matching the operation's schema; `Authorization: Bearer <mcpo_api_key>`.
**Output:** the wrapped MCP tool's result as JSON.

**Notes on the read-only servers:**
- `filesystem` exposes only the paths in `mcp_filesystem_paths` (mounted read-only at `/data/readonly/*`).
- `git` exposes only `mcp_git_repo_path` (mounted read-only at `/data/repos`).
- `postgres` runs as the read-only role `mcp_readonly`.
