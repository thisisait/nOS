# pazny.offline_maps

The offline-maps subsystem of the `iiab` stack: tileserver-gl serving one
OpenMapTiles base map that Planetiler builds locally from OpenStreetMap, plus a
vendored OpenFreeMap style. No hosted tile provider is called at view time.
The compose service is still named `tileserver`.

## What it does

Runs from `tasks/stacks/stack-up.yml` before `docker compose -p iiab up`:

1. Builds `{{ maps_cache_dir }}/planetiler/{{ maps_region }}.pmtiles` with a
   one-shot `ghcr.io/onthegomap/planetiler` container (`creates:` — once per region).
   Sources (Geofabrik extract, water polygons, Natural Earth) stay under
   `planetiler/data/sources`.
2. Fetches the OpenFreeMap glyphs (`ofm.tar.gz`, linked as `fonts/`) and sprites
   into the cache.
3. Copies `files/styles/*.json` into `{{ maps_data_dir }}/styles/` and renders
   `config.json` (dataset `basemap` + every `*.pmtiles`/`*.mbtiles` found in the data dir).
4. Renders the nginx vhost (macOS) and the compose override.

Nothing hides a failure: a map that does not arrive fails the play
(gate `tests/anatomy/test_offline_maps_serves_a_basemap.py`).

`maps_cache_dir` lives under `artifact_cache_dir`, so no removal level deletes
the base map; `remove=data` only drops `maps_data_dir` (styles + config).

## Style

`files/styles/liberty.json` is OpenFreeMap "liberty" rewritten by
`tools/maps-style-vendor.py`: the source becomes `pmtiles://{basemap}`, the
hosted hillshade is dropped, labels prefer `name:cs`. Re-run the tool to refresh.

## Variables (default.config.yml)

| Variable | Default | |
|---|---|---|
| `maps_region` | `czech-republic` | Geofabrik slug passed to `--area` |
| `maps_languages` | `cs,en,de,sk,pl` | `name:*` tags kept |
| `maps_planetiler_version` | `0.10.2` | image tag |
| `maps_planetiler_java_opts` | `-Xmx3g` | JVM heap for the build |
| `maps_cache_dir` | `{{ artifact_cache_dir }}/maps` | survives every removal |
| `maps_fonts_url`, `maps_sprites_url` | OpenFreeMap assets | fetched once |
| `maps_mbtiles_files` | `[]` | extra `{url, dest}` archives into the data dir |

## Measured build (Czech Republic)

Measured 2026-10-03 on an M-series Mac (Docker VM 16.5 GiB, 13 CPUs, the estate
running beside it at ~9.8 GiB), planetiler 0.10.2, `--languages=cs,en,de,sk,pl`:

| | |
|---|---|
| Downloads (first run only) | ~2.4 GB: Geofabrik CZ extract ~0.95 GB, water polygons 0.93 GB, Natural Earth 0.43 GB, lake centerlines 0.08 GB — ~4 min at 4–11 MB/s |
| Build (sources cached) | 4 min 14 s wall (19 min CPU), 258 s end to end |
| Peak container RAM | 3.16 GiB with `-Xmx3g` |
| Output | `czech-republic.pmtiles` 652 MB (z0–14, 1.9 GB of features) |

`-Xmx6g` was SIGKILLed (rc 137) in the encode phase twice: heap plus mmap'd temp
files exceeded what the VM had left beside the estate. 3 GiB is enough for CZ.
Served by tileserver-gl v5.6.0 at ~220 MiB RSS: style, TileJSON, vector tiles,
glyphs, sprites and server-side raster render all 200 (throwaway container).

## Licences

Map data © OpenStreetMap contributors (ODbL); OpenMapTiles schema (BSD/CC-BY);
OpenFreeMap style/sprites (BSD), Noto fonts (OFL).
