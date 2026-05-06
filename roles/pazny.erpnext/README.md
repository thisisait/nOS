# pazny.erpnext

> ## ⚠️  PARKED 2026-05-08 — non-working / experimental
>
> This role is **disabled by default and hard-blocked at role-load** to keep
> blank runs reaching `failed=0`. Operators who want to attempt enable
> regardless must opt in:
>
> ```yaml
> # config.yml
> install_erpnext: true
> erpnext_experimental_override: true   # acknowledge instability
> ```
>
> **Why parked:**
>
> - The configurator is a one-shot (`restart: "no"`) creating the Frappe
>   site + bench config, but `bench new-site` periodically fails on cold
>   blank with MariaDB connection races (mariadb is healthy but `bench` retry
>   loop misjudges and gives up).
> - Long post-start recovery pipeline (`tasks/post.yml` 205 LOC of
>   "(try N) configurator retry / migration lock cleanup") masks real
>   failures and slows blank runs by 5-10 min on cold cache.
> - Upstream `frappe/erpnext:v15` minor versions occasionally break the
>   configurator interface; we chase upstream rather than own the contract.
> - SSO setup (Frappe Social Login Key) is an out-of-band post-API call
>   sequence that doesn't fit the plugin loader's `replay_api_calls`
>   pattern cleanly — a real Track-Q-style refactor is overdue.
>
> **Future rework:** when Track X+ stabilises, ERPNext can come back as
> a proper plugin under `files/anatomy/plugins/erpnext-base/` with
> `lifecycle.post_compose: replay_api_calls` doing the bench/Frappe API
> work the role's post.yml currently does. Compose template + post.yml
> stay in this dir as the foundation for that rework.

---

Ansible role for deploying **ERPNext** (Frappe framework) as a compose override fragment in the nOS `b2b` stack. Provides CRM, ERP, HR, and Accounting capabilities.

Part of [nOS](../../README.md) Wave 2.2 role extraction.

## What it does

Six compose services + one Docker named volume, rendered as a single override fragment:

- `erpnext-configurator` — one-shot: `bench new-site` + app install
- `erpnext-backend` — gunicorn + socketio
- `erpnext-frontend` — nginx (port `erpnext_port`)
- `erpnext-queue-short` — short queue worker
- `erpnext-queue-long` — long queue worker
- `erpnext-scheduler` — cron scheduler
- Named volume `erpnext_sites` (P0.1 VirtioFS workaround — see below)

Two invocation modes from `tasks/stacks/stack-up.yml`:

1. **Main (`tasks/main.yml`)** — runs *before* `docker compose up b2b`:
   - Renders `templates/compose.yml.j2` into `{{ stacks_dir }}/b2b/overrides/erpnext.yml`
   - Notifies `Restart erpnext` if the override template changed

2. **Post (`tasks/post.yml`)** — runs *after* `docker compose up b2b --wait`:
   - Checks configurator exit code + site_config.json existence
   - **Case 1** (site not created): full retry — wait for MariaDB, remove stale configurator container, rerun
   - **Case 2** (site created, migrations incomplete): `bench migrate` with lock cleanup, accept `Queued rebuilding of search index` stdout marker as success
   - Restart frontend + backend after any repair
   - Reconverge Administrator password via `bench set-admin-password`
   - Verify site via `/api/method/frappe.ping` with `Host:` header (accepts 200, 403, 417)
   - **Authentik native OIDC** (when `install_authentik`): creates a Frappe `Social Login Key` doctype record via `bench execute frappe.client.insert`. Idempotent — existence probed via `frappe.client.get_list` filtered on `provider_name=Authentik`, insert runs only if zero keys match.

## Authentik SSO (native OIDC)

ERPNext integrates with Authentik via **Frappe's built-in Social Login Key** (not Nginx proxy_auth). The `Social Login Key` doctype is a first-class Frappe construct — once configured, ERPNext's login page renders a "Login with Authentik" button that kicks off the OAuth2 authorization-code flow against the Authentik provider.

**Endpoints (hard-coded in the payload):**

| Frappe field | Value |
|---|---|
| `base_url` | `https://{{ authentik_domain }}` |
| `authorize_url` | `/application/o/authorize/` |
| `access_token_url` | `/application/o/token/` |
| `api_endpoint` | `/application/o/userinfo/` |
| `redirect_url` | `/api/method/frappe.integrations.oauth2_logins.custom` (built-in Frappe callback) |
| `client_id_field_name` | `preferred_username` (Authentik's OIDC claim for usernames) |
| `auth_url_data` | `{"scope":"openid profile email"}` |
| `sign_ups` | `Allow` (auto-provision new ERPNext users from Authentik) |

**Redirect URI registered in Authentik:** `https://{{ erpnext_domain }}/api/method/frappe.integrations.oauth2_logins.custom?provider=Authentik`

**Variables consumed:**

- `authentik_oidc_erpnext_client_id` (default `nos-erpnext`)
- `authentik_oidc_erpnext_client_secret` (default `{{ global_password_prefix }}_pw_oidc_erpnext`)
- `authentik_domain` (default `auth.dev.local`)

Both are populated by the orchestrator via `authentik_oidc_apps` entry with `slug: erpnext`.

**Idempotency:** `bench execute frappe.client.get_list --kwargs '{"doctype":"Social Login Key","filters":{"provider_name":"Authentik"}}'` precedes the insert; if the listing already contains `Authentik`, the insert is skipped. Rotating the client_secret currently requires manual update inside ERPNext (Social Login Key > Authentik) or deletion of the doctype record so the next run re-creates it.

**Nginx:** the `erpnext.conf` vhost intentionally omits `authentik-proxy-auth.conf` / `authentik-proxy-locations.conf` — the forward-auth outpost is **not** used for ERPNext. All authentication happens inside Frappe.

## Why a named volume?

macOS Docker Desktop's VirtioFS bind mount is unstable for Frappe `filelock` operations (`OSError [Errno 5] Input/output error in filelock.__exit__`). Named volumes live inside the Docker VM (linuxkit) on native ext4, outside the host filesystem — full speed and stability. The volume is declared at the top of `compose.yml.j2`; compose merge semantics merge top-level `volumes:` across `-f` files.

Blank reset wipes the volume via `docker compose down -v` + `docker volume prune -f -a` in `blank-reset.yml`. Setting `erpnext_data_dir` is deprecated post-P0.1.

## Requirements

- Docker Desktop for Mac (ARM64)
- `pazny.mariadb` role (or equivalent MariaDB on the shared network)
- `redis_docker: true` (ERPNext uses Redis cache/queue/socketio)
- `stacks_shared_network` defined at the play level

## Variables

| Variable | Default | Description |
|---|---|---|
| `erpnext_version` | `v15.98.1` | Pinned for CVE-2026-27471 (CVSS 9.3 unauth doc access) |
| `erpnext_domain` | `erp.dev.local` | Public hostname |
| `erpnext_port` | `8082` | Exposed on `127.0.0.1` only (or LAN if `services_lan_access`) |
| `erpnext_site_name` | `erp.dev.local` | Frappe site key |
| `erpnext_admin_password` | *(from credentials)* | Administrator login, rotated via `global_password_prefix` |
| `erpnext_mem_limit` | `{{ docker_mem_limit_standard }}` | Applied to each of the 6 services |

Secrets (`erpnext_admin_password`, `mariadb_root_password`, `redis_password`) stay in the top-level `default.credentials.yml` so blank-reset prefix rotation continues to work.

## Usage

From `tasks/stacks/stack-up.yml`, gate on `install_erpnext`:

```yaml
# Before b2b compose up
- name: "[Stack] ERPNext render (pazny.erpnext role)"
  ansible.builtin.include_role:
    name: pazny.erpnext
  when: install_erpnext | default(false)

# ... stack-up.yml renders base b2b compose + docker compose up ...

# After b2b compose up
- name: "[Stack] ERPNext post-start recovery (pazny.erpnext → post.yml)"
  ansible.builtin.include_role:
    name: pazny.erpnext
    tasks_from: post.yml
  when: install_erpnext | default(false)
```

## Rollback

Revert the commit that introduced this role and:

1. Restore the 6 `erpnext-*` service blocks + top-level `volumes: erpnext_sites` in `templates/stacks/b2b/docker-compose.yml.j2`
2. Restore `tasks/stacks/erpnext_post.yml` and the `include_tasks` call from `tasks/stacks/stack-up.yml`

The override file at `~/stacks/b2b/overrides/erpnext.yml` becomes dead — delete it manually if the rollback is permanent. The named volume `b2b_erpnext_sites` is unaffected and keeps ERPNext data intact.
