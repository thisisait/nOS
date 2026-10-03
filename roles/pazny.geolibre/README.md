# pazny.geolibre

GeoLibre (static web GIS, `ghcr.io/opengeos/geolibre`, digest-pinned) in the `iiab`
stack, with the nos-atlas (`~/projects/nos-atlas`) plugin mounted as a
drop-in. Served at `https://atlas.<tenant_domain>` behind Authentik forward-auth (tier 3).
Off by default: `install_geolibre: true` in `config.yml`, then `nos --tags geolibre`.

## What it does

1. Copies `{{ nos_atlas_src_dir }}/dist/nos-atlas/` into
   `{{ geolibre_data_dir }}/plugins/nos-atlas/`. The container mounts that copy
   read-only at `/usr/share/nginx/html/plugins/nos-atlas`; the dev checkout is never
   mounted. No `dist/` yet: a named debug line, GeoLibre still comes up. Building the
   bundle (`npm run build` in nos-atlas) is not this role's job.
2. Renders `{{ stacks_dir }}/iiab/overrides/geolibre.yml` (`GEOLIBRE_SHARE_URL=off`).

## The one click: enable the plugin

GeoLibre v3.2.0 has no runtime switch for a default plugin list. Its "bundled plugins"
are discovered at **build** time (`virtual:bundled-plugins`), the installed list lives
in each browser's settings, and a `?plugin=` deep link only activates built-ins. So
each browser adds it once:

**Settings → Manage Plugins → Settings** → add
`https://atlas.<tenant_domain>/plugins/nos-atlas/plugin.json`, then **Plugins → nOS Atlas**.

To make it automatic, build a GeoLibre image with `dist/nos-atlas` copied into
`apps/geolibre-desktop/public/plugins/` before `npm run build`.

## Layer catalog

`geolibre_layers` in `default.config.yml` is the one declaration. The role renders it to
`{{ geolibre_data_dir }}/catalog/services.json`, mounted read-only as
`GEOLIBRE_SERVICES_FILE`, so the layers appear in the **Browser** panel. GeoLibre reads
the file at boot and refuses to start on a bad entry. The schema is in
`docker/entrypoint.sh` at the image revision. Only free, keyless services go in, and each
entry cites its licence (`licence_url`). GeoLibre shows no attribution per service, so
the required credit (ČÚZK – on-line, © OpenStreetMap) is part of the layer name. The
`maps.<tenant>` basemap is listed only when `install_offline_maps` is on, as raster tiles. For the vector style, use a custom style URL in the New map dialog
(`https://maps.<tenant>/styles/liberty/style.json`). Gate:
`tests/anatomy/test_geolibre_layer_catalog.py`.

PostGIS layers (`geo.party_site`) are not listed: no tile server serves them yet.

## Atlas data refresh

Pulse `geolibre:atlas-refresh` (hourly) runs `tools/atlas-refresh.py`. It records the
reader snapshot read-only (red-status, estate-status, and wing.db pulse_jobs/pulse_runs
without command, args or env). Then it runs the nos-atlas generator and writes into
`{{ geolibre_data_dir }}/plugins/nos-atlas/data`. A converge's bundle copy overwrites
that directory with the `dist/` data until the next run. The KEAP taxonomy fixture is
not rebuilt by the job (`npm run fixture` in nos-atlas).
