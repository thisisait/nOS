# Offline Maps

> tileserver-gl serving offline vector + raster map tiles from MBTiles archives. Part of the iiab (offline-first content) stack; no hosted tile provider is ever called.

## Quick Reference

| | |
|---|---|
| **URL** | `https://maps.<tenant_domain>` (derived from `maps_domain`; default `maps.dev.local`) |
| **Host port** | `127.0.0.1:8081` → container `8080` (`maps_port`, default.config wins over the role default `8070`) |
| **Stack** | `iiab` |
| **Toggle** | `install_offline_maps: false` (default; `requires: node`) |
| **Image** | `maptiler/tileserver-gl:v5.6.0` (`maps_tileserver_version`) |
| **Data** | `{{ nos_data_root }}/tenants/{{ nos_tenant_slug }}/shared/maps/data` → container `/data` (default `~/nos/tenants/dev/shared/maps/data`) |
| **Container** | `iiab-tileserver-1` (compose service `tileserver`) |
| **Manifest node** | `nos.iiab.offline-maps` |

## Authentication

- **App-level auth:** none — tileserver-gl has no native login.
- **SSO bucket:** `forward_auth`. Access is gated at the Traefik edge by the `authentik@file` middleware; a valid Authentik session is "you're in". There is no per-user identity inside the service.
- The forward-auth gate is why the health probe accepts 401/302 as healthy (the redirect to Authentik is the gate working).

## Content (MBTiles)

- The role auto-downloads one init fixture so the server starts with valid data: the tileserver-gl **Zurich demo** (~2 MB, `maps_init_mbtiles_url`). It is proof-of-life only.
- Operators add real archives via `maps_mbtiles_files` (a list of URLs) or by dropping `.mbtiles` files into the data dir. Without at least one `.mbtiles` file tileserver-gl logs "No valid data input" and serves an empty map.

## Health Check

- **Endpoint:** `GET /` (the web map viewer root).
- **Expected:** any `2xx`/`3xx`/`4xx` — behind forward-auth an unauthenticated probe returns `401`/`302`, which still proves the server is live (plugin `wait_health`, `accept_any_2xx_3xx_4xx: true`).

## Dependencies

- Node.js runtime on the host (`requires: node` on the install flag).
- Traefik (edge routing + forward-auth middleware).
- Authentik (SSO gate, optional).
