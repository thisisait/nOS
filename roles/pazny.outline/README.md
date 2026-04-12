# pazny.outline

Ansible role for deploying **Outline** (team wiki / knowledge base) as a compose override fragment in the devBoxNOS `b2b` stack.

Part of [devBoxNOS](../../README.md) Wave 2.2 role extraction.

## What it does

Single `outline` service with native Authentik OIDC SSO (env-var based). No post-start setup — user accounts are provisioned on first OIDC login.

Single invocation from `tasks/stacks/stack-up.yml`:

- **Main (`tasks/main.yml`)** — runs *before* `docker compose up b2b`:
  - Creates `{{ outline_data_dir }}` on the host
  - Renders `templates/compose.yml.j2` into `{{ stacks_dir }}/b2b/overrides/outline.yml`
  - Notifies `Restart outline` if the override changed

## Requirements

- Docker Desktop for Mac (ARM64)
- `install_postgresql: true` (Outline uses Postgres as primary datastore)
- `redis_docker: true` (Outline uses Redis for queues + websocket pub/sub)
- `stacks_shared_network` defined at the play level
- Optional: `install_authentik: true` enables native OIDC env vars

## Variables

| Variable | Default | Description |
|---|---|---|
| `outline_version` | `latest` | `outlinewiki/outline` image tag |
| `outline_domain` | `wiki.dev.local` | Public hostname |
| `outline_port` | `3005` | Exposed on `127.0.0.1` only (or LAN if `services_lan_access`) |
| `outline_data_dir` | `~/outline/data` | Host bind mount (overridden by `external-paths.yml` on SSD setups) |
| `outline_db_name` | `outline` | PostgreSQL database name |
| `outline_db_user` | `outline` | PostgreSQL user |
| `outline_mem_limit` | `{{ docker_mem_limit_standard }}` | Container memory limit |

Secrets (`outline_db_password`, `outline_secret_key`, `outline_utils_secret`) stay in the top-level `default.credentials.yml`. `outline_secret_key` and `outline_utils_secret` are auto-regenerated on `blank=true` runs via `openssl rand -hex 32` in `main.yml` (because changing them invalidates on-disk encrypted data — deliberate destruction of state).

OIDC client id/secret come from the centralized `authentik_oidc_apps` list in `default.config.yml` via the derived `authentik_oidc_outline_client_id` / `authentik_oidc_outline_client_secret` variables.

## Usage

From `tasks/stacks/stack-up.yml`, gate on `install_outline`:

```yaml
- name: "[Stack] Outline render (pazny.outline role)"
  ansible.builtin.include_role:
    name: pazny.outline
  when: install_outline | default(false)
```

## Rollback

Revert the commit and restore the `outline` service block in `templates/stacks/b2b/docker-compose.yml.j2`. Delete the dead `~/stacks/b2b/overrides/outline.yml`.
