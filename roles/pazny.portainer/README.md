# pazny.portainer

Ansible role for deploying **Portainer CE** as a compose override fragment in the devBoxNOS `infra` stack. Docker management UI with Authentik OAuth2 (native via Settings API).

Part of [devBoxNOS](../../README.md) Wave 2.2 role extraction (infra-edge unit).

## What it does

Two invocation modes from `tasks/stacks/core-up.yml`:

1. **Main (`tasks/main.yml`)** — runs *before* `docker compose up infra`:
   - Creates `{{ portainer_data_dir }}` on the host
   - Renders `templates/compose.yml.j2` into `{{ stacks_dir }}/infra/overrides/portainer.yml`
   - The override is picked up by core-up's `find + -f` loop and merged into the infra compose project
   - Notifies `Restart portainer` if the override template changed

2. **Post (`tasks/post.yml`)** — runs *after* `docker compose up infra --wait`:
   - Waits for `/api/status` (12 × 10s)
   - Creates the admin user via `POST /api/users/admin/init` (fresh install)
   - **Password reconverge** — session-based `PUT /api/users/1/passwd` using `previous_password_prefix` as the OLD auth. **PARTIAL**: only rotates by one prefix at a time. Two+ steps drift → manual reset required.
   - When `install_authentik` is true: configures OAuth2/OIDC settings via `PUT /api/settings` using the Portainer Client ID/Secret from the centralized `authentik_oidc_apps` registry

## Requirements

- Docker Desktop for Mac (ARM64)
- `docker-socket-proxy` service in the base `templates/stacks/infra/docker-compose.yml.j2` (shared with Traefik — gate is `install_portainer | install_traefik`)
- For OAuth2 config: `install_authentik` + `authentik_oidc_portainer_client_id` / `authentik_oidc_portainer_client_secret` available as play-level vars (derived from `authentik_oidc_apps`)

## Variables

| Variable | Default | Description |
|---|---|---|
| `portainer_version` | `2.27.3` | Pinned for CVE-2025-68121 (transitive Go TLS CVSS 10.0) |
| `portainer_port` | `9002` | Exposed on `127.0.0.1` by default (9000/9001 reserved for RustFS) |
| `portainer_domain` | `portainer.dev.local` | Public domain (used for OAuth2 redirect URI) |
| `portainer_data_dir` | `~/portainer` | Host bind mount for SQLite persistence |
| `portainer_mem_limit` | `{{ docker_mem_limit_standard }}` | Defaults to `1g` |
| `portainer_cpus` | `{{ docker_cpus_standard }}` | Defaults to `1.0` |
| `portainer_admin_password` | *(from credentials)* | Set via `global_password_prefix` rotation |

## Usage

From `tasks/stacks/core-up.yml`, gate the role invocations on `install_portainer`:

```yaml
# Before infra compose up
- name: "[Core] Portainer render (pazny.portainer role)"
  ansible.builtin.include_role:
    name: pazny.portainer
  when: install_portainer | default(false)

# ... core-up.yml renders base infra compose + runs docker compose up ...

# After infra compose up
- name: "[Core] Portainer post-start admin + OAuth2"
  ansible.builtin.include_role:
    name: pazny.portainer
    tasks_from: post.yml
  when:
    - install_portainer | default(false)
    - _core_infra_enabled | bool
```

## Known limitations

- **Password reconverge is PARTIAL** — only rotates by one prefix (`previous_password_prefix` → `global_password_prefix`). If the admin password drifts by two or more steps, the session-based PUT can't recover and the operator must reset manually.
- **OAuth2 config needs manual UI step** — Portainer doesn't fully support env var OIDC; this role configures the REST API endpoint, but initial redirect URI binding may still need manual verification in the UI.

## Rollback

Revert the commit that introduced this role and:

1. Restore the portainer service block in `templates/stacks/infra/docker-compose.yml.j2`
2. The legacy `tasks/iiab/portainer.yml` + `tasks/iiab/portainer_post.yml` are untouched (coordinator deletes them in Phase B)

The override file at `~/stacks/infra/overrides/portainer.yml` becomes dead — delete it manually if the rollback is permanent.
