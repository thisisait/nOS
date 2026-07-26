# Calibre-Web

> Ebook server. Web front-end for browsing and reading a Calibre library. The
> library itself (`metadata.db` + book files) is a bind-mounted host directory —
> Calibre-Web keeps only its own `app.db` in `/config`.

## Quick Reference

| | |
|---|---|
| **URL** | `https://books{host_alias_seg}.{tenant_domain}` (default `https://books.dev.local`) |
| **Port** | `8083` (`calibreweb_port`; loopback publish `127.0.0.1:8083` → container `8083`) |
| **Stack** | `iiab` |
| **Node id** | `nos.iiab.calibre-web` |
| **Toggle** | `install_calibreweb: true` |
| **Image** | `lscr.io/linuxserver/calibre-web:0.6.26` (`calibreweb_version` — `default.config.yml` wins over the role default `0.6.26-ls384`), plus `DOCKER_MODS=linuxserver/mods:universal-calibre`, which installs the `calibredb` binaries on first boot |
| **Config** | `{{ nos_data_root }}/tenants/{{ nos_tenant_slug }}/shared/calibreweb/config` → `/config` (default `~/nos/tenants/dev/shared/calibreweb/config`) — holds `app.db` |
| **Data (library)** | `{{ nos_data_root }}/tenants/{{ nos_tenant_slug }}/shared/calibreweb/books` → `/books` (default `~/nos/tenants/dev/shared/calibreweb/books`) — the Calibre library: `metadata.db` + the book files. External-storage override → `{{ external_storage_root }}/calibre` |
| **Compose** | `~/stacks/iiab/docker-compose.yml` + `~/stacks/iiab/overrides/calibre-web.yml` (+ `calibre-web-base.yml` from the plugin) |
| **Container** | `iiab-calibre-web-1` (compose service `calibre-web`) |
| **Memory limit** | `512m` (`docker_mem_limit_light`) |
| **Networks** | `gated_net` **only** — Traefik-only, per SEC-02. Calibre-Web is kept off `iiab_net`/`shared_net` because its reverse-proxy header login trusts `X-authentik-username`, so no peer container may reach `:8083` |

`calibreweb_domain`, `calibreweb_port`, `calibreweb_version` pin in `default.config.yml`;
role defaults are fallbacks. The domain derives from `tenant_domain` + `host_alias`, not a
hardcoded `dev.local`. `~/stacks/iiab/` still holds the compose files — only the persistent
data rows moved to `nos_data_root`.

## Authentication

- **Admin user:** `admin` — the linuxserver image ships `admin` / `admin123`; `tasks/post.yml`
  resets the password on every run.
- **Admin password:** `{global_password_prefix}_pw_calibreweb`
- **SSO:** `forward_auth` (plugin `calibre-web-base`, `authentik.mode: forward_auth`, tier 3).
  Authentik gates access at the Traefik edge via the `authentik@file` middleware; Calibre-Web
  has no native OIDC (upstream request #2965 was rejected). The plugin's compose-extension sets
  `traefik.enable=false` so the FILE-provider router is the single authority.
- **Optional header login (dormant):** Calibre-Web's "Allow Reverse Proxy Authentication" can
  consume `X-authentik-username` (`calibreweb_proxy_auth_header`) and skip its own form. Gated by
  `calibreweb_proxy_auth_enabled`, which resolves to the global `sso_autologin` — **false** by
  default. When enabled, `post.yml` renames the seeded `admin` row to `calibreweb_proxy_auth_username`
  (default `akadmin`), because the header login matches an EXISTING account and never auto-creates one.

## API Access

- **Base URL:** N/A — Calibre-Web ships no REST API.
- **Auth method:** N/A
- **CLI access:** `docker compose -p iiab exec -T -u abc calibre-web calibredb <cmd> --library-path /books`
  (the container runs as `abc`/PUID; `--library-path` is required — the library lives at `/books`, not
  at `calibredb`'s default location).
- **OPDS feed:** `https://books{host_alias_seg}.{tenant_domain}/opds` — read-only catalog, behind the
  same Authentik forward-auth gate as the UI.

## Library autowiring

`tasks/post.yml` makes the library self-provisioning on a blank run:

1. `chown -R abc:abc /books` so the PUID user can write the bind mount.
2. `calibredb` creates an empty library when `/books/metadata.db` is absent.
3. `app.db`'s `config_calibre_dir` is set to `/books` — without it Calibre-Web dead-ends on `/admin/dbconfig`.
4. Into a still-empty library it seeds one bundled public-domain EPUB (Alice's Adventures in
   Wonderland, Project Gutenberg #11) — `calibreweb_seed_sample_book: true`, bundled in `files/`, so no
   provision-time network is needed. It is never re-added once the operator deletes it.

## Health Check

- **Container healthcheck:** `curl -fsS -o /dev/null http://localhost:8083/` — 30s interval, 90s
  start period (the `universal-calibre` mod downloads the calibre binaries on first boot).
- **Plugin wait_health:** `http://127.0.0.1:8083/`, accepting any 2xx/3xx/4xx — the root answers
  `302 → /login`, and behind the gate Authentik answers `401`/`302`. Both are healthy.

## Dependencies

- No database service — `app.db` (in `/config`) and `metadata.db` (in `/books`) are both SQLite files.
- Authentik (forward-auth gate; optional, but the default posture).
- Traefik — the only route in, since Calibre-Web sits on `gated_net` alone.
