# pazny.hedgedoc

Ansible role for deploying **HedgeDoc** (real-time collaborative markdown editor) as a compose override fragment in the nOS `b2b` stack.

Part of [nOS](../../README.md) Wave 2.2+ role extraction.

## What it does

Single `hedgedoc` service with native Authentik OIDC SSO via `CMD_OAUTH2_*` env vars. No post-start setup — user accounts are provisioned on first OIDC login.

Single invocation from `tasks/stacks/stack-up.yml`:

- **Main (`tasks/main.yml`)** — runs *before* `docker compose up b2b`:
  - Creates `{{ hedgedoc_data_dir }}` (uploads) on the host
  - Renders `templates/compose.yml.j2` into `{{ stacks_dir }}/b2b/overrides/hedgedoc.yml`
  - Notifies `Restart hedgedoc` if the override changed

## Requirements

- Docker Desktop for Mac (ARM64 — `quay.io/hedgedoc/hedgedoc` ships multi-arch)
- `install_postgresql: true` (HedgeDoc uses Postgres as primary datastore)
- `stacks_shared_network` defined at the play level
- Optional: `install_authentik: true` enables native OIDC env vars + `NODE_EXTRA_CA_CERTS` mount

## Variables

| Variable | Default | Description |
|---|---|---|
| `hedgedoc_version` | `1.10.7` | `quay.io/hedgedoc/hedgedoc` image tag (pinned stable) |
| `hedgedoc_domain` | `hedgedoc.{{ instance_tld }}` | Public hostname |
| `hedgedoc_port` | `3012` | Exposed on `127.0.0.1` only (or LAN if `services_lan_access`) |
| `hedgedoc_data_dir` | `~/hedgedoc/uploads` | Host bind mount for user image uploads (overridden by `external-paths.yml` on SSD setups) |
| `hedgedoc_db_name` | `hedgedoc` | PostgreSQL database name |
| `hedgedoc_db_user` | `hedgedoc` | PostgreSQL user |
| `hedgedoc_mem_limit` | `{{ docker_mem_limit_standard }}` | Container memory limit |

Secrets (`hedgedoc_db_password`, `hedgedoc_session_secret`) stay in the top-level `default.credentials.yml`. `hedgedoc_session_secret` is auto-regenerated every run via `openssl rand -hex 32` in `main.yml` (safe stateless group — session cookies are re-issuable, notes in DB are preserved).

OIDC client id/secret come from the centralized `authentik_oidc_apps` list in `default.config.yml` via the derived `authentik_oidc_hedgedoc_client_id` / `authentik_oidc_hedgedoc_client_secret` variables.

## Usage

From `tasks/stacks/stack-up.yml`, gate on `install_hedgedoc`:

```yaml
- name: "[Stacks] pazny.hedgedoc render"
  ansible.builtin.include_role:
    name: pazny.hedgedoc
  when: install_hedgedoc | default(false)
```

## Rollback

Revert the commit. Delete the dead `~/stacks/b2b/overrides/hedgedoc.yml`. Drop `hedgedoc` Postgres DB and user if created.
