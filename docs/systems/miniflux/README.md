# Miniflux

> A minimalist RSS/Atom feed reader. Stores feed subscriptions, read/unread and
> starred state, and the OIDC session link. State lives in PostgreSQL — the
> container is stateless (no bind-mount).

## Quick Reference

| | |
|---|---|
| **URL** | `https://rss{host_alias_seg}.{tenant_domain}` (default `https://rss.dev.local`) |
| **Port** | `3011` (`miniflux_port`; loopback publish `127.0.0.1:3011` → container `8080`) |
| **Stack** | `iiab` |
| **Node id** | `nos.iiab.miniflux` |
| **Toggle** | `install_miniflux: true` |
| **Image** | `miniflux/miniflux:2.2.19` (`miniflux_version`) |
| **Data** | none in-container — PostgreSQL database `miniflux` (user `miniflux`) on `postgresql:5432` |
| **Memory limit** | `512m` (`miniflux_mem_limit`) |
| **Networks** | `iiab_net` + the shared stacks network |

`miniflux_domain` and `miniflux_port` pin in `default.config.yml`; role defaults are
fallbacks. The domain derives from `tenant_domain` + `host_alias`, not a hardcoded
`dev.local`.

## Authentication

- **SSO:** `native_oidc` (Authentik OAuth2 provider `nos-miniflux`), RBAC tier 3.
  - Redirect URI: `https://{miniflux_domain}/oauth2/oidc/callback`
  - Scopes: `openid`, `email`, `profile`
- **Bootstrap admin:** created on first boot (`CREATE_ADMIN=1`):
  - user `admin`, password `{global_password_prefix}_pw_miniflux_admin`
- **Local form:** hidden when `DISABLE_LOCAL_AUTH` is set (autologin path). Break-glass
  is unset `DISABLE_LOCAL_AUTH` + recreate — there is no runtime UI escape.

## Database

- **`DATABASE_URL`:** `postgres://miniflux:<pw>@postgresql:5432/miniflux?sslmode=prefer`
  (password `{global_password_prefix}_pw_miniflux`)
- **`RUN_MIGRATIONS=1`** — schema migrates on boot.

## Health Check

- **Endpoint (plugin/manifest):** `GET /healthcheck` → `200`.
- **Container healthcheck is DB-aware ON PURPOSE:** it probes `GET /` instead, because
  `/healthcheck` answers `200` from the HTTP layer without touching Postgres — on
  2026-07-20 that let a schema-less miniflux report `healthy` for 19 hours while every
  real request `500`'d. `GET /` renders a session and fails when the DB is empty.

## Dependencies

- PostgreSQL (feed + state store — required)
- Authentik (native-OIDC SSO — optional)
- Mailpit (SMTP relay for notifications, only when `install_mailpit` — optional)
