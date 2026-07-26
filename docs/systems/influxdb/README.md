# InfluxDB

> InfluxDB 2.x — time-series database for high-frequency measurements pushed by
> the estate's own instrumentation. A write target, distinct from the
> scrape-driven Prometheus metrics store.

## Quick Reference

| | |
|---|---|
| **URL** | `https://influxdb.<tenant_domain>` (local default `https://influxdb.dev.local`) |
| **Port** | `8086` (bound `127.0.0.1:8086` by default; `0.0.0.0` when `services_lan_access: true`) |
| **Stack** | `data` (taxonomy anchor `nos.data.influxdb`) — but the container is rendered into the `observability` compose project |
| **Toggle** | `install_influxdb: true` (default `false`) |
| **Image** | `influxdb:2.7.12` |
| **Data** | `{{ nos_data_root }}/platform/services/influxdb/data` (config at `…/influxdb/config`) |
| **SSO** | `forward_auth` — Authentik proxy gate (Tier 1), no native OIDC |

`nos_data_root` defaults to `~/nos`; on an external-disk install it is redirected
(e.g. `/Volumes/SSD1TB/nOS/data`). The path segment `platform/services/influxdb/data`
is constant.

## Authentication

- **Admin user:** `admin` (`influxdb_init_username`)
- **Admin password:** `{global_password_prefix}_pw_influxdb` (`influxdb_admin_password`)
- **API token:** `{global_password_prefix}_pw_influxdb_token` (`influxdb_admin_token`)
- **Initial org:** `nos` · **initial bucket:** `default` · **retention:** `90d`
- **SSO:** Authentik `forward_auth` gates the web UI at the Traefik proxy
  (`authentik@file` middleware). InfluxDB 2.x has no native OIDC — the HTTP API
  authenticates with the native InfluxDB token instead.

> **Token caveat:** `DOCKER_INFLUXDB_INIT_ADMIN_TOKEN` is read **only on the
> first-run setup** against an empty `/var/lib/influxdb2`. After first init the
> live token is fixed; re-rendering `influxdb_admin_token` does not rotate it.
> Read the actual live token before calling the API.

## API Access

- **Base URL (loopback, bypasses the proxy gate):** `http://127.0.0.1:8086`
- **v2 API root:** `/api/v2/`
- **Auth header:** `Authorization: Token <influxdb_admin_token>` (InfluxDB token
  scheme — NOT `Bearer`)
- **Org query param:** `?org=nos`

## Health Check

- **Endpoint:** `GET /health`
- **Expected:** `200 OK` with `{"name":"influxdb","status":"pass",...}`
- Also available: `GET /ping` (204), `GET /ready` (200 once serving).

## Dependencies

- None hard — InfluxDB is a standalone TSDB (no external database).
- Authentik (SSO gate at the proxy, optional — only when `install_authentik: true`).
- Traefik (edge proxy carrying the `forward_auth` middleware).
