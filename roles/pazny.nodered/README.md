# pazny.nodered

Ansible role for deploying **Node-RED** (low-code flow automation) as a compose override fragment in the devBoxNOS `iiab` stack.

## What it does

Called from `tasks/stacks/stack-up.yml` **before** `docker compose -p iiab up`:

1. Ensures `{{ nodered_data_dir }}` exists (host bind mount for `/data`).
2. Renders `templates/settings.js.j2` into `{{ nodered_data_dir }}/settings.js` — built-in `adminAuth` is disabled; access is gated by Authentik forward_auth at the nginx layer.
3. Renders `templates/compose.yml.j2` into `{{ stacks_dir }}/iiab/overrides/nodered.yml`.
4. Enables the nginx vhost symlink (`sites-enabled/nodered.conf`).

## Requirements

- Docker Desktop for Mac (ARM64). Multi-arch image `nodered/node-red:4.0.9` runs natively on M1.
- `stacks_shared_network` defined at the play level; `iiab_net` defined in base `templates/stacks/iiab/docker-compose.yml.j2`.
- The nodered nginx vhost template needs to already be rendered by the top-level `nginx` task.
- Authentik (for proxy-auth SSO) — optional but recommended.

## Variables

| Variable | Default | Description |
|---|---|---|
| `nodered_version` | `4.0.9` | Image tag (pinned stable) |
| `nodered_port` | `1880` | Exposed on `127.0.0.1` only (unless `services_lan_access`) |
| `nodered_domain` | `nodered.{{ instance_tld }}` | Public URL |
| `nodered_data_dir` | `~/nodered/data` | Host bind mount for `/data` |
| `nodered_timezone` | `Europe/Prague` | `TZ` env var |
| `nodered_uid` / `nodered_gid` | `1000` | Container user — matches upstream image default |
| `nodered_flows_file` | `flows.json` | Name of the flows file inside `/data` |
| `nodered_enable_safe_mode` | `"false"` | `NODE_RED_ENABLE_SAFE_MODE` |
| `nodered_enable_projects` | `"true"` | Enable git-backed Projects in editor |
| `nodered_mem_limit` | `1g` | Docker memory limit |
| `nodered_cpus` | `1.0` | Docker CPU quota |

## SSO

Proxy auth (tier **2 — manager**). Node-RED's function nodes grant shell-equivalent power, so the app must stay behind Authentik's forward_auth gate. The built-in `adminAuth` block in `settings.js` is intentionally omitted.

## Notes

Node-RED image runs as UID 1000. On Docker Desktop for Mac, osxfs/virtiofs maps host permissions transparently; the data dir is created with `0755` and should be writable by the container user. On Linux hosts this would require `chown 1000:1000`.
