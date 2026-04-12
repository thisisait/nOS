# pazny.postgresql

Ansible role for deploying **PostgreSQL** as a compose override fragment in the devBoxNOS `infra` stack. Shared relational database for Authentik, Infisical, Outline, Metabase, Apache Superset, Paperclip, jsOS, and (historically) Mattermost.

Part of [devBoxNOS](../../README.md) Wave 2.2 infra-db-peers extraction (`pazny.mariadb`, **`pazny.postgresql`**, `pazny.redis`).

## What it does

Two invocation modes from `tasks/stacks/core-up.yml`:

1. **Main (`tasks/main.yml`)** — runs *before* `docker compose up infra`:
   - Creates `{{ postgresql_data_dir }}` on the host
   - Renders `templates/compose.yml.j2` into `{{ stacks_dir }}/infra/overrides/postgresql.yml`
   - The override is picked up by core-up's `find + -f` loop and merged into the infra compose project
   - Notifies `Restart postgresql` if the override template changed

2. **Post (`tasks/post.yml`)** — runs *after* `docker compose up infra --wait`:
   - Waits for PostgreSQL to accept TCP connections (18 × 5s retry via `pg_isready`)
   - Enables `pgcrypto` extension in `template1` (inherited by new DBs)
   - On `blank=true` reset, drops the existing service databases and roles before recreating them
   - Restarts Authentik + Infisical after a blank DROP so they re-bootstrap cleanly
   - Creates service databases: `outline`, `metabase`, `superset`, plus (conditionally) `authentik`, `infisical`, `mattermost`, `paperclip`, `jsos`
   - Creates matching DB users with generated passwords
   - Enables `pgcrypto` in each service DB (required for bcrypt password hash reconverge in Metabase/Superset/n8n)
   - Grants all privileges + transfers ownership to each service user

## Requirements

- Docker Desktop for Mac (ARM64)
- `community.postgresql` collection (declared in `meta/main.yml`; current post.yml uses `docker compose exec psql` but future-proofed)
- `stacks_shared_network` defined at the play level (`infra_net` and the external shared network must already exist in the base compose file)
- A top-level `Restart postgresql` handler in the consuming playbook (also provided role-local as a fallback)

## Variables

| Variable | Default | Description |
|---|---|---|
| `postgresql_version` | `16.13-alpine` | Pinned for CVE-2026-2005/2006/2007 (pgcrypto RCE + multibyte RCE + buffer overflow) |
| `postgresql_port` | `5432` | Exposed on `127.0.0.1` only |
| `postgresql_root_user` | `postgres` | Superuser |
| `postgresql_root_password` | *(from credentials)* | Set via `global_password_prefix` rotation |
| `postgresql_data_dir` | `~/postgresql/data` | Host bind mount for persistence |
| `postgresql_mem_limit` | `{{ docker_mem_limit_standard }}` | Defaults to `1g` |
| `postgresql_cpus` | `{{ docker_cpus_standard }}` | Defaults to `1.0` |

Service database/user/password triples (Authentik, Infisical, Outline, Metabase, Superset, Mattermost, Paperclip, jsOS) stay in the top-level `default.config.yml` / `default.credentials.yml` so the blank-reset prefix rotation pattern continues to work.

## Usage

From `tasks/stacks/core-up.yml`, gate the role invocations on `install_postgresql`:

```yaml
# Before infra compose up
- name: "[Core] PostgreSQL render + dirs (pazny.postgresql role)"
  ansible.builtin.include_role:
    name: pazny.postgresql
  when: install_postgresql | default(false)

# ... core-up.yml renders base infra compose + runs docker compose up ...

# After infra compose up
- name: "[Core] PostgreSQL post-start DB/user setup"
  ansible.builtin.include_role:
    name: pazny.postgresql
    tasks_from: post.yml
  when:
    - install_postgresql | default(false)
    - _core_infra_enabled | bool
```

## Rollback

Revert the commit that introduced this role and:

1. Restore the postgresql service block in `templates/stacks/infra/docker-compose.yml.j2`
2. Restore `tasks/stacks/postgresql_setup.yml`
3. Restore the `include_tasks` / `include_role` calls in `tasks/stacks/core-up.yml`

The override file at `~/stacks/infra/overrides/postgresql.yml` becomes dead — delete it manually if the rollback is permanent.
