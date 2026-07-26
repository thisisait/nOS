# Metabase

> BI dashboardy. SQL dotazy, vizualizace, sdileni reportu.

## Quick Reference

| | |
|---|---|
| **URL** | `https://bi.dev.local` |
| **Port** | `3002` |
| **Stack** | `data` |
| **Toggle** | `install_metabase: true` |
| **Image** | `metabase/metabase:v0.61.2.6` (`metabase_version`) |
| **Compose** | `~/stacks/data/docker-compose.yml` |
| **Data** | **PostgreSQL** — database `metabase`, user `metabase` on the `postgresql` container (`MB_DB_TYPE: postgres`). Questions, dashboards, collections, users and query history all live there. |
| **Container mount** | `{{ metabase_data_dir }}` = `{{ nos_data_root }}/platform/services/metabase/data` → `/metabase-data` (default `~/nos/platform/services/metabase/data`) |

Data-path note: `nos_data_root` defaults to `~/nos`. On external storage the bind mount
is overridden to `{{ external_storage_root }}/metabase`
(`tasks/stacks/external-paths.yml`). **Backing up Metabase means backing up the Postgres
database, not the bind mount** — `MB_DB_TYPE` is `postgres`, so `/metabase-data` holds
only container-local scratch (plugin jars etc.), never the H2 app DB.

## Authentication

- **Admin user:** `admin@dev.local` (`default_admin_email` = `admin@{{ tenant_domain }}`)
- **Admin password:** `{global_password_prefix}_pw_metabase_admin`
- **SSO:** Authentik `forward_auth` (slug `metabase`, tier 2) — an access gate in front of
  the app, per `files/anatomy/plugins/metabase-base/plugin.yml`.

> **SSO ceiling.** Metabase OSS ships no OIDC, so the Authentik provider is a pure
> forward-auth gate: passing it does **not** log you into Metabase. Metabase still shows
> its own login form behind the gate and everyone shares the admin account above.

## API Access

- **Base URL:** `https://bi.dev.local/api/` (loopback: `http://127.0.0.1:3002/api/`)
- **Auth method:** Session token — `POST /api/session` with the admin e-mail + password,
  then send it as the `X-Metabase-Session` header.
- **Bot account: none.** `roles/pazny.metabase/tasks/post.yml` provisions exactly one
  identity — the admin above, via `POST /api/setup` on first run and a
  `PUT /api/user/1/password` reconverge afterwards. There is no `openclaw-bot` and no
  `~/agents/tokens/` directory anywhere in this repo.
- **Credential location:** `~/.nos/secrets.yml` (prefix-derived), not a token file.

## Health Check

- **Endpoint:** `GET /api/health`
- **Expected:** `200 OK` with `{"status":"ok"}`

## Dependencies

- PostgreSQL (application database — `metabase` DB on the `postgresql` container; this is
  where all Metabase state actually lives)
- Authentik (forward-auth gate, optional)
