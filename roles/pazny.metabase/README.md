# pazny.metabase

Ansible role for deploying **Metabase BI** as a compose override fragment in the devBoxNOS `data` stack. Uses PostgreSQL from the infra stack.

Part of [devBoxNOS](../../README.md) Wave 2.2 role extraction (voip-engineering-data worker).

## What it does

Two invocation modes from `tasks/stacks/stack-up.yml`:

1. **Main (`tasks/main.yml`)** — runs *before* `docker compose up data`:
   - Creates `{{ metabase_data_dir }}` on the host
   - Renders `templates/compose.yml.j2` into `{{ stacks_dir }}/data/overrides/metabase.yml`
   - Notifies `Restart metabase` if the override template changed

2. **Post (`tasks/post.yml`)** — runs *after* `docker compose up data --wait`:
   - Waits for `/api/health` (20 × 10s retry)
   - On first run: `POST /api/setup` creates the admin user + DB config in one call (idempotent — returns 403 if already set up)
   - On subsequent runs: reconverges admin password via `POST /api/session` (with previous prefix) → `PUT /api/user/1/password`

## Requirements

- Docker Desktop for Mac (ARM64)
- PostgreSQL reachable at `postgresql:5432` on `{{ stacks_shared_network }}` (provided by `pazny.postgresql`)
- A top-level `Restart metabase` handler in the consuming playbook (also provided role-local)

## Variables

| Variable | Default | Description |
|---|---|---|
| `metabase_version` | `latest` | `metabase/metabase` image tag |
| `metabase_port` | `3002` | HTTP port bound on `127.0.0.1` |
| `metabase_data_dir` | `~/metabase` | Host bind mount |
| `metabase_db_name` | `metabase` | PostgreSQL database |
| `metabase_db_user` | `metabase` | PostgreSQL username |
| `metabase_db_password` | *(from credentials)* | `{{ global_password_prefix }}_pw_metabase` |
| `metabase_admin_email` | `{{ default_admin_email }}` | First-run admin user email |
| `metabase_admin_password` | *(from credentials)* | `{{ global_password_prefix }}_pw_metabase_admin` |
| `metabase_timezone` | `Europe/Prague` | JAVA_TIMEZONE |
| `metabase_mem_limit` | `{{ docker_mem_limit_standard }}` | Defaults to `1g` |

## Usage

From `tasks/stacks/stack-up.yml`:

```yaml
- name: "[Stacks] Metabase render (pazny.metabase role)"
  ansible.builtin.include_role:
    name: pazny.metabase
  when: install_metabase | default(false)

# ... stack-up.yml runs docker compose up data ...

- name: "[Stacks] Metabase post-start setup"
  ansible.builtin.include_role:
    name: pazny.metabase
    tasks_from: post.yml
  when:
    - install_metabase | default(false)
    - "'data' in _remaining_stacks"
```

## Rollback

Revert the commit, restore the metabase service block in `templates/stacks/data/docker-compose.yml.j2`, and restore `tasks/iiab/metabase_post.yml`.
