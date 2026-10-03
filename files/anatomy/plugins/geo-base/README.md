# geo-base — open cadastral data + party sites in PostGIS

Two Pulse jobs over the `geo` database that `install_postgis` creates
(roles/pazny.postgresql). Both idle (exit 0) where there is no geo database.

| Job | Schedule | Writes |
|---|---|---|
| `geo:geo-load` (`tools/geo-load.py`) | monthly, 6th 03:30 | `geo.ruian_adm`, `geo.inspire_cp`, `geo.inspire_bu`, `geo.load_log` |
| `geo:project-sites` (`tools/geo-project-sites.py`) | nightly 02:20 | `geo.party_site`, view `geo.party_site_geom` |

Success is read back by `tools/geo-status.py` (a reader: row counts per layer).

## Sources (open data, no account, no paid service)

- ČÚZK KÚ catalogue `SC_SEZNAMKUKRA_DOTAZ` — which KÚ / obec lies in which kraj (`geo_regions`, VÚSC codes).
- RÚIAN address points CSV (CC-BY 4.0), month-end state; URL computed (the HTML index is behind a bot captcha).
- INSPIRE Cadastral Parcels per KÚ, Buildings per obec, GML in EPSG:5514 ("no conditions").

Stored as delivered in **EPSG:5514**; consumers `ST_Transform` (to 4326/3857).
No duplicated reprojected columns until a measured consumer needs them.
PROJ has no network grids in the image, so 5514→4326 is the standard
Helmert-based transform (about 1 m), not the grid-exact one.

## Measured — Jihočeský kraj (35), 2026-10-03, throwaway container

| | |
|---|---|
| Units | 1625 KÚ, 624 obcí |
| Downloads | CP 1.0 GB (1625 zips), BU 90 MB, RÚIAN 61 MB (all CZ, filtered to the kraj) |
| Rows | ruian_adm 224 561 · inspire_cp 2 214 864 · inspire_bu 343 432 |
| Load from cache | 19 min 37 s (CP dominates); downloads alone ~6 min |
| Unchanged rerun | seconds (If-Modified-Since + same unit set → "kept") |
| geo db size | 969 MB |
| Host RSS of the loader | ~260 MB (work runs in the PostgreSQL container) |

Two obce (537144, 545422) publish only `BuildingPart` points and no
`Building` layer; the loader skips and names them every run.

## Party sites

KEAP owns `party-site` (operator-entered: kind, RÚIAN ADM, KÚ + parcel
number in the INSPIRE label form — `st. 481` for a building parcel —
building kód SO). The ARES pack fills `party-registry-status.sidlo_ruian_adm`;
a party without an operator `hq` gets its ARES seat projected as `hq/ares`.
Erasure: `tools/digest-teardown.py --erase-party <slug> --confirm` erases the
KEAP rows and `geo.party_site` together (`state/gdpr-erasure-map.yml` svc_geo).
