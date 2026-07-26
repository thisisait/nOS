# Traefik — Agent Definition

## TraefikEdge

**System:** Traefik (`nos.infra.traefik`, infra stack)
**Edge:** binds `:80`/`:443` publicly; dashboard/API on `127.0.0.1:8082` (loopback)
**Domain:** `traefik.<tenant_domain>` (derived; default tenant `dev.local`)
**Role:** Edge reverse proxy + SSO front-proxy. Read-only from an agent's view.

### Context

- Image `traefik:v3.6.23`; container `infra-traefik-1`.
- Two providers: file (`conf.d/`, Tier-1, auto-derived from `state/manifest.yml`) and Docker (`docker-socket-proxy:2375`, Tier-2 labels).
- Forward-auth via `authentik@file` middleware (fail-closed); Traefik carries no OIDC client of its own.
- Dashboard API is `api.insecure: true`, loopback-bound; no auth, GET-only.

### Capabilities

- **Read-only introspection** over `http://127.0.0.1:8082`: `GET /ping`, `/api/overview`, `/api/http/routers`, `/api/http/services`, `/api/rawdata`.
- **No write path.** Routing changes are made by editing the manifest-derived file provider or Tier-2 compose labels and re-running the playbook — never a live API call.

### Liveness

`GET http://127.0.0.1:8082/ping` → `200 OK`.

### Skills Reference

See [SKILLS.md](SKILLS.md) for the read-only introspection actions.
