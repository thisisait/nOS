# pazny.bone

Ansible role for deploying **Bone** — the local FastAPI + uvicorn service that is the *structure / state / dispatcher* organ of nOS. Part of [nOS](../../README.md).

> **Formerly BoxAPI.** See [`docs/anatomy.md`](../../docs/anatomy.md) for the organ metaphor.

Bone runs as a user-level launchd agent (`eu.thisisait.nos.api`), listens on a loopback port, and is fronted by nginx at `api.dev.local`. It is the only process in nOS allowed to shell out to `ansible-playbook`.

## What it does

1. Creates `~/boxapi/` and copies the Python modules from `files/bone/` (`main.py`, `state.py`, `migrations.py`, `upgrades.py`, `patches.py`, `coexistence.py`, `events.py`, `requirements.txt`)
2. Creates a Python venv at `~/boxapi/venv/` if missing
3. Installs Python dependencies into the venv via pip
4. Renders the launchd plist `eu.thisisait.nos.api.plist` into `~/Library/LaunchAgents/` from `templates/bone-launchd.plist.j2`
5. Loads the launchd service via `launchctl load -w` (idempotent — already loaded is OK)

> Install dir `~/boxapi/` and launchd label `eu.thisisait.nos.api` stay on their pre-rebrand names in L2. They migrate to `~/bone/` and `eu.thisisait.nos.bone` in the L4 runtime rebrand commit along with the corresponding playbook migration record.

Changes to the plist template trigger a `Restart bone` handler that kicks the agent with `launchctl kickstart -k`.

## Requirements

- macOS with system Python 3 (shipped with Command Line Tools)
- The `files/bone/` directory and `templates/bone-launchd.plist.j2` staying inside the playbook repo
- Play-level handler `Restart bone` defined in the consuming playbook (a role-local copy is also provided)

## Variables

| Variable | Default | Description |
|---|---|---|
| `bone_port` | `8099` | Loopback port bound by uvicorn |
| `bone_domain` | `api.{{ instance_tld }}` | Public hostname behind nginx vhost |
| `bone_secret` | *(from default.config.yml)* | Shared secret for privileged API calls, prefix-rotated |

The secret `bone_secret` stays in the top-level `default.config.yml` so that `global_password_prefix` rotation propagates consistently across all nOS services. Exposed to the running uvicorn process as `BONE_SECRET` through the launchd plist's `EnvironmentVariables` block.

## Usage

In the consuming playbook:

```yaml
- import_role:
    name: pazny.bone
  when: install_bone | default(false)
  tags: ['bone', 'api']
```

## Rollback

Revert the rebrand commits that introduced this role. To also stop and remove the launchd agent manually:

```bash
launchctl bootout gui/$(id -u)/eu.thisisait.nos.api 2>/dev/null || true
rm -f ~/Library/LaunchAgents/eu.thisisait.nos.api.plist
rm -rf ~/boxapi
```
