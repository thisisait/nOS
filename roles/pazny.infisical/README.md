# pazny.infisical

Ansible role for deploying **Infisical CE** (secrets vault) as a compose override fragment in the nOS `infra` stack. Foundation secrets store for infra bootstrap and cross-service secret distribution.

Part of [nOS](../../README.md) Wave 2.2 role extraction (infra IAM unit).

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

## SSO (Authentik — native OIDC)

Since Sprint 2a (2026-04-22) Infisical uses **native OIDC** via Authentik, not Nginx forward_auth.
Rendered only when `install_authentik` is true. Env vars consumed by Infisical CE 0.60+:

| Env var | Value |
|---|---|
| `OIDC_CLIENT_ID` | `{{ authentik_oidc_infisical_client_id }}` (default `nos-infisical`) |
| `OIDC_CLIENT_SECRET` | `{{ authentik_oidc_infisical_client_secret }}` (default `{{ global_password_prefix }}_pw_oidc_infisical`) |
| `OIDC_DISCOVERY_URL` | `https://{{ authentik_domain }}/application/o/infisical/.well-known/openid-configuration` |
| `OIDC_ISSUER` | `https://{{ authentik_domain }}/application/o/infisical/` |
| `OIDC_REDIRECT_URI` | `https://{{ infisical_domain }}/api/v1/sso/oidc/callback` |
| `SITE_URL` | `https://{{ infisical_domain }}` |

`extra_hosts: [{{ authentik_domain }}:host-gateway]` routes the container's OIDC discovery call through the host Nginx so
`auth.dev.local` resolves the same way it does from a browser.

### Required companion changes (owned by the orchestrator, not this role)

1. **`authentik_oidc_apps`** entry in `default.config.yml`:

   ```yaml
   - name: "Infisical"
     slug: "infisical"
     enabled: "{{ install_infisical | default(false) }}"
     client_id: "nos-infisical"
     client_secret: "{{ global_password_prefix }}_pw_oidc_infisical"
     redirect_uris: "https://{{ infisical_domain | default('vault.dev.local') }}/api/v1/sso/oidc/callback"
     launch_url: "https://{{ infisical_domain | default('vault.dev.local') }}"
   ```

2. **RBAC tier** — Infisical is Tier 1 (admin) in `authentik_app_tiers`; the proxy-auth entry for `infisical` should be removed.

3. **Post-start API setup (partial — stub planned).** Infisical CE does not fully wire an organization-scoped OIDC config from env vars alone:
   the env vars seed defaults, but the org's OIDC config row still needs `isActive=true` and the discovery URL attached via the admin API.
   A follow-up `tasks/post.yml` block should POST to `/api/v1/sso/config` (or `PATCH` an existing row) after the first admin bootstraps.
   Until that lands, operators either (a) toggle "Enable OIDC" once in the org Security → SSO UI, or (b) accept that the env vars alone
   suffice for a default install where admins log in via email+password first and OIDC is offered alongside.

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
