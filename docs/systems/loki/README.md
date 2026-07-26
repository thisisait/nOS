# Loki

> Log-aggregation backend for the estate. Alloy tails host, container, nginx, PHP-FPM and agent logs and pushes them here; queried with LogQL through Grafana. No browser UI of its own on nOS.

## Quick Reference

| | |
|---|---|
| **URL** | `http://localhost:3100` (loopback only — no public domain, not Traefik-routed) |
| **Port** | `3100` (published `127.0.0.1:3100`) |
| **Stack** | `observability` |
| **Toggle** | `install_observability: true` |
| **Image** | `grafana/loki:3.7.2` |
| **Config** | `~/stacks/observability/loki/local-config.yaml` |
| **Data** | `{{ loki_storage_path }}` = `{{ nos_data_root }}/platform/services/loki/storage` → default `~/nos/platform/services/loki/storage` |
| **Container mount** | host data → `/loki` |
| **Retention** | `744h` (31 days) (`loki_retention`) |
| **Limits** | `mem_limit` = `docker_mem_limit_standard` (default `1g`), `cpus` = `1.0` |

Data-path note: `nos_data_root` defaults to `~/nos`. On external storage the path is overridden to `{{ external_storage_root }}/observability/loki` (`tasks/stacks/external-paths.yml`). The config lives under `stacks_dir` (`~/stacks`), which is config, not persistent data.

## Authentication

- **Admin user:** none — Loki has no login.
- **Auth:** none. The HTTP API is unauthenticated and bound to `127.0.0.1` only (Loki runs in single-tenant / `auth_enabled: false` mode).
- **SSO:** none. Loki has no Authentik provider (no `authentik:` block in `files/anatomy/plugins/loki-base/plugin.yml`); it is a backend log store, not a browser-facing service. The SSO-gated way to search these logs is through Grafana → Explore → Loki (see `../grafana/`).

## API Access

- **Base URL:** `http://localhost:3100/loki/api/v1/`
- **Auth method:** none (loopback, unauthenticated)
- **Surface:** the native Loki HTTP API — read-only LogQL query + label introspection endpoints. Log ingestion (`POST /loki/api/v1/push`) is owned by Alloy, not agents.

## Health Check

- **Endpoint:** `GET /ready`
- **Expected:** `200 OK`
- Container healthcheck instead verifies the config (`loki -verify-config`), because that is what the distroless image can run internally.

## Dependencies

- **Alloy** — pushes tailed log streams into Loki (`loki_port` is Alloy's `loki.write` target).
- **Grafana** — the query frontend; Loki is a Grafana data source (logs).
- Master config (retention, schema, storage backend) is provisioned by the `loki-base` plugin into `~/stacks/observability/loki/local-config.yaml`.
