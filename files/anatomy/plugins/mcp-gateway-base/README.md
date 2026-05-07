# mcp-gateway-base — content batch (Q5)

> **Status:** live, captured 2026-05-07. Wires `pazny.mcp_gateway` (mcpo)
> into the plugin loader. Forward-auth at the Traefik layer; bearer-key
> auth at the app level. Tier 3 (user) — operator-facing tool surface
> for OpenWebUI agents.

## What this plugin owns

| Surface | Block | Notes |
|---|---|---|
| Health probe | `lifecycle.post_compose.wait_health` | `/docs` endpoint; tolerant of 4xx behind bearer |
| Loki labels | `observability.loki.labels` | `app=mcpo, stack=iiab, tier=3` |
| GDPR Article 30 row | `gdpr:` | `legitimate_interests`, retention 30d |
| Wing /hub deep-link card | `ui-extension.hub_card` | Operator entry point to mcpo OpenAPI docs |

## What stays in the role

`roles/pazny.mcp_gateway/` keeps install responsibilities — image pin,
port defaults, mcpo `config.json` render, Postgres read-only role bootstrap,
Grafana service-account token wiring, sibling Grafana MCP SSE container.
This plugin layers cross-cutting wiring (health, telemetry, hub) on top.

## SSO posture

mcpo has **no native OIDC**. Authentication is bearer-key at the app
level (`--api-key` flag, consumed by OpenWebUI via
`TOOL_SERVER_CONNECTIONS`). Operator access through the browser is gated
by the Authentik forward-auth Traefik middleware (`authentik@file`),
applied at the proxy layer rather than per-plugin. No `authentik:` block
in this manifest — forward-auth bindings live in
`roles/pazny.traefik/` configuration.

## Activation

Activates when `install_mcp_gateway: true` is set in `config.yml`.
Also implicitly requires Open WebUI (which consumes mcpo as a tool
server). The role auto-enables the Postgres MCP read-only user via
`tasks/post.yml`.
