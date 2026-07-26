# HedgeDoc

> Real-time collaborative markdown editor. PostgreSQL-backed, b2b compose stack, native Authentik OIDC.

## Quick Reference

| | |
|---|---|
| **System id** | `nos.b2b.hedgedoc` |
| **Domain** | `hedgedoc.{{ tenant_domain }}` (default `tenant_domain: dev.local`; optional host-alias segment prepended) |
| **Host port** | `3012` → container `:3000` (bound `127.0.0.1` unless `services_lan_access: true`) |
| **Stack** | `b2b` |
| **Toggle** | `install_hedgedoc` |
| **Image** | `quay.io/hedgedoc/hedgedoc:1.11.0` |
| **Data** | `{{ nos_data_root }}/platform/services/hedgedoc/data` → `/hedgedoc/public/uploads` |
| **Mem / CPU** | `hedgedoc_mem_limit` (default `1g`) / `hedgedoc_cpus` (default `1.0`) |

Notes and edit history live in **PostgreSQL** (infra stack); only file uploads are bind-mounted at the data path above. `nos_data_root` defaults to `~/nos`; an external-storage override relocates the subtree (removal-reset also honors `hedgedoc_external_data_dir_override`). The image is pinned at `1.11.0` to close REM-121 (CVE-2026-58486 YAML alias-expansion DoS, CVSS 8.3).

## Authentication

- **SSO bucket:** `native_oidc` (Authentik OAuth2, `CMD_OAUTH2_*` env). RBAC tier **3** (user).
- **Authentik client:** `nos-hedgedoc`, slug `hedgedoc`, redirect URI `https://hedgedoc.{{ tenant_domain }}/auth/oauth2/callback`, scopes `openid email profile`.
- **Login policy:** OIDC-only — `CMD_ALLOW_ANONYMOUS: false` and `CMD_ALLOW_EMAIL_REGISTER: false`. There is **no local admin and no email/password registration**; a user account is created on the first "Sign in with Authentik". No post-start setup is required (`roles/pazny.hedgedoc/tasks/main.yml`).
- **Public URL / TLS:** `CMD_DOMAIN` = the derived domain, `CMD_PROTOCOL_USESSL: true`, `CMD_URL_ADDPORT: false`.

## Database

- **Engine:** PostgreSQL (infra stack, host `postgresql:5432`).
- **Database / user:** `hedgedoc` / `hedgedoc`; password `{{ global_password_prefix }}_pw_hedgedoc` (`hedgedoc_db_password`).
- **Connection:** `CMD_DB_URL` uses `sslmode=require` when `postgresql_ssl_enabled: true`, else `prefer` (TLS-if-offered, plaintext fallback — REM-009).
- **Session secret:** `hedgedoc_session_secret` (default `{{ global_password_prefix }}_pw_hedgedoc_session`) — regenerated on removal-reset (session cookies are re-creatable; DB notes are not lost).

## Health Check

- **Container liveness:** TCP connect on `:3000` (`bash -c ':>/dev/tcp/127.0.0.1/3000'` — the image ships no curl/wget). This is the compose healthcheck.
- **App status endpoint:** `GET /status` (the plugin's `post_compose` waits on `http://127.0.0.1:{{ hedgedoc_port }}/status`).
- `state/manifest.yml` carries no `health_check` block for HedgeDoc; the TCP liveness above is authoritative for container health.

## Dependencies

- PostgreSQL (required — notes + history)
- Authentik (SSO — required in practice: anonymous + email registration are off)
- Mailpit (optional — dev SMTP capture when `install_mailpit: true`)

## Upgrades

- Version pin lives in `hedgedoc_version` (`roles/pazny.hedgedoc/defaults/main.yml`) and `default.config.yml`.
