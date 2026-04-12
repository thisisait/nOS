# pazny.homeassistant

Ansible role for deploying **Home Assistant** (home automation platform) as a compose override fragment in the devBoxNOS `iiab` stack.

Part of [devBoxNOS](../../README.md) Wave 2.2 role extraction (iiab-content unit).

## What it does

Two invocation modes from `tasks/stacks/stack-up.yml`:

1. **Main (`tasks/main.yml`)** — runs *before* `docker compose -p iiab up`:
   - Creates the config directory on the host
   - Seeds `configuration.yaml` with `default_config:` on first run
   - Injects an Ansible-managed `http: trusted_proxies` block for nginx reverse-proxy compatibility
   - Renders `templates/compose.yml.j2` into `{{ stacks_dir }}/iiab/overrides/homeassistant.yml`
   - Notifies `Restart homeassistant` when either changes

2. **Post (`tasks/post.yml`)** — runs *after* `docker compose -p iiab up`:
   - Waits for the web UI to respond (20 × 10s retry)
   - On first run, drives `/api/onboarding/users → core_config → analytics → integration`
   - On subsequent runs, reconverges the admin password via `hass --script auth change_password` in-container
   - Degrades gracefully if the API is unreachable (`failed_when: false` throughout)

## Requirements

- Docker Desktop for Mac (ARM64)
- `iiab_net` + `{{ stacks_shared_network }}` Docker networks (declared in base iiab compose)
- `global_password_prefix` set at play level (admin password falls back to `{{ global_password_prefix }}_pw_homeassistant`)

## Variables

| Variable | Default | Description |
|---|---|---|
| `homeassistant_version` | `2026.4` | Pinned for CVE-2026-34205 (CVSS 9.7 Supervisor bypass) |
| `homeassistant_port` | `8123` | Host port (bound to `127.0.0.1` unless privileged) |
| `homeassistant_domain` | `home.dev.local` | Used by the nginx vhost |
| `homeassistant_timezone` | `Europe/Prague` | `TZ` env var |
| `homeassistant_config_dir` | `~/homeassistant` | Host bind mount |
| `homeassistant_privileged` | `false` | `true` → `privileged + network_mode: host` for mDNS/Bonjour |
| `homeassistant_admin_name` | `Admin` | Onboarding display name |
| `homeassistant_admin_user` | `admin` | Onboarding username |
| `homeassistant_admin_password` | *(from prefix)* | Falls back to `{{ global_password_prefix }}_pw_homeassistant` |
| `homeassistant_mem_limit` | `docker_mem_limit_standard` | Defaults to `1g` |
| `homeassistant_cpus` | `docker_cpus_standard` | Defaults to `1.0` |

## Usage

From `tasks/stacks/stack-up.yml`:

```yaml
- name: "[Stack] Home Assistant render + dirs (pazny.homeassistant role)"
  ansible.builtin.include_role:
    name: pazny.homeassistant
  when: install_homeassistant | default(false)

# ... stack-up.yml runs docker compose up iiab ...

- name: "[Stack] Home Assistant post-start onboarding + password reconverge"
  ansible.builtin.include_role:
    name: pazny.homeassistant
    tasks_from: post.yml
  when: install_homeassistant | default(false)
```

## Rollback

Revert the commit that introduced this role and:

1. Restore the `homeassistant` service block in `templates/stacks/iiab/docker-compose.yml.j2`
2. Restore `tasks/iiab/homeassistant.yml` and `tasks/iiab/homeassistant_post.yml`
3. Restore the `import_tasks` calls in `main.yml`

The override file at `~/stacks/iiab/overrides/homeassistant.yml` becomes dead — delete it manually.
