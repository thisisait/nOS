# pazny.redis

Ansible role for deploying **Redis** as a compose override fragment in the devBoxNOS `infra` stack. Shared cache / message broker for Authentik (sessions), Infisical (cache), and n8n (queue).

Part of [devBoxNOS](../../README.md) Wave 2.2 infra-db-peers extraction (`pazny.mariadb`, `pazny.postgresql`, **`pazny.redis`**).

## What it does

Single invocation mode from `tasks/stacks/core-up.yml` — runs *before* `docker compose up infra`:

- Creates `{{ redis_data_dir }}` on the host
- Renders `templates/compose.yml.j2` into `{{ stacks_dir }}/infra/overrides/redis.yml`
- The override is picked up by core-up's `find + -f` loop and merged into the infra compose project
- Notifies `Restart redis` if the override template changed

There is **no `post.yml`** — Redis needs no post-start bootstrap. Authentication (`--requirepass`) and persistence (`--appendonly yes`) are set in the compose `command:` line.

## Requirements

- Docker Desktop for Mac (ARM64)
- `stacks_shared_network` defined at the play level (`infra_net` and the external shared network must already exist in the base compose file)
- A top-level `Restart redis` handler in the consuming playbook (also provided role-local as a fallback)

## Install toggle — `redis_docker`, not `install_redis`

Because devBoxNOS can run Redis either as a Homebrew service or as a Docker container, the toggle is historically named **`redis_docker`**, not `install_redis`. Preserve that naming in `core-up.yml` wiring:

```yaml
- name: "[Core] Redis render + dirs (pazny.redis role)"
  ansible.builtin.include_role:
    name: pazny.redis
  when: redis_docker | default(false)
```

## Variables

| Variable | Default | Description |
|---|---|---|
| `redis_version` | `7.4.6-alpine` | Pinned for CVE-2025-49844 (CVSS 10.0 RediShell RCE) |
| `redis_port` | `6379` | Exposed on `127.0.0.1` only |
| `redis_data_dir` | `~/redis/data` | Host bind mount for AOF persistence |
| `redis_mem_limit` | `{{ docker_mem_limit_light }}` | Defaults to `512m`; container also self-caps at `256m` via `--maxmemory` |
| `redis_cpus` | `{{ docker_cpus_light }}` | Defaults to `0.5` |
| `redis_password` | *(from credentials)* | Set via `global_password_prefix` rotation |

## Usage

From `tasks/stacks/core-up.yml`:

```yaml
- name: "[Core] Redis render + dirs (pazny.redis role)"
  ansible.builtin.include_role:
    name: pazny.redis
  when: redis_docker | default(false)
```

No post-start include needed.

## Rollback

Revert the commit that introduced this role and:

1. Restore the redis service block in `templates/stacks/infra/docker-compose.yml.j2`
2. Restore the `include_role` call in `tasks/stacks/core-up.yml`

The override file at `~/stacks/infra/overrides/redis.yml` becomes dead — delete it manually if the rollback is permanent.
