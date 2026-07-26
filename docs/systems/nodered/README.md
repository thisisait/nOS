# Node-RED

> Flow-based low-code programming for IoT and integration. Filesystem-only storage
> (no database): `/data` holds `flows.json`, credentials, and installed nodes.

## Quick Reference

| | |
|---|---|
| **URL** | `https://nodered{host_alias_seg}.{tenant_domain}` (default `https://nodered.dev.local`) |
| **Port** | `1880` (`nodered_port`; loopback publish `127.0.0.1:1880` → container `1880`) |
| **Stack** | `iiab` |
| **Node id** | `nos.iiab.nodered` |
| **Toggle** | `install_nodered: true` |
| **Image** | `nodered/node-red:4.0.9` (`nodered_version`; multi-arch, runs natively on M1) |
| **Data** | `{{ nos_data_root }}/platform/services/nodered/data` → `/data` (default `~/nos/...`; external-storage override applies). Filesystem-only — `flows.json`, credentials, installed nodes |
| **Memory limit** | `1g` (`docker_mem_limit_standard`) |
| **Container user** | `1000:1000` (`nodered_uid`/`nodered_gid`) |
| **Networks** | `iiab_net` + the shared stacks network |
| **Timezone** | `Europe/Prague` (`nodered_timezone`) |

`nodered_domain`, `nodered_port`, `nodered_version` pin in `default.config.yml`; role
defaults are fallbacks. The domain derives from `tenant_domain` + `host_alias`, not a
hardcoded `dev.local`.

## Authentication

- **SSO:** `native_oidc` (β1.B, 2026-05-05) via `passport-openidconnect` in the editor's
  `adminAuth.strategy` block. Authentik OAuth2 provider `nos-nodered`, RBAC tier 2.
  - Redirect URI: `https://{nodered_domain}/auth/strategy/callback`
  - Scopes: `openid`, `profile`, `email`; username claim `preferred_username`
  - Enabled when `install_authentik` AND `nodered_native_oidc_enabled` are true. The
    `passport-openidconnect` npm package installs at first boot via `/data/package.json`.
- **Break-glass local admin:** a fallback user is kept in `adminAuth.users` so an
  Authentik outage never locks the operator out:
  - user `admin`, password `{global_password_prefix}_nodered_admin`
- **Autologin:** `native_oidc` supports partial autologin — `strategy.autoLogin` redirects,
  but the local form is not hard-hidden (dormant behind `sso_autologin=false`).

> The `nodered-base` plugin's prose still mentions "forward-auth" in places — that is
> stale narrative. The authoritative `authentik.mode` is `native_oidc`; pre-β1.B it was
> forward_auth at the nginx layer.

## Health Check

- **Endpoint:** `GET /` — the plugin health-wait accepts any `2xx/3xx/4xx`
  (`http://127.0.0.1:1880/`), because an SSO gate answers `401`/`302` and that is healthy.
- **Container healthcheck:** `wget --spider -q http://127.0.0.1:1880/` (start period 90s).

## Storage Toggles

- `NODE_RED_ENABLE_PROJECTS=true` — git-backed projects
- `NODE_RED_ENABLE_SAFE_MODE=false`
- `FLOWS=flows.json`

## Dependencies

- Authentik (native-OIDC SSO — optional; falls back to open editor if disabled)
- No database (filesystem-only `/data`)
