# pazny.infisical

Ansible role for deploying **Infisical CE** (secrets vault) as a compose override fragment in the devBoxNOS `infra` stack. Foundation secrets store for infra bootstrap and cross-service secret distribution.

Part of [devBoxNOS](../../README.md) Wave 2.2 role extraction (infra IAM unit).

## What it does

Two invocation modes from `tasks/stacks/core-up.yml`:

1. **Main (`tasks/main.yml`)** — runs *before* `docker compose up infra`:
   - Creates `{{ infisical_data_dir }}` on the host
   - Renders `templates/compose.yml.j2` into `{{ stacks_dir }}/infra/overrides/infisical.yml`
   - The override is picked up by core-up's `find + -f` loop and merged into the infra compose project
   - Notifies `Restart infisical` if the override template changed

2. **Post (`tasks/post.yml`)** — runs *after* `docker compose up infra --wait`:
   - Waits for `http://127.0.0.1:{infisical_port}/api/status` (20 × 5s retry)
   - Prints dashboard URL + first-user-is-admin hint

## Requirements

- Docker Desktop for Mac (ARM64)
- PostgreSQL + Redis running in the same infra compose project (both provide bootstrap connection URIs)
- `stacks_shared_network` external network already created at play level
- Play-level `Restart infisical` handler (also provided role-local as a fallback)

## Variables

| Variable | Default | Description |
|---|---|---|
| `infisical_version` | `latest` | Image tag (overridable via `version_policy`) |
| `infisical_domain` | `vault.dev.local` | Public domain behind nginx reverse proxy |
| `infisical_port` | `8075` | Exposed on `127.0.0.1` only |
| `infisical_data_dir` | `~/infisical` | Host bind mount for persistence |
| `infisical_db_name` | `infisical` | PostgreSQL database name |
| `infisical_db_user` | `infisical` | PostgreSQL user |
| `infisical_mem_limit` | `{{ docker_mem_limit_standard }}` | Defaults to `1g` |
| `infisical_cpus` | `{{ docker_cpus_standard }}` | Defaults to `1.0` |
| `infisical_encryption_key` | *(from credentials)* | Prefix-rotated |
| `infisical_auth_secret` | *(from credentials)* | Prefix-rotated |
| `infisical_db_password` | *(from credentials)* | Prefix-rotated |

Secrets stay in the top-level `default.credentials.yml` so the blank-reset prefix rotation pattern continues to work.

## Usage

From `tasks/stacks/core-up.yml`, gate the role invocations on `install_infisical`:

```yaml
# Before infra compose up
- name: "[Core] Infisical render + dirs (pazny.infisical role)"
  ansible.builtin.include_role:
    name: pazny.infisical
  when: install_infisical | default(false)

# ... core-up.yml renders base infra compose + runs docker compose up ...

# After infra compose up
- name: "[Core] Infisical post-start wait-for-ready"
  ansible.builtin.include_role:
    name: pazny.infisical
    tasks_from: post.yml
  when:
    - install_infisical | default(false)
    - _core_infra_enabled | bool
```

## Rollback

Revert the commit that introduced this role and:

1. Restore the `infisical` service block in `templates/stacks/infra/docker-compose.yml.j2`
2. Restore `tasks/stacks/infisical_post.yml`
3. Restore the `include_tasks` call in `tasks/stacks/core-up.yml`

The override file at `~/stacks/infra/overrides/infisical.yml` becomes dead — delete it manually if the rollback is permanent.
