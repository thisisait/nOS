# code-server

> VS Code in the browser (LinuxServer.io image), behind the Authentik forward-auth proxy.
> No database — state is the filesystem under `/config`. In the `devops` compose project.
> Full shell access to the host workspace: treated as an admin-only surface.

## Quick Reference

| | |
|---|---|
| **Node** | `nos.devops.code-server` |
| **Stack** | `devops` |
| **Toggle** | `install_code_server: false` |
| **Image** | `lscr.io/linuxserver/code-server:4.115.0-ls332` (arm64v8 + amd64 multi-arch) |
| **Domain** | `code.<tenant_domain>` (pattern `code{{ _host_alias_seg }}.{{ tenant_domain }}`, `PROXY_DOMAIN`) |
| **Port** | `3009` — published `127.0.0.1:3009` → container `8443` |
| **Config** | `{{ nos_data_root }}/platform/services/code_server/data` → `/config` |
| **Workspace** | `{{ nos_data_root }}/platform/services/code_server/workspace` → `/config/workspace` |
| **Mem limit** | `docker_mem_limit_critical` (`2g`) |
| **Container** | `devops-code-server-1` |

`nos_data_root` defaults to `{{ HOME }}/nos`. The manifest service id is `code_server` (underscore); the compose service and container use the hyphen form `code-server`.

## Authentication

- **Built-in login:** disabled. `PASSWORD`, `HASHED_PASSWORD` and `SUDO_PASSWORD` are rendered empty on purpose, so the LinuxServer image serves no password prompt.
- **SSO:** Authentik **forward_auth** — access is gated entirely by the `authentik@file` middleware / nginx forward-auth in front of the route. There is no per-user identity inside code-server (pure access gate). RBAC tier **2** per `plugin.yml` + `state/manifest.yml` (`rbac_tier: 2`); the role header notes the intent is admin-only because code-server grants full host-workspace shell access.
- **Upstream note:** the LSIO image is HTTP-only on `8443` (no internal TLS) — do not add it to `traefik_https_upstream_ids`.

## Health Check

- No `health_check` block is declared for code-server in `state/manifest.yml`.
- **Container healthcheck** (from `compose.yml.j2`): `curl -sf http://localhost:8443/healthz || curl -sf http://localhost:8443/` (`start_period` 60s).

## Environment

- `PUID` `1000` / `PGID` `1000` / `TZ` `Europe/Prague`.
- `DEFAULT_WORKSPACE=/config/workspace`.

## Dependencies

- Docker (`devops` compose stack).
- Authentik (forward-auth gate) — without it the route is unauthenticated, which for a full-shell IDE is unsafe; keep the gate on.
- No database, no shared nOS backend services.
