# Paperclip

> Multi-agent orchestration platform — coordinates AI agents (OpenClaw, Claude Code, Codex)
> through an org-chart structure. PostgreSQL-backed, in the `devops` compose project.
> Web UI with its own better-auth user store; management is via the in-container `pnpm paperclipai` CLI.

## Quick Reference

| | |
|---|---|
| **Node** | `nos.devops.paperclip` |
| **Stack** | `devops` |
| **Toggle** | `install_paperclip: true` |
| **Image** | `ghcr.io/paperclipai/paperclip:sha-b9a80dc` (upstream publishes no semver tags) |
| **Domain** | `paperclip.<tenant_domain>` (pattern `paperclip{{ _host_alias_seg }}.{{ tenant_domain }}`, `BETTER_AUTH_TRUSTED_ORIGINS`) |
| **Port** | `3006` — published `127.0.0.1:3006` → container `3100` |
| **Data** | `{{ nos_data_root }}/platform/services/paperclip/data` → `/paperclip` (`PAPERCLIP_HOME`) |
| **Database** | PostgreSQL `paperclip` (user `paperclip`) on the shared `infra-postgresql-1` |
| **Mem limit** | `docker_mem_limit_standard` (`1g`) |
| **Container** | `devops-paperclip-1` |

`nos_data_root` defaults to `{{ HOME }}/nos`.

## Authentication

- **App auth:** better-auth against Paperclip's own user store (`account` table in the `paperclip` DB). There is no fixed admin username — the first admin is created by a **CEO bootstrap invite** (`pnpm paperclipai auth bootstrap-ceo`), which prints an invite URL.
- **Session secret:** `BETTER_AUTH_SECRET` = `paperclip_auth_secret` = `{global_password_prefix}_pw_paperclip_auth` (deterministic — must not re-roll per run or it invalidates sessions).
- **DB password:** `paperclip_db_password` = `{global_password_prefix}_pw_paperclip`.
- **Allowed hostnames:** Paperclip closes the TCP connection with no HTTP response unless the request `Host` is registered. `paperclip_domain` (and any `service_extra_hosts`) are registered via `pnpm paperclipai allowed-hostname`; `127.0.0.1` is **not** registered, so loopback probes must send `Host: paperclip.<tenant_domain>`.
- **SSO:** Authentik **forward_auth** — the `authentik@file` Traefik middleware gates the route (client id `nos-paperclip`). RBAC tier **2** (manager). Native OIDC (`BETTER_AUTH_OIDC_*`) is staged but **not yet consumed by the upstream image**; access control remains the proxy gate.
- **Deployment mode:** `PAPERCLIP_DEPLOYMENT_MODE=authenticated`.

## Health Check

- **Endpoint:** `GET /` (manifest `health_check`, `http://localhost:{{ paperclip_port }}/`, expect `200`).
- **Caveat:** a loopback `GET /` must carry `Host: paperclip.<tenant_domain>` (an allowed hostname) or Paperclip drops the connection. The container healthcheck hits `http://localhost:3100/` from inside the container.
- **TCP liveness:** `127.0.0.1:3006` open is the fastest reliable "node server up" signal.

## Dependencies

- Docker (`devops` compose stack).
- **PostgreSQL** (`install_postgresql: true`) — required backend.
- OpenClaw gateway, reached out to at `PAPERCLIP_OPENCLAW_URL` (`http://host.docker.internal:{{ openclaw_gateway_port }}`, default `18789`).
- Authentik (route gate, optional).
