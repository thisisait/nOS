# pazny.firefly

Ansible role for deploying **Firefly III** (personal / family finance manager) as a compose override fragment in the nOS `b2b` stack.

## What it does

Single `firefly` service wired into the `b2b` stack with MariaDB (primary datastore) + Redis (cache / session) and Authentik SSO via **`remote_user_guard`** — an nginx `auth_request` forwards the user to Authentik's proxy outpost and injects `REMOTE_USER` / `REMOTE_EMAIL` headers, which Firefly reads to auto-provision accounts on first login. No post-start setup required.

Single invocation from `tasks/stacks/stack-up.yml`:

- **Main (`tasks/main.yml`)** — runs *before* `docker compose up b2b`:
  - Creates `{{ firefly_upload_dir }}` and `{{ firefly_export_dir }}` on the host
  - Renders `templates/compose.yml.j2` into `{{ stacks_dir }}/b2b/overrides/firefly.yml`
  - Deploys + enables the nginx vhost (`templates/nginx/sites-available/firefly.conf`)
  - Notifies `Restart firefly` / `Restart nginx` on changes

## Requirements

- Docker Desktop for Mac (ARM64)
- `install_mariadb: true` — MariaDB is the primary datastore; the `firefly` database + user are auto-provisioned by `pazny.mariadb/tasks/post.yml` (see INTEGRATION.md)
- `redis_docker: true` — session / cache driver
- `stacks_shared_network` defined at the play level
- `install_authentik: true` (recommended) — enables the `remote_user_guard` env vars and nginx forward-auth include

## Variables

| Variable | Default | Description |
|---|---|---|
| `firefly_version` | `version-6.2.21` | `fireflyiii/core` image tag (pin to a specific stable release) |
| `firefly_domain` | `firefly.{{ instance_tld }}` | Public hostname |
| `firefly_port` | `3014` | Exposed on `127.0.0.1` only (or LAN if `services_lan_access`) |
| `firefly_upload_dir` | `~/firefly/upload` | Attachments bind mount |
| `firefly_export_dir` | `~/firefly/export` | Export bind mount |
| `firefly_db_name` | `firefly` | MariaDB database name |
| `firefly_db_user` | `firefly` | MariaDB user |
| `firefly_site_owner` | `{{ default_admin_email }}` | Site-owner email (used by Firefly for system notifications) |
| `firefly_tz` | `Europe/Prague` | Container TZ |
| `firefly_default_language` | `en_US` | UI language |
| `firefly_mem_limit` | `{{ docker_mem_limit_standard }}` (`1g`) | Container memory limit |
| `firefly_cpus` | `{{ docker_cpus_standard }}` (`1.0`) | Container CPU limit |

## Secrets

Stay in `default.credentials.yml`:

- `firefly_db_password` — MariaDB user password
- `firefly_app_key` — Laravel `APP_KEY` (`base64:<32b>`). Auto-generated on `blank=true` runs via `main.yml` (see INTEGRATION.md). **Changing this invalidates on-disk encrypted data.**

## SSO (Authentik)

Firefly uses **proxy auth** (`remote_user_guard`), not native OIDC. The flow:

1. User hits `https://firefly.dev.local`
2. nginx `auth_request` → Authentik embedded proxy outpost → Authentik login
3. On success, outpost sets `X-authentik-username` / `X-authentik-email` headers
4. nginx `authentik-proxy-auth.conf` snippet maps those to `Remote-User` / `Remote-Email` *and* Firefly-specific `REMOTE_USER` / `REMOTE_EMAIL` headers (see vhost)
5. Firefly reads `REMOTE_USER` → finds-or-creates a local account

Access-tier: **Tier 2 (manager)** — finance data is sensitive. See `authentik_app_tiers` in `default.config.yml`.

## Integration points

See **`INTEGRATION.md`** for the exact `default.config.yml` / `default.credentials.yml` / `main.yml` / `tasks/stacks/core-up.yml` / `tasks/stacks/stack-up.yml` edits required to wire the role in.

## Smoke test

```bash
# After ansible-playbook main.yml -K -e install_firefly=true
curl -sSf -o /dev/null -w "%{http_code}\n" -k https://firefly.dev.local
# Expect: 302 (redirect to Authentik login) when not authenticated
docker compose -p b2b logs firefly | tail -20
```
