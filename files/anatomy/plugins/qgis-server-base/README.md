# qgis-server-base — content batch (Q5)

> **Status:** live, captured 2026-05-07. Wires `pazny.qgis_server`
> (kartoza/qgis-server) into the plugin loader. **No SSO** — QGIS
> Server is in CLAUDE.md's "No SSO" bucket alongside FreePBX.
> Tier 3 (user) — OGC WMS / WFS / WCS endpoint serving from the
> engineering compose stack.

## What this plugin owns

| Surface | Block | Notes |
|---|---|---|
| Health probe | `lifecycle.post_compose.wait_health` | 90s timeout — amd64 Rosetta cold-start is slow |
| Loki labels | `observability.loki.labels` | `app=qgis-server, stack=engineering, tier=3` |
| GDPR Article 30 row | `gdpr:` | `legitimate_interests`, retention 30d |
| Wing /hub deep-link card | `ui-extension.hub_card` | Operator entry point to the OGC root |

## What stays in the role

`roles/pazny.qgis_server/` keeps install responsibilities — image pin
(amd64-only kartoza/qgis-server, runs via Rosetta on M-series),
`platform: linux/amd64` declaration, host port (8071), data dir on
`~/qgis/projects/`, tuning env vars (`QGIS_SERVER_LOG_LEVEL`,
`QGIS_SERVER_MAX_THREADS`, `QGIS_SERVER_PARALLEL_RENDERING`). This
plugin layers cross-cutting wiring (health, telemetry, hub) on top.

## SSO posture

**No SSO.** QGIS Server publishes stateless OGC endpoints (WMS GetMap,
WFS GetFeature, WCS GetCoverage) consumed directly by GIS clients
(QGIS Desktop, ArcGIS, browsers). Per the CLAUDE.md SSO trichotomy,
adding either native OIDC or forward-auth in front would break the
OGC contract. Access control is network-level at the Traefik
perimeter. No `authentik:` block in this manifest — by design.

## Activation

Activates when `install_qgis_server: true` is set in `config.yml`.
Apple Silicon constraint: the kartoza image is amd64-only and runs
under Rosetta emulation, which adds ~20–30s to cold start.
