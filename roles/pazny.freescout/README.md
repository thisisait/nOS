# pazny.freescout

Ansible role for deploying **FreeScout** (Laravel helpdesk / ticketing) as a compose override fragment in the nOS `b2b` stack.

Part of [nOS](../../README.md) Wave 2.2 role extraction.

## What it does

Single `freescout` service plus post-start admin onboarding via Laravel Artisan and **native OIDC SSO** with Authentik via the `freescout-oauth` community module.

Two invocation modes from `tasks/stacks/stack-up.yml`:

1. **Main (`tasks/main.yml`)** — runs *before* `docker compose up b2b`:
   - Creates `{{ freescout_data_dir }}` on the host
   - Renders `templates/compose.yml.j2` into `{{ stacks_dir }}/b2b/overrides/freescout.yml`
   - Notifies `Restart freescout` if the override changed

2. **Post (`tasks/post.yml`)** — runs *after* `docker compose up b2b --wait`:
   - Waits for FreeScout HTTP to accept requests (accepts 200/302/500)
   - First-run: `artisan freescout:create-user --role=admin` if the admin email has no user
   - Every run: `artisan tinker` UPDATE of the bcrypt password hash for the admin user (reconverge for rotated `global_password_prefix`)
   - **When `install_authentik=true`**: clones the `freescout-oauth` module into `/data/Modules/OAuth` (persistent), runs `artisan module:enable OAuth`, and persists all OIDC endpoints + client credentials into the `options` table via `tinker` / `Option::set()` so the admin UI form never has to be filled in by hand

FreeScout has no REST API for onboarding, which is why Artisan CLI calls via `docker compose exec` are the only path.

## Authentik SSO (native OIDC)

Migrated from Nginx proxy-auth (forward_auth) to native OIDC on 2026-04-22.

- **Flow**: FreeScout renders its own login page with a "Sign in with Authentik" button (provided by the `freescout-oauth` module). Click → Authorization Code flow against `auth.dev.local` → OAuth callback at `/oauth/callback` → session created.
- **Module source**: [`freescout-help-desk/oauth`](https://github.com/freescout-help-desk/oauth) with fallback to [`tiredofit/freescout-module-oauth`](https://github.com/tiredofit/freescout-module-oauth) if the primary clone fails.
- **Config persistence**: all settings (`oauth.client_id`, `oauth.client_secret`, discovery URL, redirect URI, scopes) are written into the FreeScout `options` table. The compose env vars (`FREESCOUT_OIDC_*`) are mirrored there for documentation / future modules that read from env.
- **CA trust**: the mkcert root CA is bind-mounted into the container (`/usr/local/share/ca-certificates/mkcert-ca.crt`) and PHP curl is pointed at it via `PHP_CURL_CAINFO` so TLS handshakes against `auth.dev.local` succeed without inserting a cert bundle on the host.
- **Authentik provider**: add (or update) an entry in `authentik_oidc_apps` in `default.config.yml`:

  ```yaml
  - name: "FreeScout"
    slug: "freescout"
    enabled: "{{ install_freescout | default(false) }}"
    client_id: "nos-freescout"
    client_secret: "{{ global_password_prefix }}_pw_oidc_freescout"
    redirect_uris: "https://{{ freescout_domain | default('helpdesk.dev.local') }}/oauth/callback"
    launch_url: "https://{{ freescout_domain | default('helpdesk.dev.local') }}"
    type: "oauth2"
  ```

- **Nginx**: the `authentik-proxy-auth` include was removed from `templates/nginx/sites-available/freescout.conf`. The service gates itself — no forward-auth anymore.

### First-run gotcha

On a **completely fresh** install (blank=true), the OAuth module must finish cloning + enabling before the Authentik application exists. The playbook order handles this correctly (Authentik is provisioned in `core-up.yml`, FreeScout in `stack-up.yml`), but if you toggle `install_authentik` on for an existing FreeScout, re-run with `--tags freescout,authentik` to pick up the new OIDC wiring.

If the Option-table UPSERT fails on very old FreeScout DBs (pre-1.7), log into the Admin UI at `https://{{ freescout_domain }}/users/permissions/oauth` and the form will be pre-populated from env vars — press Save once.

## Requirements

- Docker Desktop for Mac (ARM64)
- `pazny.mariadb` role (or equivalent MariaDB). `freescout` database + user are seeded via `mariadb_databases` / `mariadb_users` in `default.config.yml`
- `stacks_shared_network` defined at the play level
- For OIDC: `install_authentik=true` and an Authentik outpost reachable at `{{ authentik_domain }}`

## Variables

| Variable | Default | Description |
|---|---|---|
| `freescout_version` | `php8.3-1.17.152` | `tiredofit/freescout` image tag (past CVE-2026-28289) |
| `freescout_domain` | `helpdesk.dev.local` | Public hostname |
| `freescout_port` | `8090` | Exposed on `127.0.0.1` only (or LAN if `services_lan_access`) |
| `freescout_data_dir` | `~/freescout/data` | Host bind mount (overridden by `external-paths.yml` on SSD setups). Houses the cloned `Modules/OAuth` as well. |
| `freescout_db_name` | `freescout` | MariaDB database name |
| `freescout_db_user` | `freescout` | MariaDB user |
| `freescout_admin_email` | `{{ default_admin_email }}` | Admin login email |
| `freescout_timezone` | `Europe/Prague` | Container TZ |
| `freescout_mem_limit` | `{{ docker_mem_limit_light }}` | Container memory limit |

Secrets (`freescout_db_password`, `freescout_admin_password`, `authentik_oidc_freescout_client_secret`) stay in the top-level `default.credentials.yml` for prefix rotation.

## Usage

From `tasks/stacks/stack-up.yml`, gate on `install_freescout`:

```yaml
- name: "[Stack] FreeScout render (pazny.freescout role)"
  ansible.builtin.include_role:
    name: pazny.freescout
  when: install_freescout | default(false)

# ... docker compose up b2b --wait ...

- name: "[Stack] FreeScout post-start (pazny.freescout → post.yml)"
  ansible.builtin.include_role:
    name: pazny.freescout
    tasks_from: post.yml
  when: install_freescout | default(false)
```

## Rollback

- **SSO rollback** (back to proxy-auth): re-add the `authentik-proxy-locations` / `authentik-proxy-auth` includes to `templates/nginx/sites-available/freescout.conf`, remove the `FREESCOUT_OIDC_*` env block from `templates/compose.yml.j2`, and delete `{{ freescout_data_dir }}/Modules/OAuth` + `php artisan module:disable OAuth`. Update `authentik_oidc_apps[freescout].type` back to `proxy`.
- **Full role rollback**: revert the commit and restore the `freescout` service block in `templates/stacks/b2b/docker-compose.yml.j2` plus `tasks/iiab/freescout_post.yml`. Delete the dead `~/stacks/b2b/overrides/freescout.yml`.
