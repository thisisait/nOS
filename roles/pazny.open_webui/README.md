# pazny.open_webui

Ansible role for deploying **Open WebUI** (chat frontend for Ollama) as a compose override fragment in the devBoxNOS `iiab` stack.

Part of [devBoxNOS](../../README.md) Wave 2.2 role extraction. Member of the `iiab-agents` group (**`pazny.open_webui`**, `pazny.uptime_kuma`, `pazny.vaultwarden`, `pazny.rustfs`).

Note: the role name uses an underscore (`open_webui`) to match Ansible role-name conventions; the compose service name uses a hyphen (`open-webui`) to match the upstream container naming.

## What it does

Two invocation modes (wired in Phase B):

1. **Main (`tasks/main.yml`)** — runs *before* `docker compose up iiab`:
   - Creates `{{ openwebui_data_dir }}` and `~/agents/log` on the host
   - Renders `templates/compose.yml.j2` into `{{ stacks_dir }}/iiab/overrides/open-webui.yml`
   - Links the `openwebui.conf` nginx vhost
   - Notifies `Restart openwebui` / `Restart nginx`

2. **Post (`tasks/post.yml`)** — runs *after* `docker compose up iiab --wait`:
   - Waits for `/api/config` to return 200 (12 × 10s retry)
   - Attempts to sign in with current credentials
   - If no user exists, registers the first admin user via `/api/v1/auths/signup`
   - On every run, reconverges the admin password via in-container `python3 + passlib bcrypt + sqlite3 UPDATE` (state-declarative, idempotent)

## Requirements

- Docker Desktop for Mac (ARM64)
- Ollama daemon running on the host at `11434` (via `host.docker.internal`)
- `stacks_shared_network` defined at the play level
- A top-level `Restart openwebui` handler in the consuming playbook (role-local fallback also provided)
- `Restart nginx` handler (shared play-level)
- (Optional) `install_authentik` + `authentik_oidc_openwebui_client_id`/`_secret` for SSO

## Variables

| Variable | Default | Description |
|---|---|---|
| `openwebui_version` | `0.6.35` | Pinned for CVE-2025-64495/64496 (XSS→RCE, JWT theft) |
| `openwebui_port` | `3004` | Host port (container listens on 8080) |
| `openwebui_domain` | `ai.dev.local` | Nginx vhost hostname |
| `openwebui_data_dir` | `~/openwebui` | Host bind mount for SQLite state |
| `openwebui_secret_key` | *(from credentials)* | Rotated via `global_password_prefix` |
| `openwebui_enable_signup` | `true` | Whether new user signup is allowed |
| `openwebui_admin_name` | `Admin` | Display name for first admin user |
| `openwebui_admin_email` | `{{ default_admin_email }}` | Email for first admin user |
| `openwebui_admin_password` | *(from credentials)* | Rotated via `global_password_prefix` |
| `openwebui_mem_limit` | `{{ docker_mem_limit_critical }}` | Defaults to `4g` |

## Usage

From `tasks/stacks/stack-up.yml`, gated on `install_openwebui`:

```yaml
# Before iiab compose up
- name: "[Stacks] Render pazny.open_webui compose override + nginx vhost"
  ansible.builtin.include_role:
    name: pazny.open_webui
    apply:
      tags: ['openwebui', 'ai']
  when: install_openwebui | default(false)
  tags: ['openwebui', 'ai']

# After iiab compose up
- name: "[Stacks] Open WebUI admin password reconverge (pazny.open_webui → post.yml)"
  ansible.builtin.include_role:
    name: pazny.open_webui
    tasks_from: post.yml
    apply:
      tags: ['openwebui', 'ai']
  when: install_openwebui | default(false)
  tags: ['openwebui', 'ai']
```

## Rollback

Revert the commit that introduced this role and:

1. Restore the `open-webui:` service block in `templates/stacks/iiab/docker-compose.yml.j2`
2. Restore `tasks/iiab/openwebui.yml` and `tasks/iiab/openwebui_post.yml` (if also reverted in Phase B)
3. Delete the leftover override file at `~/stacks/iiab/overrides/open-webui.yml`
