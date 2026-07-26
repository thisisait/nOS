# Woodpecker CI

> Lightweight CI/CD server + agent, hooked into Gitea over OAuth2.
> Two containers (server + agent) in one role, both in the `devops` compose project.
> Gitea push → Gitea webhook → Woodpecker runs the `.woodpecker.yml` pipeline.

## Quick Reference

| | |
|---|---|
| **Node** | `nos.devops.woodpecker` |
| **Stack** | `devops` |
| **Toggle** | `install_woodpecker: false` |
| **Server image** | `woodpeckerci/woodpecker-server:v3.14.1` |
| **Agent image** | `woodpeckerci/woodpecker-agent:v3.14.1` |
| **Domain** | `ci.<tenant_domain>` (pattern `ci{{ _host_alias_seg }}.{{ tenant_domain }}`, `WOODPECKER_HOST` over HTTPS) |
| **Web port** | `8060` — published `127.0.0.1:8060` → container `8000` |
| **gRPC port** | `9060` — published `127.0.0.1:9060` → container `9000` (agent↔server, internal) |
| **Data** | `{{ nos_data_root }}/platform/services/woodpecker/data` → `/var/lib/woodpecker` |
| **Mem limit** | server `docker_mem_limit_light` (`512m`); agent `docker_mem_limit_standard` (`1g`) |
| **Containers** | `devops-woodpecker-server-1`, `devops-woodpecker-agent-1` |

`nos_data_root` defaults to `{{ HOME }}/nos`.

## Authentication

- **App-level login:** Gitea **OAuth2** (`WOODPECKER_GITEA=true`, `WOODPECKER_GITEA_URL=https://git.<tenant_domain>`). The OAuth2 application is autowired in Gitea by `roles/pazny.woodpecker/tasks/post-oauth.yml`; client/secret persist to `{{ HOME }}/.nos/secrets.yml`.
- **Pre-seeded admin:** `WOODPECKER_ADMIN` (defaults to `gitea_admin_user`) is auto-created and granted admin on first login, bypassing `WOODPECKER_OPEN=false`.
- **Open registration:** disabled (`woodpecker_open_registration: false`).
- **Agent secret:** `woodpecker_agent_secret` = `{global_password_prefix}_pw_woodpecker` (shared server↔agent).
- **SSO:** Authentik **forward_auth** — a Tier-1 route gate on `ci.<tenant_domain>` in front of Woodpecker's own Gitea handshake (client id `nos-woodpecker`). RBAC tier **2** (manager). Woodpecker has no native OIDC and no trusted-proxy/header-auth backend, so login is transitively Authentik-rooted via Gitea's native OIDC, not direct.

## API Access

- **Base (loopback):** `http://127.0.0.1:8060/api/`
- **Auth header:** `Authorization: Bearer <token>`
- **Token:** `woodpecker_api_token` — an OAuth-derived Personal Access Token (Woodpecker UI → User Settings → Personal Access Tokens). It **cannot exist on a fresh blank** (no user has logged in yet); provision it after first login and re-run `--tags woodpecker`.

## Health Check

- No `health_check` block is declared for Woodpecker in `state/manifest.yml`.
- **Readiness signal:** the web UI reachable on `127.0.0.1:8060` (the TCP port is the reliable liveness signal).
- **Metrics:** `GET /metrics` — exposed by the server, gated behind `Authorization: Bearer <woodpecker_prom_token>` (`WOODPECKER_PROMETHEUS_AUTH_TOKEN`); only the Alloy scrape carrying the matching token can read it.

## Hardening

- `WOODPECKER_PLUGINS_PRIVILEGED=""` — no plugin may request `privileged` containers (REM-002).
- `WOODPECKER_AUTHENTICATE_PUBLIC_REPOS=false` — forked-PR / unaffiliated-contributor pushes do not trigger pipelines (pipeline-as-RCE defense).
- `v3.14.1` pins the floating `v3` tag — fixes CVE-2026-50141 (agent_id gRPC-metadata spoof auth bypass, REM-105).

## Dependencies

- Docker (`devops` compose stack) and `/var/run/docker.sock` bind-mounted into the agent (`WOODPECKER_BACKEND=docker`).
- **Gitea** (peer service) — the OAuth2 forge for app-level auth. Woodpecker is dormant without it.
- Authentik (route gate, optional).
