# Uptime Kuma

> Status monitoring a incident management. Sleduje dostupnost vsech sluzeb.

## Quick Reference

| | |
|---|---|
| **URL** | `https://uptime.dev.local` |
| **Port** | `3001` |
| **Stack** | `iiab` |
| **Toggle** | `install_uptime_kuma: true` |
| **Image** | `louislam/uptime-kuma:2.2.1` (`uptime_kuma_version`) |
| **Container** | `iiab-uptime-kuma-1` |
| **Compose** | `~/stacks/iiab/docker-compose.yml` |
| **Data** | `{{ uptime_kuma_data_dir }}` = `{{ nos_data_root }}/platform/services/uptime_kuma/data` → default `~/nos/platform/services/uptime_kuma/data` |
| **Container mount** | host data → `/app/data` (holds the embedded SQLite DB) |

Data-path note: `nos_data_root` defaults to `~/nos`. On external storage the path is
overridden to `{{ external_storage_root }}/uptime-kuma`
(`tasks/stacks/external-paths.yml`).

> **Version shadow — read this before bumping.** `roles/pazny.uptime_kuma/defaults/main.yml`
> still pins `uptime_kuma_version: "1"` and its comment argues for staying on the v1 line,
> but `default.config.yml` sets `2.2.1` and **`default.config.yml` outranks a role
> default** — so what actually runs is **v2.2.1**. The bump was REM-073 (2026-07-24, SSTI
> CVE-2026-33130); the config comment marks the shadow as intentional. Treat any v1-era
> statement in the role defaults as historical.

## Authentication

- **Admin user:** `admin` (`uptime_kuma_admin_user`)
- **Admin password:** `{global_password_prefix}_pw_uptime_kuma` — provisioned and
  reconverged by `roles/pazny.uptime_kuma/tasks/monitors.yml` (`reset-password.py`),
  not "configured at first launch".
- **SSO:** Authentik `forward_auth` (slug `uptime-kuma`, tier 3) via the proxy outpost.
- **Kuma's own login is DISABLED by default** (`uptime_kuma_disable_internal_auth: true`,
  applied only when `install_authentik` is on) so the Authentik gate is the single
  sign-in. The admin password above still exists for the playbook's own API login.

## API Access

- **Base URL:** `https://uptime.dev.local` (loopback: `http://127.0.0.1:3001`)
- **Auth method:** WebSocket (socket.io). nOS drives it through the `uptime_kuma_api`
  Python library from `roles/pazny.uptime_kuma/files/setup-monitors.py`, which logs in
  with the admin user + password.
- **Bot account: none.** No `openclaw-bot`, and no `~/agents/tokens/` directory exists
  anywhere in this repo. Credentials come from `~/.nos/secrets.yml`.

> **There is no monitor REST API.** Uptime Kuma exposes only a handful of unauthenticated
> HTTP routes (`/api/entry-page`, `/api/status-page/<slug>`,
> `/api/status-page/heartbeat/<slug>`, `/api/badge/...`, `/metrics`). Creating, listing or
> editing monitors is socket.io-only — see SKILLS.md.

## Health Check

- **Container:** the image **bakes its own `HEALTHCHECK`** (`extra/healthcheck`); the
  compose override declares none. Recorded in
  `tests/anatomy/test_healthcheck_coverage.py`.
- **Manifest:** the `uptime_kuma` row in `state/manifest.yml` carries **no** `health_check`
  block.
- **HTTP probe (if you need one):** `GET /api/entry-page` → `200 OK`. The previously
  documented `GET /api/entry` is not a route Uptime Kuma serves.

## Dependencies

- None (embedded SQLite database under `/app/data`)
- Authentik (forward-auth proxy outpost, optional)
- Bone (optional — receives monitor alerts at
  `http://127.0.0.1:{{ bone_port }}/api/events`, `uptime_kuma_notify_webhook_url`)
- ntfy (optional — alert topic `uptime_kuma_ntfy_topic`, default `nos-alerts`)
