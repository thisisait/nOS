# QGIS Server

> Backend OGC map server. Publishes WMS / WFS / WCS endpoints from QGIS project files. No browser-root UI, no SSO — a headless geospatial service in the engineering stack.

## Quick Reference

| | |
|---|---|
| **URL** | `https://gis.<tenant_domain>` (derived from `qgis_domain`; default `gis.dev.local`) |
| **Host port** | `127.0.0.1:8071` → container `80` (`qgis_port`) |
| **Stack** | `engineering` |
| **Toggle** | `install_qgis_server: false` (default) |
| **Image** | `kartoza/qgis-server:latest` (`qgis_version`; default.config `latest` overrides the role default `LTR`) |
| **Platform** | `linux/amd64` only — runs under Rosetta emulation on Apple Silicon |
| **Data** | `{{ nos_data_root }}/platform/services/qgis/data/projects` → container `/io/data` (default `~/nos/platform/services/qgis/data/projects`) |
| **Container** | `engineering-qgis-server-1` (compose service `qgis-server`) |
| **Manifest node** | `nos.engineering.qgis-server` |

## Authentication

- **App-level auth:** none. QGIS Server is in the "No SSO" bucket (alongside FreePBX).
- **SSO bucket:** `none`. The OGC endpoints (WMS GetMap, WFS GetFeature) are stateless and consumed directly by GIS clients; the only access control is network-level at the Traefik perimeter. No `authentik:` block exists for this service.
- `kind: backend` — the plugin marks it backend-only so Wing `/hub` suppresses the (would-404) tile.

## API (OGC)

- **Endpoint:** the service root `/` with OGC query parameters.
- **Required parameter:** `MAP=` must point at a QGIS project file under the container's `/io/data` (host `qgis_data_dir/projects`). A request without `?MAP=` returns HTTP 500 (a bare root GET is expected to fail — that is documented behaviour, not an outage).
- Standard OGC verbs: `SERVICE=WMS|WFS|WCS` + `REQUEST=GetCapabilities|GetMap|GetFeature|...`.

## Health Check

- **Container healthcheck:** TCP liveness on internal `:80` (`:>/dev/tcp/127.0.0.1/80`) — the kartoza image ships no curl/wget, and a bare HTTP GET without OGC params would error.
- **Plugin `wait_health`:** `GET /` accepting `2xx`/`3xx`/`4xx` (root returns 500 without `?MAP=`; that counts as live). Cold-start budget is generous (90s) because amd64 emulation is slow.

## Dependencies

- QGIS project files (`.qgs` / `.qgz`) placed under `qgis_data_dir/projects` — the service has nothing to serve without them.
- Traefik (edge routing; network-level access control).
- Rosetta / Docker Desktop amd64 emulation on Apple Silicon.
