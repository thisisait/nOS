# martin (geo tiles)

Vector tiles of the PostGIS `geo` schema for GeoLibre. Upstream: github.com/maplibre/martin
(Apache-2.0 OR MIT).

| | |
|---|---|
| URL | `https://atlas.<tld>/tiles/` (`/tiles/catalog` lists the sources) |
| Role | `roles/pazny.martin` (iiab stack), plugin `martin-base` |
| Container | `iiab-martin-1`, no host port; Traefik dials `martin:3000` |
| Edge | the gated `tiles` lane on the atlas router: Authentik forward-auth, tier 3 |
| Database | `geo`, as the read-only login `martin` (schema `geo` only) |
| Sources | `party_site`, `party_site_parcel`, `inspire_cp`, `inspire_bu` |
| Cache | none — an erased party is absent from the next tile |
| Enable | `install_martin: true` (with `install_postgis`, `install_geolibre`) in `config.yml` |

## Setup

Set the flag, then converge PostgreSQL (role and grants), the stack and the edge:
`nos --tags postgresql,martin,traefik`. Load data with `tools/geo-load.py` and
`tools/geo-project-sites.py`; a source whose table does not exist yet is skipped.

## In GeoLibre

There is no catalog entry: GeoLibre v3.2.0's catalog has no vector-tile kind. Add a
layer with **Add data → OGC vector tiles** → `https://atlas.<tld>/tiles/party_site`.
