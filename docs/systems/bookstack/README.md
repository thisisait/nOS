# BookStack

> Wiki / knowledge base with a Shelf → Book → Chapter → Page library model. LinuxServer.io PHP/Apache image, MariaDB-backed, b2b compose stack.

## Quick Reference

| | |
|---|---|
| **System id** | `nos.b2b.bookstack` |
| **Domain** | `bookstack.{{ tenant_domain }}` (default `tenant_domain: dev.local`; optional host-alias segment prepended) |
| **Host port** | `3013` → container `:80` (bound `127.0.0.1` unless `services_lan_access: true`) |
| **Stack** | `b2b` |
| **Toggle** | `install_bookstack` |
| **Image** | `lscr.io/linuxserver/bookstack:26.05.2` |
| **Data** | `{{ nos_data_root }}/platform/services/bookstack/data` → `/config` |
| **Mem / CPU** | `bookstack_mem_limit` (default `1g`) / `bookstack_cpus` (default `1.0`) |

`nos_data_root` defaults to `~/nos` (`{{ HOME }}/nos`); an external-storage override (e.g. `/Volumes/SSD1TB/...`) relocates the whole `platform/services/bookstack/data` subtree. The authoritative app config is `/config/www/.env`, rendered by the role from `env.j2`.

## Authentication

- **SSO bucket:** `native_oidc` (Authentik OAuth2). RBAC tier **3** (user).
- **Authentik client:** `nos-bookstack`, slug `bookstack`, redirect URI `https://bookstack.{{ tenant_domain }}/oidc/callback`, scopes `openid email profile groups`.
- **Login:** "Sign in with Authentik" on the BookStack login page. With `sso_autologin` enabled BookStack auto-redirects and hides the local form (`AUTH_AUTO_INITIATE`); break-glass is `?prevent_auto_init=true`.
- **Local admin:** BookStack ships the LinuxServer/upstream first-run default account — nOS does **not** seed or manage a nOS admin here. Treat OIDC as the real identity path; rotate or disable the upstream default after first boot.

## Database

- **Engine:** MariaDB (shared from the `infra` stack; host `mariadb` on `b2b_net` when `install_mariadb: true`, else `bookstack_db_host` default `127.0.0.1`).
- **Database / user:** `bookstack` / `bookstack`; password `{{ global_password_prefix }}_pw_bookstack` (`bookstack_db_password`, `default.credentials.yml`).
- **APP_KEY:** `bookstack_app_key` — Laravel `base64:` key, auto-generated on first run / removal-reset.
- **Optional Redis:** when `redis_docker: true`, cache/session/queue move to Redis.

## Health Check

- **Endpoint:** `GET /login`
- **Expected:** `200 OK` (manifest `health_check`, and the container healthcheck curls `http://127.0.0.1/login`). `/login` exercises the full Laravel boot + DB + `.env` path.

## Dependencies

- MariaDB (required — schema + accounts)
- Authentik (SSO, optional but default)
- Redis (optional — cache/session/queue when `redis_docker: true`)
- Mailpit (optional — dev SMTP capture when `install_mailpit: true`)

## Upgrades

- Version pin lives in `bookstack_version` (`roles/pazny.bookstack/defaults/main.yml`) and `default.config.yml`. Upgrade recipe: `upgrades/bookstack.yml`.
