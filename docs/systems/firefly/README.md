# Firefly III

> Personal finance manager (accounts, transactions, budgets). MariaDB + Redis backed, b2b compose stack, header-OIDC access via Authentik.

## Quick Reference

| | |
|---|---|
| **System id** | `nos.b2b.firefly` |
| **Domain** | `firefly.{{ tenant_domain }}` (default `tenant_domain: dev.local`; optional host-alias segment prepended) |
| **Host port** | `3014` → container `:8080` (bound `127.0.0.1` unless `services_lan_access: true`) |
| **Stack** | `b2b` |
| **Toggle** | `install_firefly` |
| **Image** | `fireflyiii/core:version-6.2.21` |
| **Data** | uploads `{{ nos_data_root }}/platform/services/firefly/upload` → `/var/www/html/storage/upload`; exports `{{ nos_data_root }}/platform/services/firefly/export` → `/var/www/html/storage/export` |
| **Mem / CPU** | `firefly_mem_limit` (default `1g`) / `firefly_cpus` (default `1.0`) |

Firefly has no single `data_dir` and no `data_path_var` in `state/manifest.yml` — persistent state is the MariaDB schema; only user uploads/exports are bind-mounted. `nos_data_root` defaults to `~/nos`; an external-storage override relocates the `platform/services/firefly/*` subtree.

## Authentication

- **SSO bucket:** `header_oidc` (Authentik proxy outpost → trusted identity header; Firefly's `remote_user_guard`). RBAC tier **2** (manager).
- **How it works:** Authentik authenticates the user; the forward-auth path injects the identity header and Firefly **auto-creates the local account on first request**. The user never sees Firefly's own login screen. This is not a per-app OIDC client (Firefly's v6 native OIDC is `auth.json`-file-driven, not env-driven, so nOS uses the header path).
- **Header name depends on the edge proxy** (compose env, set when `install_authentik: true`):
  - Traefik (default, `install_nginx: false`): `AUTHENTICATION_GUARD_HEADER: HTTP_X_AUTHENTIK_USERNAME`, `AUTHENTICATION_GUARD_EMAIL: HTTP_X_AUTHENTIK_EMAIL`.
  - Host nginx (`install_nginx: true`): `REMOTE_USER` / `REMOTE_EMAIL`.
- **Site owner:** `SITE_OWNER = firefly_site_owner` (default `default_admin_email`). No password admin — identity comes from the forwarded header.

## Database & Cache

- **Database:** MariaDB (`DB_CONNECTION: mysql`), db/user `firefly` / `firefly`, password `{{ global_password_prefix }}_pw_firefly` (`firefly_db_password`). Host `mariadb` on the b2b networks when `install_mariadb: true`.
- **APP_KEY:** `firefly_app_key` — Laravel `base64:` key, auto-generated on the first removal-reset run.
- **Redis:** required — cache + session (`REDIS_HOST: redis`, `redis_password`).
- **Network isolation (SEC-02):** Firefly runs on `b2b_net` + `gated_b2b_net`, deliberately **off** the flat `shared_net`, so a peer container cannot reach `:8080` to forge the identity header (`remote_user_guard` does no upstream header validation).

## Health Check

- **Endpoint:** `GET /health`
- **Expected:** `200 OK` (manifest `health_check`; container healthcheck curls `http://127.0.0.1:8080/health`). Returns 200 only once the schema is migrated **and** Redis is reachable.

## Dependencies

- MariaDB (required — schema + accounts)
- Redis (required — cache/session)
- Authentik (SSO / header guard, default)
- Mailpit (optional — dev SMTP capture when `install_mailpit: true`)

## Upgrades

- Version pin lives in `firefly_version` (`roles/pazny.firefly/defaults/main.yml`) and `default.config.yml`. Upgrade recipe: `upgrades/firefly.yml`. First-boot migrations run automatically via `roles/pazny.firefly/tasks/post.yml`.
