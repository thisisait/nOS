# Home Assistant

> Home automation. Devices, scenes, automations, dashboards. Everything HA owns —
> `configuration.yaml`, `secrets.yaml`, the `auth_oidc` custom component, and its own
> SQLite recorder database — lives in the single bind-mounted `/config` tree.

## Quick Reference

| | |
|---|---|
| **URL** | `https://home{host_alias_seg}.{tenant_domain}` (default `https://home.dev.local`) |
| **Port** | `8123` (`homeassistant_port`; loopback publish `127.0.0.1:8123` → container `8123`). `homeassistant_privileged: true` swaps this for `privileged: true` + `network_mode: host` (mDNS/Bonjour discovery) and drops the port mapping entirely |
| **Stack** | `iiab` |
| **Node id** | `nos.iiab.homeassistant` (the doc tree is aliased to `docs/systems/home-assistant/` via `DOCS_DIR_ALIASES`) |
| **Toggle** | `install_homeassistant: false` (**default OFF**) |
| **Image** | `homeassistant/home-assistant:2026.6.0` (`homeassistant_version`; CVE-2026-34205 Supervisor-bypass pin) |
| **Data** | `{{ nos_data_root }}/platform/services/homeassistant/config` → `/config` (default `~/nos/platform/services/homeassistant/config`; external-storage override → `{{ external_storage_root }}/homeassistant`). This one mount is both config and data — there is no second volume |
| **Compose** | `~/stacks/iiab/docker-compose.yml` + `~/stacks/iiab/overrides/homeassistant.yml` (+ `homeassistant-base.yml` from the plugin) |
| **Container** | `iiab-homeassistant-1` |
| **Memory limit** | `1g` (`docker_mem_limit_standard`) |
| **Networks** | `iiab_net` + the shared stacks network (`shared_net`) — bridge mode only; `network_mode: host` replaces them |
| **tmpfs** | `/tmp` |

`homeassistant_domain`, `homeassistant_port`, `homeassistant_version`, `homeassistant_config_dir`
and the admin credentials pin in `default.config.yml`; role defaults are fallbacks. `~/stacks/iiab/`
still holds the compose files — only the data row moved to `nos_data_root`.

> On macOS, `network_mode: host` reaches the Docker VM's network, **not** the physical Mac network —
> so it does not actually buy LAN device discovery there.

## Authentication

- **Admin user:** `admin` (`homeassistant_admin_user`) — the owner account is created by
  `tasks/post.yml` via the one-shot `POST /api/onboarding/users` flow. Once onboarding closes, later
  runs reconverge the password with `hass --script auth change_password` inside the container.
- **Admin password:** `{global_password_prefix}_pw_homeassistant`
- **SSO:** `native_oidc` (plugin `homeassistant-base`, tier 3 = user). HA core speaks OAuth2, not OIDC
  discovery, so the role installs the **`auth_oidc` HACS component**
  (christiaangoossens/hass-oidc-auth, `homeassistant_auth_oidc_version: 1.1.1`) into
  `{{ homeassistant_config_dir }}/custom_components/auth_oidc` and renders the client credentials into
  `secrets.yaml` — config-file driven, not env.
  - Authentik client `nos-homeassistant`, slug `homeassistant`
  - Redirect URI: `https://{homeassistant_domain}/auth/oidc/callback`
  - Scopes: `openid`, `profile`, `email`
  - **Autologin:** `features.default_redirect: true` in `configuration.yaml` skips HA's local login
    picker. Dormant behind the global `sso_autologin` (false). Break-glass: `?skip_oidc_redirect=true`.

> Pre-D1.0 both this doc and the plugin description called HA "Authentik proxy auth" — that was the
> "no OIDC env in compose ⇒ proxy" heuristic misfiring. The authoritative `authentik.mode` is
> `native_oidc`, and the slug is `homeassistant`, not `home-assistant`. The plugin's own
> `description:` field still carries the stale forward-auth wording.

## API Access

- **Base URL:** `https://home{host_alias_seg}.{tenant_domain}/api/`
- **Auth method:** Long-Lived Access Token, sent as `Authorization: Bearer <token>`.
- **Bot account:** none. The playbook provisions **no** service account and **no** token —
  `openclaw-bot` and `~/agents/tokens/home-assistant.token` were `docs/systems/TEMPLATE/` boilerplate
  that nothing in the repo ever creates. Generate a Long-Lived Access Token from the HA user profile
  page if an agent needs one.

## Health Check

- **Container healthcheck:** `curl -fsS -o /dev/null http://localhost:8123/` — 30s interval, 60s start
  period. `/` serves the onboarding/frontend and works in both bridge and `network_mode: host`.
- **Plugin wait_health:** `http://127.0.0.1:8123/`; `post.yml` additionally waits for `200`/`302`.
- `GET /api/` (which answers `{"message":"API running."}`) is **not** the health probe — it requires a
  bearer token and returns `401` without one.

## Dependencies

- No database service — HA's recorder uses SQLite inside `/config`.
- Authentik (native OIDC via the `auth_oidc` custom component; optional). The plugin's
  compose-extension adds `extra_hosts` for `host.docker.internal` and the Authentik domain, but only
  in bridge mode — a host-network container shares the host's `/etc/hosts` and the alias would conflict.
