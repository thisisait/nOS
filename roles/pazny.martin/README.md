# pazny.martin

martin (`ghcr.io/maplibre/martin`, digest-pinned, arm64) serving the PostGIS `geo`
schema as vector tiles at `https://atlas.<tenant_domain>/tiles/`. Off by default:
`install_martin: true` (needs `install_postgis`, and `install_geolibre` for the route).

## Shape

- **Sources are explicit** (`templates/config.yaml.j2`, `auto_publish: false`):
  `party_site` (address point), `party_site_parcel` (the parcel of a site),
  `inspire_cp`, `inspire_bu` (zoom ≥ 12). A layer geo-load has not loaded yet is
  skipped with a warning (`on_invalid: warn`).
- **Read-only login** `martin` (password: `nos_derived_secrets.martin_db`), made by
  `pazny.postgresql` post.yml: USAGE on schema `geo`, SELECT on its tables and on
  future ones created by the superuser, `default_transaction_read_only`. Nothing else.
- **Edge:** no host port, no own router. The geolibre router has a gated `tiles` lane
  (`authentik@file`) → `martin:3000`, so the atlas app (forward_auth tier 3) gates it.
  Same origin as GeoLibre: the browser sends the atlas cookie with each tile and no
  CORS is needed (`cors: false`). A `tiles.<tenant>` host would not work: MapLibre
  fetches with `credentials: same-origin`, so every tile would 302 into Authentik.
- **Erasure:** no tile cache (`cache: disable`) and `Cache-Control: no-store`; the
  party sources read the view over `geo.party_site`, so `--erase-party` takes effect
  on the next tile.

## In GeoLibre

GeoLibre v3.2.0's catalog (`geolibre_layers`) has no vector-tile kind and its `xyz`
kind refuses a vector TileJSON, so there is no catalog entry. Add a layer by hand:
**Add data → OGC vector tiles** → `https://atlas.<tenant>/tiles/party_site`
(or `party_site_parcel`, `inspire_cp`, `inspire_bu`). `/tiles/catalog` lists them.
