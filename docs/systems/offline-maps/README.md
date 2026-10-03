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

## Content

- **Base map:** Planetiler builds OpenMapTiles PMTiles for `maps_region` (default `czech-republic`) into `maps_cache_dir` once; served as dataset `basemap` with the vendored `liberty` style (labels in Czech). Details and measured build cost: `roles/pazny.offline_maps/README.md`.
- Extra archives: `maps_mbtiles_files` (a list of `{url, dest}`) or `.pmtiles`/`.mbtiles` dropped into the data dir; each is served by basename.

## Health Check

- **Endpoint:** `GET http://127.0.0.1:<maps_port>/styles/liberty/style.json` (loopback, no forward-auth).
- **Expected:** `200` only. The e2e probes also read `/data/basemap.json` back; an empty tileserver is red.

## Dependencies

- Node.js runtime on the host (`requires: node` on the install flag).
- Traefik (edge routing + forward-auth middleware).
- Authentik (SSO gate, optional).
