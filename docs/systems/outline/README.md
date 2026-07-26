# Outline

> Team wiki and knowledge base. Markdown editor, collections, search.

## Quick Reference

| | |
|---|---|
| **URL** | `https://wiki{host_alias_seg}.{tenant_domain}` (default `https://wiki.dev.local`) |
| **Port** | `3005` (`outline_port`; loopback publish `127.0.0.1:3005` → container `3000`) |
| **Stack** | `b2b` |
| **Toggle** | `install_outline: true` |
| **Compose** | `~/stacks/b2b/docker-compose.yml` (role fragment: `~/stacks/b2b/overrides/outline.yml`) |
| **Image** | `outlinewiki/outline:1.8.1` (`outline_version`) |
| **Data** | `{{ nos_data_root }}/platform/services/outline/data` (default `~/nos/platform/services/outline/data`) → `/var/lib/outline/data` — **attachments only**; documents live in PostgreSQL |
| **Mem / CPU** | `outline_mem_limit` (default `1g`) / `outline_cpus` (default `1.0`) |

`nos_data_root` defaults to `~/nos` (`{{ HOME }}/nos`); `tasks/stacks/external-paths.yml`
relocates `outline_data_dir` to `{{ external_storage_root }}/outline/data` when external
storage is in play. The bind mount backs `FILE_STORAGE=local` /
`FILE_STORAGE_LOCAL_ROOT_DIR` — **document text, collections, and revisions are rows in
PostgreSQL**, not files here.

## Database

- **`DATABASE_URL`:** `postgres://outline:<pw>@postgresql:5432/outline` with
  `PGSSLMODE=disable` (password `{global_password_prefix}_pw_outline`)
- **Redis:** `redis://:<pw>@redis:6379` — sessions + the collaborative-editing backend
- **Secrets:** `outline_secret_key` / `outline_utils_secret` are auto-generated
  (`openssl rand -hex 32`) on a removal-reset and persisted to `~/.nos/secrets.yml`.

## Authentication

- **SSO:** `native_oidc` (Authentik OAuth2 client `nos-outline`, slug `outline`), RBAC tier **3**.
  - Redirect URI: `https://{outline_domain}/auth/oidc.callback`
  - Scopes: `openid`, `profile`, `email`
- **Admin:** first user who logs in via SSO
- **Local form:** Authentik is the only configured auth provider, so there is no local
  password login. The login *screen* still renders (with a "Continue with Authentik"
  button) — Outline has no env to suppress it. Autologin is inverted vs other services:
  auto-redirect happens by the **absence** of `OIDC_DISABLE_REDIRECT`, which the
  compose-extension emits while `sso_autologin` is false. Break-glass is therefore
  "set `OIDC_DISABLE_REDIRECT=true` + recreate".

## API Access

- **Base URL:** `https://wiki.dev.local/api/`
- **Auth method:** Bearer token (Personal API Token)
- **Bot account:** none provisioned. No playbook task creates an Outline user or API
  token, and nothing writes `~/agents/tokens/outline.token` — log in via SSO and mint a
  Personal API Token in Settings → API Tokens if an agent needs one.

## Health Check

- **Endpoint:** `GET /_health` (container healthcheck: `wget --spider http://localhost:3000/_health`)
- **Expected:** `200 OK`
- **`start_period` is 180s on purpose:** a cold boot runs Node 22 startup + the Postgres
  schema migration + Redis collab init + OIDC plugin registration before `/_health`
  answers. At 60s an early failed probe made `docker compose up --wait` return rc=1 and
  trip the stack-up fail-fast assert on a container that was healthy moments later.

## Dependencies

- PostgreSQL (document + collection store — required)
- Redis (sessions + collaborative editing — required)
- Authentik (native-OIDC SSO — required; it is the only auth provider)
- Mailpit (SMTP relay, only when `install_mailpit` — optional)
