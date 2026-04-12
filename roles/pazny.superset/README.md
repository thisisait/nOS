# pazny.superset

Ansible role for deploying **Apache Superset** as a compose override fragment in the devBoxNOS `data` stack. Uses PostgreSQL + Redis from the infra stack.

Part of [devBoxNOS](../../README.md) Wave 2.2 role extraction (voip-engineering-data worker).

> **Version pin:** `6.0.0` — addresses CVE-2026-23982 (auth bypass) and CVE-2025-48912 (RLS SQLi). Do not downgrade.

## What it does

Two invocation modes from `tasks/stacks/stack-up.yml`:

1. **Main (`tasks/main.yml`)** — runs *before* `docker compose up data`:
   - Creates `{{ superset_data_dir }}` on the host
   - Renders `templates/compose.yml.j2` into `{{ stacks_dir }}/data/overrides/superset.yml`
   - Notifies `Restart superset` if the override template changed

2. **Post (`tasks/post.yml`)** — runs *after* `docker compose up data --wait`:
   - Runs `superset db upgrade` (retried 12 × 10s until the container is ready)
   - Runs `superset init` (roles + permissions)
   - Runs `superset fab create-admin` to create the initial admin user (idempotent — prints `was created` only on first run)

## Requirements

- Docker Desktop for Mac (ARM64)
- PostgreSQL reachable at `postgresql:5432`, Redis reachable at `redis:6379` — both on `{{ stacks_shared_network }}`
- A top-level `Restart superset` handler in the consuming playbook (also provided role-local)

## Variables

| Variable | Default | Description |
|---|---|---|
| `superset_version` | `6.0.0` | Pinned for CVE-2026-23982 / CVE-2025-48912 |
| `superset_port` | `8089` | HTTP port bound on `127.0.0.1` |
| `superset_data_dir` | `~/superset` | Host bind mount |
| `superset_db_name` | `superset` | PostgreSQL database |
| `superset_db_user` | `superset` | PostgreSQL username |
| `superset_db_password` | *(from credentials)* | `{{ global_password_prefix }}_pw_superset` |
| `superset_secret_key` | *(from credentials)* | `{{ global_password_prefix }}_pw_superset_secret` |
| `superset_admin_email` | `{{ default_admin_email }}` | First-run admin user email |
| `superset_admin_password` | *(from credentials)* | `{{ global_password_prefix }}_pw_superset` |
| `superset_mem_limit` | `{{ docker_mem_limit_standard }}` | Defaults to `1g` |

## Usage

From `tasks/stacks/stack-up.yml`:

```yaml
- name: "[Stacks] Superset render (pazny.superset role)"
  ansible.builtin.include_role:
    name: pazny.superset
  when: install_superset | default(false)

# ... stack-up.yml runs docker compose up data ...

- name: "[Stacks] Superset post-start: db upgrade + init + admin"
  ansible.builtin.include_role:
    name: pazny.superset
    tasks_from: post.yml
  when:
    - install_superset | default(false)
    - "'data' in _remaining_stacks"
```

## Rollback

Revert the commit, restore the superset service block in `templates/stacks/data/docker-compose.yml.j2`, and restore `tasks/stacks/superset_setup.yml`.
