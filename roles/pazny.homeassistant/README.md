# pazny.homeassistant

Ansible role for deploying **Home Assistant** (home automation platform) as a compose override fragment in the nOS `iiab` stack.

Part of [nOS](../../README.md) Wave 2.2 role extraction (iiab-content unit).

## What it does

Two invocation modes from `tasks/stacks/stack-up.yml`:

1. **Main (`tasks/main.yml`)** — runs *before* `docker compose -p iiab up`:
   - Creates the config directory on the host
   - Seeds `configuration.yaml` with `default_config:` on first run
   - Injects an Ansible-managed `http: trusted_proxies` block for nginx reverse-proxy compatibility
   - **OIDC** (when `install_authentik`): downloads the [`auth_oidc`](https://github.com/christiaangoossens/hass-oidc-auth) HACS community plugin into `custom_components/auth_oidc/`, renders `secrets.yaml` with the OIDC client_id/secret, and injects an Ansible-managed `auth_oidc:` block into `configuration.yaml` pointing at Authentik's discovery URL
   - Renders `templates/compose.yml.j2` into `{{ stacks_dir }}/iiab/overrides/homeassistant.yml` (adds `extra_hosts` for `auth.dev.local` so the container can reach Authentik)
   - Notifies `Restart homeassistant` when any of the above change

2. **Post (`tasks/post.yml`)** — runs *after* `docker compose -p iiab up`:
   - Waits for the web UI to respond (20 × 10s retry)
   - On first run, drives `/api/onboarding/users → core_config → analytics → integration`
   - On subsequent runs, reconverges the admin password via `hass --script auth change_password` in-container
   - Degrades gracefully if the API is unreachable (`failed_when: false` throughout)

## SSO (native OIDC via `auth_oidc` plugin)

Home Assistant core only supports OAuth2 — no native OIDC discovery. This role installs the community [`christiaangoossens/hass-oidc-auth`](https://github.com/christiaangoossens/hass-oidc-auth) HACS plugin, which adds a true OIDC auth provider with discovery-URL support against Authentik.

**Install flow (first run, when `install_authentik: true`):**

1. `get_url` fetches `hass-oidc-auth-v{{ homeassistant_auth_oidc_version }}.tar.gz` from GitHub releases
2. `unarchive` extracts into `{{ homeassistant_config_dir }}/hass-oidc-auth-<version>/`
3. A shell move step promotes `custom_components/auth_oidc/` to its final location and cleans up the tarball + extracted tree
4. `secrets.yaml` is rendered with `oidc_client_id` / `oidc_client_secret` pulled from the `authentik_oidc_apps` registry (see `default.config.yml`)
5. `configuration.yaml` gets an `# BEGIN ANSIBLE MANAGED - auth_oidc … # END` block wiring the plugin to `https://{{ authentik_domain }}/application/o/homeassistant/.well-known/openid-configuration`

**Login UX:** HA's login screen shows an additional "Sign in with Authentik" provider below the local username/password form. Users are auto-created on first OIDC login (`automatic_person_creation: true`).

**Callback URL** (declared in the OIDC registry, not in this role):
```
https://{{ homeassistant_domain }}/auth/oidc/callback
```

**Nginx forward-auth has been removed** — HA handles auth end-to-end. The vhost at `templates/nginx/sites-available/homeassistant.conf` is a plain reverse proxy.

**Fallback / manual install:** if the GitHub download fails (offline, rate-limited, or the tag moves), `install_authentik` tasks degrade with `failed_when: false`. To install manually, grab the release from <https://github.com/christiaangoossens/hass-oidc-auth/releases>, extract, and drop `custom_components/auth_oidc/` into `{{ homeassistant_config_dir }}/custom_components/`. Re-run the playbook — the stat check skips the download when `manifest.json` already exists.

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
| `homeassistant_auth_oidc_version` | `0.9.0` | `christiaangoossens/hass-oidc-auth` release tag (plugin downloaded on first run when `install_authentik`) |

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
