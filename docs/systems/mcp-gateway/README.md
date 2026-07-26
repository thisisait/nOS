# MCP Gateway (mcpo)

> mcpo — an MCP-to-OpenAPI proxy. It wraps several Model Context Protocol servers behind a single bearer-authenticated OpenAPI surface that Open WebUI (and other tool clients) consume.

## Quick Reference

| | |
|---|---|
| **URL** | `https://mcp.<tenant_domain>` (derived from `mcpo_domain`; default `mcp.dev.local`) |
| **Host port** | `127.0.0.1:8765` → container `8000` (`mcpo_port`) |
| **Stack** | `iiab` |
| **Toggle** | `install_mcp_gateway: false` (default; requires Open WebUI) |
| **Image** | `ghcr.io/open-webui/mcpo:main` (`mcpo_image` + `mcpo_version: main`) |
| **Data** | `{{ nos_data_root }}/platform/services/mcpo/data` (holds `config.json` + `data/`; default `~/nos/platform/services/mcpo/data`) |
| **Container** | `iiab-mcpo-1` (compose service `mcpo`) |
| **Manifest node** | `nos.iiab.mcp-gateway` |

## Authentication

- **App-level auth:** bearer API key. mcpo starts with `--api-key <mcpo_api_key>`; `mcpo_api_key` = `{global_password_prefix}_pw_mcpo`. Open WebUI presents it as `Authorization: Bearer <key>`.
- **SSO bucket:** `forward_auth` at the Traefik edge (no per-plugin OIDC client — Track Q5 doctrine). The bearer key is the app layer; the Authentik forward-auth middleware is the edge layer.

## Wrapped MCP servers

Configured via `config.json`; each is toggled independently (all default `true`):

| Server | Purpose | Exposure |
|--------|---------|----------|
| `time` | timezone-aware datetime | uvx mcp-server-time |
| `memory` | persistent notes | npx server-memory |
| `fetch` | HTTP fetching | uvx mcp-server-fetch |
| `filesystem` | read-only paths (`mcp_filesystem_paths` → `/data/readonly/*`) | npx server-filesystem |
| `git` | read-only local repos (`mcp_git_repo_path` → `/data/repos`) | uvx mcp-server-git |
| `postgres` | read-only DB queries (user `mcp_readonly`) | npx server-postgres |
| `grafana` | Grafana dashboards/queries | SSE sibling container `mcp-grafana` |

## Health Check

- **Plugin `wait_health`:** `GET /docs` accepting `2xx`/`3xx`/`4xx` (behind the bearer key, `/docs` may 401 — still live).
- **Container healthcheck:** TCP liveness on internal `:8000` (`:>/dev/tcp/127.0.0.1/8000`), auth-independent.

## Dependencies

- Open WebUI (the primary consumer, via `TOOL_SERVER_CONNECTIONS`).
- PostgreSQL (read-only `mcp_readonly` role, when the postgres server is enabled).
- Grafana (when the grafana server is enabled — service-account token wired in `post.yml`).
- Traefik + Authentik (edge forward-auth, optional).
