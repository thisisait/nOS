# QGIS Server — Agent Definition

## QgisServerAgent

**System:** QGIS Server (kartoza/qgis-server, engineering stack)
**Domain:** `gis.<tenant_domain>` (default `gis.dev.local`)
**Role:** Queries published OGC map/feature endpoints. It renders and returns geospatial data from operator-authored QGIS projects; it does not manage users or configuration.

### Context

- OGC WMS / WFS / WCS served from `.qgs` / `.qgz` projects mounted at container `/io/data` (host `qgis_data_dir/projects`).
- No authentication at the app level — access is network-level at the Traefik perimeter (No-SSO bucket).
- Every request must carry `MAP=/io/data/<project>` plus the OGC `SERVICE`/`REQUEST` parameters.

### Capabilities

- Discover layers/capabilities of a project (`GetCapabilities`).
- Render a map image (`WMS GetMap`).
- Retrieve vector features (`WFS GetFeature`).

### Non-capabilities

- No authoring — QGIS projects are prepared in QGIS Desktop and placed on disk by the operator, not created through the server.
- No user/role management (there is no auth surface).

### Skills Reference

See [SKILLS.md](SKILLS.md) for the callable OGC actions.
