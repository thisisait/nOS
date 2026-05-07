# offline-maps-base — content batch (Q5)

> **Status:** live, captured 2026-05-07. Wires `pazny.offline_maps`
> (tileserver-gl) into the plugin loader. Forward-auth at the Traefik
> layer; no app-level authentication. Tier 3 (user) — offline-first
> map tile serving in the iiab stack.

## What this plugin owns

| Surface | Block | Notes |
|---|---|---|
| Health probe | `lifecycle.post_compose.wait_health` | Root path; tolerant of forward-auth 401/302 |
| Loki labels | `observability.loki.labels` | `app=tileserver, stack=iiab, tier=3` |
| GDPR Article 30 row | `gdpr:` | `legitimate_interests`, retention 30d |
| Wing /hub deep-link card | `ui-extension.hub_card` | Operator entry point to the tile viewer UI |

## What stays in the role

`roles/pazny.offline_maps/` keeps install responsibilities — image pin,
host port (8070), data dir on `~/maps`, tileserver-gl `config.json`
render, MBTiles auto-download (Zurich demo by default; operators
override via `maps_mbtiles_files`). This plugin layers cross-cutting
wiring (health, telemetry, hub) on top.

## SSO posture

tileserver-gl has **no native OIDC**. Operator access is gated by the
Authentik forward-auth Traefik middleware (`authentik@file`), applied
at the proxy layer rather than per-plugin. No `authentik:` block in
this manifest — forward-auth bindings live in
`roles/pazny.traefik/` configuration.

## Activation

Activates when `install_offline_maps: true` is set in `config.yml`.
The role downloads at least one .mbtiles fixture so tileserver-gl
starts cleanly (without one it logs `No valid data input` and serves
an empty map).
