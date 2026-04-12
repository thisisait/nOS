# pazny.uptime_kuma

Ansible role for deploying **Uptime Kuma** (self-hosted monitoring / status page) as a compose override fragment in the devBoxNOS `iiab` stack.

Part of [devBoxNOS](../../README.md) Wave 2.2 role extraction. Member of the `iiab-agents` group (`pazny.open_webui`, **`pazny.uptime_kuma`**, `pazny.vaultwarden`, `pazny.rustfs`).

## What it does

Two invocation modes (wired in Phase B):

1. **Main (`tasks/main.yml`)** — runs *before* `docker compose up iiab`:
   - Creates `{{ uptime_kuma_data_dir }}` and `~/agents/log` on the host
   - Renders `templates/compose.yml.j2` into `{{ stacks_dir }}/iiab/overrides/uptime-kuma.yml`
   - Notifies `Restart uptime_kuma`

2. **Monitors (`tasks/monitors.yml`)** — runs *after* `docker compose up iiab --wait`:
   - Installs `uptime-kuma-api` via pip (idempotent, failure non-fatal)
   - Waits for the web UI to serve HTTP (12 × 10s retry)
   - Builds an HTTP/TCP monitor list dynamically from `install_*` flags
   - Copies helper scripts (`setup-monitors.py`, `reset-password.py`) from `{{ role_path }}/files/` into `{{ uptime_kuma_data_dir }}`
   - Reconverges the admin password (state-declarative, tries new → falls back to previous prefix)
   - Runs `setup-monitors.py` to create/update monitors

The helper scripts live in `roles/pazny.uptime_kuma/files/` so the role is self-contained and can be extracted into a separate Galaxy repo in Wave 3.

## Requirements

- Docker Desktop for Mac (ARM64)
- Python 3 + pip on the host (for `uptime-kuma-api`)
- `stacks_shared_network` NOT required — Uptime Kuma only joins the local `iiab_net`
- A top-level `Restart uptime_kuma` handler in the consuming playbook (role-local fallback also provided)

## Variables

| Variable | Default | Description |
|---|---|---|
| `uptime_kuma_version` | `1` | `1` = latest v1.x; set a specific tag (`1.23.13`) for pinning |
| `uptime_kuma_port` | `3001` | Exposed on `127.0.0.1` only |
| `uptime_kuma_domain` | `uptime.dev.local` | Nginx vhost hostname |
| `uptime_kuma_data_dir` | `~/uptime-kuma` | Host bind mount (also holds helper scripts) |
| `uptime_kuma_admin_user` | `admin` | Monitoring admin username |
| `uptime_kuma_admin_password` | *(from credentials)* | Rotated via `global_password_prefix` |
| `uptime_kuma_auto_monitors` | `true` | Auto-create monitors for all `install_*` services |
| `uptime_kuma_mem_limit` | `{{ docker_mem_limit_light }}` | Defaults to `512m` |

## Usage

From `tasks/stacks/stack-up.yml`, gated on `install_uptime_kuma`:

```yaml
# Before iiab compose up
- name: "[Stacks] Render pazny.uptime_kuma compose override"
  ansible.builtin.include_role:
    name: pazny.uptime_kuma
    apply:
      tags: ['uptime-kuma', 'monitoring']
  when: install_uptime_kuma | default(false)
  tags: ['uptime-kuma', 'monitoring']

# After iiab compose up
- name: "[Stacks] Uptime Kuma monitors + password reconverge (pazny.uptime_kuma → monitors.yml)"
  ansible.builtin.include_role:
    name: pazny.uptime_kuma
    tasks_from: monitors.yml
    apply:
      tags: ['uptime-kuma', 'monitoring']
  when: install_uptime_kuma | default(false)
  tags: ['uptime-kuma', 'monitoring']
```

## Rollback

Revert the commit that introduced this role and:

1. Restore the `uptime-kuma:` service block in `templates/stacks/iiab/docker-compose.yml.j2`
2. Restore `tasks/iiab/uptime-kuma.yml` + `tasks/iiab/uptime-kuma-monitors.yml` (if also reverted in Phase B)
3. Helper scripts at `files/uptime-kuma/*.py` remain in place (they are still referenced by the legacy task)
4. Delete the leftover override file at `~/stacks/iiab/overrides/uptime-kuma.yml`
