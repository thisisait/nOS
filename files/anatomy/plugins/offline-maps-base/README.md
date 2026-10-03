# offline-maps-base — content batch (Q5)

> **Status:** live, captured 2026-05-07. Wires `pazny.offline_maps`
> (tileserver-gl) into the plugin loader. Forward-auth at the Traefik
> layer; no app-level authentication. Tier 3 (user) — offline-first
> map tile serving in the iiab stack.

## What this plugin owns

| Surface | Block | Notes |
|---|---|---|
| Health probe | `lifecycle.post_compose.wait_health` | `/styles/liberty/style.json` on loopback, 200 only |
| E2E probes | `e2e.probes` | style + `basemap` TileJSON read back (200) |
| Blank cleanup | `lifecycle.post_blank` | removes `maps_data_dir` (the base map cache survives) |
| Loki labels | `observability.loki.labels` | `app=tileserver, stack=iiab, tier=3` |
| GDPR Article 30 row | `gdpr:` | `legitimate_interests`, retention 30d |
| Wing /hub deep-link card | `ui-extension.hub_card` | Operator entry point to the tile viewer UI |

## What stays in the role

`roles/pazny.offline_maps/` keeps install responsibilities — image pin,
the Planetiler base-map build into `maps_cache_dir`, glyphs/sprites, the
vendored style and the tileserver-gl `config.json` render. This plugin layers cross-cutting
wiring (health, telemetry, hub) on top.

## SSO posture

tileserver-gl has **no native OIDC**. Operator access is gated by the
Authentik forward-auth Traefik middleware (`authentik@file`), applied
at the proxy layer rather than per-plugin. No `authentik:` block in
this manifest — forward-auth bindings live in
`roles/pazny.traefik/` configuration.

## Activation

Activates when `install_offline_maps: true` is set in `config.yml`.
The first run builds the `maps_region` base map with Planetiler (minutes,
GBs of downloads — see the role README); later runs reuse the cache.
