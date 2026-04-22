# pazny.miniflux

Ansible role for deploying **Miniflux** (minimalistic RSS reader) as a compose override fragment in the nOS `iiab` stack.

Part of nOS Wave 2.x role extraction.

## What it does

Single `miniflux` service with native Authentik OIDC SSO (env-var based). No post-start setup — user accounts are provisioned on first OIDC login (`OAUTH2_USER_CREATION=1`). A fallback local admin account (`admin` / `miniflux_admin_password`) is created via `CREATE_ADMIN=1` for bootstrap scenarios without Authentik.

Single invocation from `tasks/stacks/stack-up.yml`:

- **Main (`tasks/main.yml`)** — runs *before* `docker compose up iiab`:
  - Renders `templates/compose.yml.j2` into `{{ stacks_dir }}/iiab/overrides/miniflux.yml`
  - Notifies `Restart miniflux` if the override changed

Miniflux is fully stateless — all data lives in PostgreSQL (`miniflux` DB). No host bind-mount volume is declared.

## Requirements

- Docker Desktop for Mac (ARM64)
- `install_postgresql: true` (Miniflux uses Postgres as primary datastore)
- `stacks_shared_network` defined at the play level
- Optional: `install_authentik: true` enables native OIDC env vars

## Variables

| Variable | Default | Description |
|---|---|---|
| `miniflux_version` | `2.2.19` | `miniflux/miniflux` image tag |
| `miniflux_domain` | `rss.{{ instance_tld }}` (fallback `rss.dev.local`) | Public hostname |
| `miniflux_port` | `3011` | Exposed on `127.0.0.1` only (or LAN if `services_lan_access`) |
| `miniflux_db_name` | `miniflux` | PostgreSQL database name |
| `miniflux_db_user` | `miniflux` | PostgreSQL user |
| `miniflux_mem_limit` | `512m` | Container memory limit (lightweight Go binary) |

Secrets (`miniflux_db_password`, `miniflux_admin_password`) stay in the top-level `default.credentials.yml`.

OIDC client id/secret come from the centralized `authentik_oidc_apps` list in `default.config.yml` via the derived `authentik_oidc_miniflux_client_id` / `authentik_oidc_miniflux_client_secret` variables.

## Usage

From `tasks/stacks/stack-up.yml`, gate on `install_miniflux`:

```yaml
- name: "[Stack] Miniflux render (pazny.miniflux role)"
  ansible.builtin.include_role:
    name: pazny.miniflux
  when: install_miniflux | default(false)
```

## SSO tier

Tier 3 (user) — `nos-users`, `nos-managers`, `nos-admins`.

## Admin password rotation

Miniflux CLI's `-reset-password` is interactive (`term.ReadPassword` only accepts `/dev/tty`), and the HTTP API requires an existing API key or Basic auth with the *current* password — so there's no clean idempotent reconverge path from Ansible. Behavior:

- **Blank run** (`-e blank=true`): `CREATE_ADMIN=1` seeds the admin with the current `miniflux_admin_password` at first start. OK.
- **Non-blank run, prefix rotation**: the admin password in Postgres does NOT drift to the new prefix. OIDC login keeps working (users are independent). If you need the fallback admin password reset, either do it in the UI (Settings → Change password) or bump with blank.

OIDC users are always created on first login (`OAUTH2_USER_CREATION=1`).

## Rollback

Revert the commit and delete the dead `~/stacks/iiab/overrides/miniflux.yml`.
