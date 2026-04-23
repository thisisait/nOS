# pazny.paperclip

Ansible role for deploying **Paperclip** — a multi-agent orchestration platform that coordinates AI agents (OpenClaw, Claude Code, Codex) via an org-chart structure — as a compose override fragment in the nOS `devops` stack.

Part of [nOS](../../README.md) Wave 2.2 role extraction batch.

## What it does

Two invocation modes from `tasks/stacks/stack-up.yml`:

1. **Main (`tasks/main.yml`)** — runs *before* `docker compose up devops`:
   - Creates `{{ paperclip_data_dir }}` on the host
   - Renders `templates/compose.yml.j2` into `{{ stacks_dir }}/devops/overrides/paperclip.yml`
   - The override is picked up by stack-up's `find + -f` loop and merged into the devops compose project
   - Notifies `Restart paperclip` if the override template changed

2. **Post (`tasks/post.yml`)** — runs *after* `docker compose up devops --wait`:
   - Registers the primary `paperclip_domain` as an allowed hostname via `pnpm paperclipai allowed-hostname`
   - Registers every entry in `service_extra_hosts` (if any) as an additional allowed hostname

> Note: the post-start logic previously lived inline in `tasks/stacks/stack-up.yml` (around the `allowed-hostname` register shell tasks). Wave 2.2 Unit 10 extracts it into this role.

## Requirements

- Docker Desktop for Mac (ARM64)
- **PostgreSQL** — Paperclip stores state in a `paperclip` database on the shared `postgresql` service. Ensure `install_postgresql: true` and the database/user are seeded (centralised in `default.config.yml` → `postgresql_databases` / `postgresql_users`).
- `stacks_shared_network` defined at the play level
- OpenClaw host-side daemon reachable at `http://host.docker.internal:{{ openclaw_gateway_port }}` (for agent routing)

## Variables

| Variable | Default | Description |
|---|---|---|
| `paperclip_version` | `latest` | GHCR image tag |
| `paperclip_domain` | `paperclip.dev.local` | Public nginx vhost hostname |
| `paperclip_port` | `3006` | Host port (3100 collides with Loki internally) |
| `paperclip_data_dir` | `~/paperclip` | Host bind mount for persistence |
| `paperclip_db_name` | `paperclip` | Postgres database name |
| `paperclip_db_user` | `paperclip` | Postgres user |
| `paperclip_db_password` | *(from credentials)* | Rotated via `global_password_prefix` |
| `paperclip_deployment_mode` | `authenticated` | Docker requires 0.0.0.0 bind |
| `paperclip_auth_secret` | *(from credentials)* | BetterAuth session secret |
| `paperclip_openclaw_url` | `http://host.docker.internal:18789` | OpenClaw gateway for agent calls |

## Usage

From `tasks/stacks/stack-up.yml`, gate both invocations on `install_paperclip`:

```yaml
# Before devops compose up
- name: "[Stacks] Paperclip render + dirs (pazny.paperclip role)"
  ansible.builtin.include_role:
    name: pazny.paperclip
  when: install_paperclip | default(false)

# ... stack-up.yml renders base devops compose + runs docker compose up ...

# After devops compose up
- name: "[Stacks] Paperclip post-start allowed-hostname registration"
  ansible.builtin.include_role:
    name: pazny.paperclip
    tasks_from: post.yml
  when: install_paperclip | default(false)
```

## Authentication & Authentik integration

**Current mode (2026-04-22):** **proxy auth + BetterAuth local accounts** (defense in depth).

Paperclip ships with [BetterAuth](https://better-auth.com) and a CEO-invite bootstrap flow — no native OIDC is supported by the upstream image today. BetterAuth's generic OAuth/OIDC plugin has to be registered **in application code**; it is not env-driven. Until upstream (or an nOS fork) adds env-configurable OIDC, the access-control layer is the **Authentik forward_auth outpost** enforced at the Nginx vhost (`templates/nginx/sites-available/paperclip.conf`):

- Nginx `authentik-proxy-auth.conf` gates access → Authentik group-based RBAC (tier 2, `nos-managers`) is applied via the `authentik_app_tiers` mapping.
- Paperclip still renders its own BetterAuth login after the proxy-auth gate. Local account lifecycle (CEO bootstrap, invites) stays owned by the Paperclip CLI.
- Data is sensitive (agent org-chart, task history) — the layered defense is intentional; even if the local login were bypassed, the outpost would reject the request first.

**Forward path (staged, off by default):** the compose template already carries the expected env vars (`BETTER_AUTH_OIDC_*`) behind the `paperclip_native_oidc_enabled` flag. When upstream Paperclip adds env-driven OIDC support (or when the nOS fork wires BetterAuth's `genericOAuth` provider from env), flip:

```yaml
paperclip_native_oidc_enabled: true
authentik_oidc_paperclip_client_id: "{{ (authentik_oidc_apps | selectattr('slug','equalto','paperclip') | first).client_id }}"
authentik_oidc_paperclip_client_secret: "{{ (authentik_oidc_apps | selectattr('slug','equalto','paperclip') | first).client_secret }}"
```

and promote the Paperclip entry in `authentik_oidc_apps` from `type: proxy` to a native OIDC provider:

```yaml
- name: "Paperclip"
  slug: "paperclip"
  enabled: "{{ install_paperclip | default(false) }}"
  client_id: "nos-paperclip"
  client_secret: "{{ global_password_prefix }}_pw_oidc_paperclip"
  redirect_uris: "https://{{ paperclip_domain | default('paperclip.dev.local') }}/api/auth/oauth/oidc/callback"
  launch_url: "https://{{ paperclip_domain | default('paperclip.dev.local') }}"
```

`tasks/post.yml` has a staged verification block (env-var injection check + `.well-known/openid-configuration` reachability probe) gated on the same flag.

The `extra_hosts: auth.dev.local:host-gateway` entry is rendered whenever `install_authentik` is true so Paperclip can reach the Authentik issuer regardless of whether OIDC is already wired.

## Rollback

Revert the commit and:

1. Restore the paperclip service block in `templates/stacks/devops/docker-compose.yml.j2`
2. Restore the inline `allowed-hostname` register tasks in `tasks/stacks/stack-up.yml`
3. Restore the include_role wiring in `tasks/stacks/stack-up.yml`
