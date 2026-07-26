# Wing

> The security-research dashboard and state-framework UI — Nette PHP over a SQLite store. It observes: systems inventory, remediation queue, audit events, migrations/upgrades, agents, and GDPR records.

## Quick Reference

| | |
|---|---|
| **Toggle** | `install_wing: true` (`default.config.yml`) |
| **Kind** | Host launchd daemon (FrankenPHP single binary) — NOT a Docker service |
| **Bind** | `127.0.0.1:9000` (`wing_port`) |
| **Domain** | `wing.<tenant_domain>` (default tenant `dev.local` ⇒ `wing.dev.local`) — Traefik file-provider route |
| **Stack** | `host` (manifest `stack: null`) |
| **launchd label** | `eu.thisisait.nos.wing` |
| **App dir** | `~/wing/app` (`wing_app_dir`) |
| **Data** | `~/wing/app/data` (`wing_data_dir`) — the `wing.db` SQLite store |
| **Logs** | `~/wing/app/log` (`wing_log_dir`) |
| **Binary** | `/opt/homebrew/bin/frankenphp` (`frankenphp_bin`) |

FrankenPHP bundles the PHP runtime + Caddy HTTP server in one binary — the pre-A3.5 `wing-nginx` sidecar is gone (closed the wing-nginx stale-IP 502 class). Source tree: `files/anatomy/wing/`.

## Authentication

Two layers:

- **Edge access — Authentik forward-auth (SSO).** `wing-base` plugin sets `authentik.mode: forward_auth`, `tier: 1` (admin), `slug: wing`, `client_id: nos-wing`. Traefik applies the `authentik@file` middleware; the Authentik session is the gate. There is no native OIDC — Wing renders its own UI behind the proxy gate. Forward-auth headers (`X-Authentik-Username`, groups) drive the in-app Nette identity + tiered RBAC (`ForwardAuthUserStorage`, `$minAccessTier`).
- **API — Bearer token.** `/api/v1/*` routes require `Authorization: Bearer <wing_api_token>`, validated against Wing's `TokenRepository` (`BaseApiPresenter::requireTokenAuth`). Missing/invalid ⇒ `401`. Token: `wing_api_token` = `{global_password_prefix}_pw_wing_api` (per-agent tokens also exist: `openclaw_wing_api_token`, `conductor_wing_api_token`, …).

## API / Health

- **Base URL:** `https://wing.<tenant_domain>/api/v1/` (or `http://localhost:9000/api/v1/` on the loopback bind)
- **Hub health:** `GET /api/v1/hub/health`
- **Route module:** everything under `api/v1/` maps to `App\Presenters\Api\*` (`RouterFactory`). Families: `events`, `notifications`, `state`, `migrations`, `upgrades`, `remediation`, `advisories`, `scan`, `pentest`, `pulse_jobs` / `pulse_runs`, `agents` / `agent-sessions`, `gdpr`, `metrics`, `hub`, `deploy-trigger`.

## Dependencies

- Bone (`http://localhost:8099`) — Wing's SQLite store (`~/wing/app/data/wing.db`) is the sink Bone writes events/notifications to; Wing reads it.
- Pulse — runs Wing's `pulse_jobs` (e.g. `dispatch-notifications`, `audit-chain-verify`) as host cron.
- Authentik + Traefik — the forward-auth edge gate (tier 1).
- FrankenPHP (Homebrew) — the runtime binary.
