# pazny.freescout

Ansible role for deploying **FreeScout** (Laravel helpdesk / ticketing) as a compose override fragment in the devBoxNOS `b2b` stack.

Part of [devBoxNOS](../../README.md) Wave 2.2 role extraction.

## What it does

Single `freescout` service plus post-start admin onboarding via Laravel Artisan.

Two invocation modes from `tasks/stacks/stack-up.yml`:

1. **Main (`tasks/main.yml`)** — runs *before* `docker compose up b2b`:
   - Creates `{{ freescout_data_dir }}` on the host
   - Renders `templates/compose.yml.j2` into `{{ stacks_dir }}/b2b/overrides/freescout.yml`
   - Notifies `Restart freescout` if the override changed

2. **Post (`tasks/post.yml`)** — runs *after* `docker compose up b2b --wait`:
   - Waits for FreeScout HTTP to accept requests (accepts 200/302/500)
   - First-run: `artisan freescout:create-user --role=admin` if the admin email has no user
   - Every run: `artisan tinker` UPDATE of the bcrypt password hash for the admin user (reconverge for rotated `global_password_prefix`)

FreeScout has no REST API for onboarding, which is why Artisan CLI calls via `docker compose exec` are the only path.

## Requirements

- Docker Desktop for Mac (ARM64)
- `pazny.mariadb` role (or equivalent MariaDB). `freescout` database + user are seeded via `mariadb_databases` / `mariadb_users` in `default.config.yml`
- `stacks_shared_network` defined at the play level

## Variables

| Variable | Default | Description |
|---|---|---|
| `freescout_version` | `php8.3-1.17.152` | `tiredofit/freescout` image tag (past CVE-2026-28289) |
| `freescout_domain` | `helpdesk.dev.local` | Public hostname |
| `freescout_port` | `8090` | Exposed on `127.0.0.1` only (or LAN if `services_lan_access`) |
| `freescout_data_dir` | `~/freescout/data` | Host bind mount (overridden by `external-paths.yml` on SSD setups) |
| `freescout_db_name` | `freescout` | MariaDB database name |
| `freescout_db_user` | `freescout` | MariaDB user |
| `freescout_admin_email` | `{{ default_admin_email }}` | Admin login email |
| `freescout_timezone` | `Europe/Prague` | Container TZ |
| `freescout_mem_limit` | `{{ docker_mem_limit_light }}` | Container memory limit |

Secrets (`freescout_db_password`, `freescout_admin_password`) stay in the top-level `default.credentials.yml` for prefix rotation.

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

Revert the commit and restore the `freescout` service block in `templates/stacks/b2b/docker-compose.yml.j2` plus `tasks/iiab/freescout_post.yml`. Delete the dead `~/stacks/b2b/overrides/freescout.yml`.
