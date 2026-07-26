# Jellyfin

> Media server. Manages and streams movies, TV shows, music and photos. Media
> directories are mounted **read-only**; Jellyfin's own state lives in `/config`
> (SQLite), with a separate throwaway `/cache`.

## Quick Reference

| | |
|---|---|
| **URL** | `https://media{host_alias_seg}.{tenant_domain}` (default `https://media.dev.local`) |
| **Port** | `8096` (`jellyfin_port`). `jellyfin_lan_access: true` is the default, so the port publishes on **all interfaces** (`0.0.0.0:8096`), not loopback — deliberate, for TVs and mobile clients |
| **Stack** | `iiab` |
| **Node id** | `nos.iiab.jellyfin` |
| **Toggle** | `install_jellyfin: false` (**default OFF**) |
| **Image** | `jellyfin/jellyfin:10.11.10` (`jellyfin_version`; REM-119 / CVE-2026-48793 pin) |
| **Config** | `{{ nos_data_root }}/tenants/{{ nos_tenant_slug }}/shared/jellyfin/config` → `/config` (default `~/nos/tenants/dev/shared/jellyfin/config`) — SQLite DB, server plugins, `plugins/configurations/SSO-Auth.xml` |
| **Cache** | `{{ nos_data_root }}/platform/services/jellyfin/cache` → `/cache` (default `~/nos/platform/services/jellyfin/cache`) — regenerable transcode/artwork cache, not user data |
| **Media** | `~/media/movies`, `~/media/shows`, `~/media/music` → `/media/*` **read-only** (`jellyfin_movies_dir` / `jellyfin_shows_dir` / `jellyfin_music_dir`) |
| **Compose** | `~/stacks/iiab/docker-compose.yml` + `~/stacks/iiab/overrides/jellyfin.yml` (+ `jellyfin-base.yml` from the plugin) |
| **Container** | `iiab-jellyfin-1` |
| **Memory limit** | `2g` (`docker_mem_limit_critical`) |
| **Networks** | `iiab_net` + the shared stacks network (`shared_net`) |

`jellyfin_domain`, `jellyfin_port`, `jellyfin_version` and every media path pin in
`default.config.yml`; role defaults are fallbacks. External storage moves all data rows to
`{{ external_storage_root }}/jellyfin/{config,cache}` and `{{ external_storage_root }}/media/*`.
`~/stacks/iiab/` still holds the compose files — only the persistent data rows moved to
`nos_data_root`.

## Authentication

- **Admin user:** `admin` (`jellyfin_admin_user`) — created by `roles/pazny.jellyfin/tasks/post.yml` through the one-shot
  `/Startup/User` endpoint on a fresh install. Later runs reconverge the password via
  `AuthenticateUserByName` → `POST /Users/{id}/Password`.
- **Admin password:** `{global_password_prefix}_pw_jellyfin`
- **SSO:** `native_oidc` (plugin `jellyfin-base`, tier 4 = guest). Not env-driven — SSO is wired by
  the **jellyfin-plugin-sso server plugin** (`jellyfin_sso_plugin_version: 4.0.0.4`), installed by the
  role into `/config/plugins` with its config rendered to `plugins/configurations/SSO-Auth.xml`.
  - Authentik client `nos-jellyfin`, slug `jellyfin`
  - Redirect URI: `https://{jellyfin_domain}/sso/OID/redirect/Authentik`
  - Scopes: `openid`, `profile`, `email`
  - Admin roles: `nos-admins`, `nos-providers`; user roles add `nos-managers`, `nos-users`, `nos-guests`

> The `jellyfin-base` compose-extension header still reads "Q2 forward_auth pivot" — stale narrative.
> The authoritative `authentik.mode` is `native_oidc` (D1.0 correction, 2026-05-05); that
> compose-extension only sets the `_NOS_PLUGIN` marker env.

> The pinned SSO plugin 4.0.0.4 targets ABI 10.11 and is end-of-line — the 9p4 repo is archived
> read-only, so a future Jellyfin 10.12 will need a successor plugin.

## API Access

- **Base URL:** `https://media{host_alias_seg}.{tenant_domain}`
- **Auth method:** API key in the `X-Emby-Token` header (or a user token from
  `POST /Users/AuthenticateByName`).
- **Bot account:** none. The playbook provisions **no** service account and **no** API key —
  `openclaw-bot` and `~/agents/tokens/jellyfin.token` were `docs/systems/TEMPLATE/` boilerplate that
  nothing in the repo ever creates. Mint a key manually under Dashboard → API Keys if an agent needs one.

## Health Check

- **Endpoint:** `GET /health`
- **Expected:** `200 OK` with the body `Healthy`
- Used by both the container healthcheck (`curl -sf http://localhost:8096/health`, 15s interval) and
  the plugin's `post_compose` wait.

## Dependencies

- No database service — Jellyfin keeps its own SQLite files under `/config`.
- Authentik (native OIDC via the SSO-Auth server plugin; optional).
- The media directories must exist on the host; they are mounted read-only.
