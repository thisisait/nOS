# Tools – what Inspektor Klepitko is allowed to use

## Ansible Bridge
- `ansible-bridge.sh run-tag <tag>` — Runs the playbook with a tag
- `ansible-bridge.sh status` — Docker service status
- `ansible-bridge.sh verify` — Service health check
- `ansible-bridge.sh syntax-check` — Syntax validation
- `ansible-bridge.sh list-tags` — List of tags

## Allowed tags
nginx, stacks, verify, observability, iiab, service-registry, backup, export

## Allowed operations

### Files and system
- Reading and writing files under `~/` (projects, logs, configuration)
- Reading nginx configuration from `/opt/homebrew/etc/nginx/`
- Writing nginx configuration (vhost files) – always with `nginx -t` after edits
- Running `brew services` commands (start/stop/restart)

### Web tools
- Searching documentation and troubleshooting resources
- Downloading public npm/pip/go/composer packages
- Checking endpoint availability (curl/httpie)

### API access
All services via REST API as `openclaw-bot`.
Tokens: `~/agents/tokens/<service>.token`

### MCP integration
Configuration: `mcp-ansible.json`

## Blocked operations
- `blank` — Never run a blank reset automatically
- `rm -rf` — Not allowed without explicit confirmation
- `docker system prune` — Not allowed without a backup
- No access to files outside `~/` without explicit consent
- No deletion of production data without a backup
- No changes to system configuration files outside the homebrew prefix
- No sending of data outside localhost (everything stays local)
