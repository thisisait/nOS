# pazny.ntfy

Ansible role for deploying **ntfy** (self-hosted push notifications server, `ntfy.sh` upstream) as a compose override fragment in the devBoxNOS `iiab` stack.

## What it does

- Creates `{{ ntfy_data_dir }}` (+ `attachments/` subdir) on the host.
- Renders `templates/server.yml.j2` into `{{ ntfy_data_dir }}/server.yml` (mounted `:ro` at `/etc/ntfy/server.yml`).
- Renders `templates/compose.yml.j2` into `{{ stacks_dir }}/iiab/overrides/ntfy.yml`.
- Exposes ntfy on `127.0.0.1:{{ ntfy_port }}` (default `2586`), fronted by nginx vhost `ntfy.dev.local` with Authentik forward-auth.

## Requirements

- Docker Desktop for Mac (ARM64).
- SQLite cache lives inside the data dir (`cache.db`) — no external DB required.
- Nginx vhost must keep `proxy_buffering off` for Server-Sent Events (SSE push).

## Variables

| Variable | Default | Description |
|---|---|---|
| `ntfy_version` | `v2.21.0` | Pinned upstream tag. |
| `ntfy_port` | `2586` | Host port (bound to `127.0.0.1`). |
| `ntfy_domain` | `ntfy.{{ instance_tld }}` | Nginx vhost hostname. |
| `ntfy_data_dir` | `~/ntfy/data` | Host bind mount (`cache.db`, `attachments/`, `server.yml`). |
| `ntfy_cache_duration` | `12h` | Message retention window. |
| `ntfy_attachment_total_size_limit` | `5G` | Global attachment cache cap. |
| `ntfy_attachment_file_size_limit` | `15M` | Per-file upload cap. |
| `ntfy_auth_default_access` | `deny-all` | Blocks anonymous; Authentik proxy gates access. |
| `ntfy_mem_limit` | `512m` | `docker_mem_limit_light`. |

## SSO

Proxy auth — ntfy's web UI sits behind Authentik forward-auth (see `authentik_oidc_apps` entry with `type: "proxy"`). Tier 2 (manager). ntfy's built-in ACL (`auth-default-access: deny-all`) blocks anonymous API clients by default; create tokens via ntfy CLI for publisher/subscriber agents.

## Rollback

Revert the commit and delete `~/stacks/iiab/overrides/ntfy.yml`, `~/ntfy/`, and the nginx vhost.
