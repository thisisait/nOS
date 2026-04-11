# pazny.mariadb

Ansible role for deploying **MariaDB** as a compose override fragment in the devBoxNOS `infra` stack. Foundation database for WordPress, Nextcloud, ERPNext, FreeScout, and FreePBX.

Part of [devBoxNOS](../../README.md) Wave 2 role extraction pilot. Second of three base roles (`pazny.glasswing`, **`pazny.mariadb`**, `pazny.grafana`).

## What it does

Two invocation modes from `tasks/stacks/core-up.yml`:

1. **Main (`tasks/main.yml`)** — runs *before* `docker compose up infra`:
   - Creates `{{ mariadb_data_dir }}` on the host
   - Renders `templates/compose.yml.j2` into `{{ stacks_dir }}/infra/overrides/mariadb.yml`
   - The override is picked up by core-up's `find + -f` loop and merged into the infra compose project
   - Notifies `Restart mariadb` if the override template changed

2. **Post (`tasks/post.yml`)** — runs *after* `docker compose up infra --wait`:
   - Waits for MariaDB to accept TCP connections (18 × 5s retry)
   - On auth failure, pauses with operator-friendly reset instructions
   - Drops the `test` database (hardening)
   - Creates databases listed in `mariadb_databases`
   - Creates users listed in `mariadb_users` with host `%` (so containers on the shared network reach MariaDB via the gateway IP, not `127.0.0.1`)

## Requirements

- Docker Desktop for Mac (ARM64)
- `community.mysql` collection (for `mysql_info`, `mysql_db`, `mysql_user`)
- `stacks_shared_network` defined at the play level (`infra_net` and the external shared network must already exist in the base compose file)
- A top-level `Restart mariadb` handler in the consuming playbook (also provided role-local as a fallback)

## Variables

| Variable | Default | Description |
|---|---|---|
| `mariadb_version` | `11.4.10` | Pinned for CVE-2026-32710 (CVSS 8.6 buffer overflow) |
| `mariadb_port` | `3306` | Exposed on `127.0.0.1` only |
| `mariadb_data_dir` | `~/mariadb/data` | Host bind mount for persistence |
| `mariadb_mem_limit` | `{{ docker_mem_limit_standard }}` | Defaults to `1g` |
| `mariadb_cpus` | `{{ docker_cpus_standard }}` | Defaults to `1.0` |
| `mariadb_root_password` | *(from credentials)* | Set via `global_password_prefix` rotation |
| `mariadb_databases` | `[]` (top-level seed) | List of `{name}` dicts, read from `default.config.yml` at runtime |
| `mariadb_users` | `[]` (top-level seed) | List of `{name, password, priv, host}` dicts, same |

Secrets and the seed database/user lists stay in the top-level `default.credentials.yml` / `default.config.yml` so the blank-reset prefix rotation pattern continues to work.

## Usage

From `tasks/stacks/core-up.yml`, gate the role invocations on `install_mariadb`:

```yaml
# Before infra compose up
- name: "[Core] MariaDB render + dirs (pazny.mariadb role)"
  ansible.builtin.include_role:
    name: pazny.mariadb
  when: install_mariadb | default(false)

# ... core-up.yml renders base infra compose + runs docker compose up ...

# After infra compose up
- name: "[Core] MariaDB post-start DB/user setup"
  ansible.builtin.include_role:
    name: pazny.mariadb
    tasks_from: post.yml
  when:
    - install_mariadb | default(false)
    - _core_infra_enabled | bool
```

## Rollback

Revert the commit that introduced this role and:

1. Restore the mariadb service block in `templates/stacks/infra/docker-compose.yml.j2`
2. Restore `tasks/iiab/mariadb.yml` and `tasks/iiab/mariadb_setup.yml`
3. Restore the `include_tasks` calls in `main.yml` and `tasks/stacks/core-up.yml`

The override file at `~/stacks/infra/overrides/mariadb.yml` becomes dead — delete it manually if the rollback is permanent.
