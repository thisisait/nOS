# pazny.freepbx

Ansible role for deploying **FreePBX + Asterisk** as a compose override fragment in the devBoxNOS `voip` stack. Uses the `tiredofit/freepbx` image and shares MariaDB with the rest of the infra stack.

Part of [devBoxNOS](../../README.md) Wave 2.2 role extraction (voip-engineering-data worker).

## What it does

Single invocation from `tasks/stacks/stack-up.yml` (runs before `docker compose up voip`):

- Ensures `{{ freepbx_data_dir }}` subdirectories (`certs/`, `data/`, `logs/`, `custom/`) exist on the host
- Renders `templates/compose.yml.j2` into `{{ stacks_dir }}/voip/overrides/freepbx.yml`
- The override is picked up by stack-up's `find + -f` loop and merged into the voip compose project
- Notifies `Restart freepbx` if the override template changed

No post-start task — FreePBX/Asterisk self-initializes on first boot via the `tiredofit/freepbx` entrypoint.

## Requirements

- Docker Desktop for Mac (ARM64 — FreePBX image is multi-arch)
- MariaDB reachable at `mariadb:3306` on `{{ stacks_shared_network }}` (provided by `pazny.mariadb`)
- A top-level `Restart freepbx` handler in the consuming playbook (also provided role-local)

## Variables

| Variable | Default | Description |
|---|---|---|
| `freepbx_version` | `latest` | `tiredofit/freepbx` image tag |
| `freepbx_port` | `8088` | Web UI bound on `127.0.0.1` |
| `freepbx_sip_port` | `5060` | SIP signaling UDP+TCP |
| `freepbx_iax_port` | `4569` | IAX2 protocol port |
| `freepbx_rtp_start` | `10000` | RTP media port range start |
| `freepbx_rtp_end` | `10100` | RTP media port range end |
| `freepbx_data_dir` | `~/freepbx` | Host bind mount root |
| `freepbx_db_name` | `asterisk` | MariaDB database |
| `freepbx_db_user` | `asterisk` | MariaDB username |
| `freepbx_db_password` | *(from credentials)* | `{{ global_password_prefix }}_pw_freepbx` |
| `freepbx_timezone` | `Europe/Prague` | Container TZ |
| `freepbx_mem_limit` | `{{ docker_mem_limit_standard }}` | Defaults to `1g` |
| `freepbx_lan_access` | `false` | When true (or `services_lan_access`), SIP/IAX/RTP bind to `0.0.0.0` |

Secrets stay in the top-level `default.credentials.yml` so the blank-reset prefix rotation pattern continues to work.

## Usage

From `tasks/stacks/stack-up.yml`, gate the role invocation on `install_freepbx`:

```yaml
- name: "[Stacks] FreePBX render (pazny.freepbx role)"
  ansible.builtin.include_role:
    name: pazny.freepbx
  when: install_freepbx | default(false)
```

The override file is then merged automatically by the voip stack `docker compose up` loop.

## Rollback

Revert the commit that introduced this role and:

1. Restore the freepbx service block in `templates/stacks/voip/docker-compose.yml.j2`
2. Delete the override file at `~/stacks/voip/overrides/freepbx.yml`
