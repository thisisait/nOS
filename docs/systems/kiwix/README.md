# Kiwix

> Offline content server. Serves Wikipedia, Project Gutenberg and other ZIM
> archives with no internet connection. Filesystem-only — the ZIM files in `/data`
> *are* the database.

## Quick Reference

| | |
|---|---|
| **URL** | `https://kiwix{host_alias_seg}.{tenant_domain}` (default `https://kiwix.dev.local`) |
| **Port** | `8888` (`kiwix_port`; loopback publish `127.0.0.1:8888` → container `8080`. `services_lan_access: true` publishes on all interfaces instead) |
| **Stack** | `iiab` |
| **Node id** | `nos.iiab.kiwix` |
| **Toggle** | `install_kiwix: true` |
| **Image** | `ghcr.io/kiwix/kiwix-serve:3.8.2` (`kiwix_version`) |
| **Data** | `{{ nos_data_root }}/tenants/{{ nos_tenant_slug }}/shared/kiwix/data` → `/data` (default `~/nos/tenants/dev/shared/kiwix/data`; external-storage override → `{{ external_storage_root }}/kiwix`) — the `.zim` archives plus the generated `download-zim.sh` helper |
| **Compose** | `~/stacks/iiab/docker-compose.yml` + `~/stacks/iiab/overrides/kiwix.yml` (+ `kiwix-base.yml` from the plugin) |
| **Container** | `iiab-kiwix-1` |
| **Memory limit** | `512m` (`docker_mem_limit_light`) |
| **Networks** | `iiab_net` + the shared stacks network (`shared_net`) |

`kiwix_domain`, `kiwix_port`, `kiwix_version`, `kiwix_data_dir`, `kiwix_init_zim_url` and
`kiwix_zim_files` pin in `default.config.yml`; role defaults are fallbacks. `~/stacks/iiab/` still
holds the compose files — only the data row moved to `nos_data_root`.

## Authentication

- **Admin user:** N/A — kiwix-serve has no accounts and no app-level login at all.
- **SSO bucket:** `forward_auth` (plugin `kiwix-base`, `authentik.mode: forward_auth`, tier 4 = guest).
  Access is gated at the Traefik edge by the `authentik@file` middleware: a valid Authentik session
  is "you're in", and there is no per-user identity inside the service. The plugin's compose-extension
  sets `traefik.enable=false` so the FILE-provider router — which knows the *internal* port 8080 —
  is the single authority.
- The loopback publish on `127.0.0.1:8888` bypasses that gate; it is reachable only from the host.

## API Access

- **Base URL:** `https://kiwix{host_alias_seg}.{tenant_domain}` (through the Authentik gate) or
  `http://127.0.0.1:8888` on the host.
- **Auth method:** none at the app layer — see the forward-auth gate above.
- **Search endpoint:** `/search`

## Content Libraries

The role does **not** ship Wikipedia or Gutenberg. It downloads one small demo archive so a blank
run reaches a working UI, and leaves the rest to the operator:

| Source | What it is |
|--------|------------|
| `kiwix_init_zim_url` | Alpine Linux docs, saved as `alpinelinux.zim` (`kiwix_init_zim_dest`, ~10 MB) — downloaded only when `/data` holds no `*.zim` at all. Proof-of-life, not a knowledge base. Set to `""` to opt out. |
| `kiwix_zim_files` | Operator list of `{url, dest}` pairs, downloaded on every run. Empty by default. |
| `{{ kiwix_data_dir }}/download-zim.sh` | Helper script the role writes into the data dir: `./download-zim.sh <url>`. Its comments carry the recommended Wikipedia EN/CS and Gutenberg CS URLs. |

The compose `entrypoint` overrides the image CMD so `/bin/sh` can expand `/data/*.zim` (Compose does
not glob inside `command:`). With no ZIM present the container logs
`No ZIM files in /data -- add .zim files and restart` and sleeps instead of crash-looping.

## Health Check

- **Container healthcheck:** none declared — the role relies on `restart: unless-stopped`.
- **Plugin wait_health:** `http://127.0.0.1:8888/`, accepting any 2xx/3xx/4xx, because the
  forward-auth gate answers `401`/`302` and that is healthy.

## Dependencies

- None. Standalone; reads ZIM files from the bind-mounted `/data`. No database, no cache, no auth backend.
- Authentik + Traefik provide the access gate, but Kiwix itself never talks to them.
