# pazny.vaultwarden

Ansible role for deploying **Vaultwarden** (Bitwarden-compatible personal password vault) as a compose override fragment in the devBoxNOS `iiab` stack.

Part of [devBoxNOS](../../README.md) Wave 2.2 role extraction. Member of the `iiab-agents` group (`pazny.open_webui`, `pazny.uptime_kuma`, **`pazny.vaultwarden`**, `pazny.rustfs`).

## What it does

Single invocation from `tasks/stacks/stack-up.yml` (wired in Phase B):

- Creates `{{ vaultwarden_data_dir }}` on the host
- Renders `templates/compose.yml.j2` into `{{ stacks_dir }}/iiab/overrides/vaultwarden.yml`
- Notifies `Restart vaultwarden` if the override template changed
- Prints admin token / URL banner for the operator

No post-start task. OIDC integration with Authentik is activated automatically via `{% if install_authentik %}` blocks when the flag is true.

## Requirements

- Docker Desktop for Mac (ARM64)
- `stacks_shared_network` defined at the play level
- A top-level `Restart vaultwarden` handler in the consuming playbook (role-local fallback also provided)
- (Optional) `install_authentik` + `authentik_oidc_apps` with a `vaultwarden` slug entry for SSO

## Variables

| Variable | Default | Description |
|---|---|---|
| `vaultwarden_version` | `1.35.4` | Pinned for CVE-2026-27802/27803, CVE-2025-24364 |
| `vaultwarden_port` | `8062` | Exposed on `127.0.0.1` (or LAN if `services_lan_access`) |
| `vaultwarden_domain` | `pass.dev.local` | Used for `DOMAIN` env var + nginx vhost |
| `vaultwarden_data_dir` | `~/vaultwarden` | Host bind mount for persistence |
| `vaultwarden_signups_allowed` | `false` | Admin provisions accounts |
| `vaultwarden_admin_token` | *(from credentials)* | Rotated via `global_password_prefix` |
| `vaultwarden_mem_limit` | `{{ docker_mem_limit_light }}` | Defaults to `512m` |

## Usage

From `tasks/stacks/stack-up.yml`, gated on `install_vaultwarden`:

```yaml
- name: "[Stacks] Render pazny.vaultwarden compose override"
  ansible.builtin.include_role:
    name: pazny.vaultwarden
    apply:
      tags: ['vaultwarden', 'iam']
  when: install_vaultwarden | default(false)
  tags: ['vaultwarden', 'iam']
```

## Rollback

Revert the commit that introduced this role and:

1. Restore the `vaultwarden:` service block in `templates/stacks/iiab/docker-compose.yml.j2`
2. Restore `tasks/iiab/vaultwarden.yml` (if also reverted in Phase B)
3. Delete the leftover override file at `~/stacks/iiab/overrides/vaultwarden.yml`
