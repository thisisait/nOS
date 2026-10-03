# GeoLibre (atlas)

Browser GIS with the nos-atlas plugin, which draws the KEAP taxonomy as a planet.
Upstream: github.com/opengeos/GeoLibre (MIT). Plugin source: `~/projects/nos-atlas`.

| | |
|---|---|
| URL | `https://atlas.<tld>` (`geolibre_domain`) |
| Role | `roles/pazny.geolibre` (iiab stack), plugin `geolibre-base` |
| Container | `iiab-geolibre-1`, `127.0.0.1:8072` (`geolibre_port`) |
| Edge | Traefik + Authentik forward-auth, tier 3 |
| Data | `geolibre_data_dir/plugins/nos-atlas`, a copy of nos-atlas `dist/`, mounted read-only |
| Enable | `install_geolibre: true` in `config.yml`, then `nos --tags geolibre` |

## First visit

GeoLibre cannot preload an external plugin at runtime. Each browser adds it once:
**Settings → Manage Plugins → Settings** → `https://atlas.<tld>/plugins/nos-atlas/plugin.json`,
then **Plugins → nOS Atlas**. Details and the build-time alternative:
`roles/pazny.geolibre/README.md`.

## Updating the plugin

Run `npm run build` in nos-atlas, then `nos --tags geolibre`. The role copies `dist/`
again; reload the browser tab.
