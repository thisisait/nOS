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

## Basemap

GeoLibre has no runtime default-style setting, so `maps.<tenant>` (`pazny.offline_maps`,
public, no forward-auth) is not wired; the nos-atlas plugin sets its own planet style
anyway. Add it by hand in the New map dialog (custom style URL
`https://maps.<tenant>/styles/liberty/style.json`). Next step if wanted:
`GEOLIBRE_SERVICES_FILE` can list it as an `xyz` service
(`/styles/liberty/{z}/{x}/{y}.png`) in the Browser panel.
