# pazny.boxapi

Ansible role for deploying **BoxAPI** — a FastAPI + uvicorn Box Management API that exposes REST endpoints (`health`, `services`, `status`, `run-tag`) for managing devBoxNOS. Part of [devBoxNOS](../../README.md).

BoxAPI runs as a user-level launchd agent (`com.devboxnos.api`), listens on a loopback port, and is fronted by nginx at `api.dev.local`.

## What it does

1. Creates `~/boxapi/` and copies `main.py` + `requirements.txt` from `files/boxapi/`
2. Creates a Python venv at `~/boxapi/venv/` if missing
3. Installs Python dependencies into the venv via pip
4. Renders the launchd plist `com.devboxnos.api.plist` into `~/Library/LaunchAgents/` from `templates/boxapi-launchd.plist.j2`
5. Loads the launchd service via `launchctl load -w` (idempotent — already loaded is OK)

Changes to the plist template trigger a `Restart boxapi` handler that kicks the agent with `launchctl kickstart -k`.

## Requirements

- macOS with system Python 3 (shipped with Command Line Tools)
- The `files/boxapi/` directory and `templates/boxapi-launchd.plist.j2` staying inside the playbook repo
- Play-level handler `Restart boxapi` defined in the consuming playbook (a role-local copy is also provided)

## Variables

| Variable | Default | Description |
|---|---|---|
| `boxapi_port` | `8099` | Loopback port bound by uvicorn |
| `boxapi_domain` | `api.{{ instance_tld }}` | Public hostname behind nginx vhost |
| `boxapi_secret` | *(from credentials)* | Shared secret for privileged API calls, prefix-rotated |

Secrets (`boxapi_secret`) stay in the top-level `default.credentials.yml` so that `global_password_prefix` rotation propagates consistently across all devBoxNOS services.

## Usage

In the consuming playbook:

```yaml
- import_role:
    name: pazny.boxapi
  when: install_boxapi | default(false)
  tags: ['boxapi', 'api']
```

## Rollback

Revert the commit that introduced this role and restore `tasks/boxapi.yml` + the `import_tasks` call site in `main.yml`. To also stop and remove the launchd agent manually:

```bash
launchctl bootout gui/$(id -u)/com.devboxnos.api 2>/dev/null || true
rm -f ~/Library/LaunchAgents/com.devboxnos.api.plist
rm -rf ~/boxapi
```
