# pazny.erpnext

Ansible role for deploying **ERPNext** (Frappe framework) as a compose override fragment in the devBoxNOS `b2b` stack. Provides CRM, ERP, HR, and Accounting capabilities.

Part of [devBoxNOS](../../README.md) Wave 2.2 role extraction.

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
