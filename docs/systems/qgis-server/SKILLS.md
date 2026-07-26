# QGIS Server — Skills

> Callable OGC actions. QGIS Server publishes standard WMS / WFS / WCS endpoints from operator-authored QGIS projects.

## Authentication

- **Method:** N/A — no app-level auth. Access is network-level at the Traefik perimeter (No-SSO bucket). Every request instead requires a `MAP=` parameter naming the project to serve.

## Base contract

- **Endpoint root:** `https://gis.<tenant_domain>/` (loopback `http://127.0.0.1:8071/`).
- **Mandatory:** `MAP=/io/data/<project>.qgs` (or `.qgz`) — the project must exist under the host mount `qgis_data_dir/projects`. A request without `MAP=` returns HTTP 500 by design.

---

## get-capabilities

**Trigger:** "list map layers", "what does this QGIS project serve", "WMS/WFS capabilities"
**Method:** OGC HTTP GET
**Endpoint:** `GET /?MAP=/io/data/<project>.qgs&SERVICE=WMS&REQUEST=GetCapabilities`
**Input:** `SERVICE` = `WMS` | `WFS` | `WCS`; `MAP` = project path.
**Output:** an XML capabilities document listing layers, CRS, bounding boxes and supported operations.

---

## get-map

**Trigger:** "render a map image", "get a WMS tile", "draw layer [x] for this bbox"
**Method:** OGC HTTP GET
**Endpoint:** `GET /?MAP=/io/data/<project>.qgs&SERVICE=WMS&REQUEST=GetMap&LAYERS=<layer>&BBOX=<minx,miny,maxx,maxy>&WIDTH=<px>&HEIGHT=<px>&CRS=<epsg>&FORMAT=image/png`
**Output:** a rendered raster image (PNG/JPEG per `FORMAT`).

---

## get-feature

**Trigger:** "get vector features", "query WFS", "return geometries for layer [x]"
**Method:** OGC HTTP GET
**Endpoint:** `GET /?MAP=/io/data/<project>.qgs&SERVICE=WFS&REQUEST=GetFeature&TYPENAME=<layer>`
**Output:** GML / GeoJSON feature collection (per `OUTPUTFORMAT`).
