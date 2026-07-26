# Prometheus

> Metrics time-series backend for the estate. Receives Alloy remote-write, scrapes exporters, and answers PromQL. Queried through Grafana; no browser UI of its own on nOS.

## Quick Reference

| | |
|---|---|
| **URL** | `http://localhost:9090` (loopback only — no public domain, not Traefik-routed) |
| **Port** | `9090` (published `127.0.0.1:9090`) |
| **Stack** | `observability` |
| **Toggle** | `install_observability: true` |
| **Image** | `prom/prometheus:v3.11.3` |
| **Config** | `~/stacks/observability/prometheus/prometheus.yml` (+ `rules/`) |
| **Data** | `{{ nos_data_root }}/platform/services/prometheus/storage` → default `~/nos/platform/services/prometheus/storage` |
| **Container mount** | host data → `/prometheus` |
| **Retention** | `30d` (`prometheus_retention`) |
| **Limits** | `mem_limit` = `docker_mem_limit_standard` (default `1g`), `cpus` = `1.0` |

Data-path note: `nos_data_root` defaults to `~/nos`. On external storage the path is overridden to `{{ external_storage_root }}/observability/prometheus` (`tasks/stacks/external-paths.yml`). The config + rules live under `stacks_dir` (`~/stacks`), which is config, not persistent data.

## Authentication

- **Admin user:** none — Prometheus has no login.
- **Auth:** none. The HTTP API is unauthenticated and bound to `127.0.0.1` only.
- **SSO:** none. Prometheus has no Authentik provider (no `authentik:` block in `files/anatomy/plugins/prometheus-base/plugin.yml`); it is a backend datastore, not a browser-facing service. The SSO-gated way to query these metrics is through Grafana (see `../grafana/`).

## API Access

- **Base URL:** `http://localhost:9090/api/v1/`
- **Auth method:** none (loopback, unauthenticated)
- **Surface:** the native Prometheus v3 HTTP API — read-only query + introspection endpoints. Config reload (`POST /-/reload`) is **disabled**: the container is not started with `--web.enable-lifecycle`, so reloads happen via a playbook re-render, not the API.
- **Ingest:** Prometheus runs with `--web.enable-remote-write-receiver`; Alloy remote-writes metrics to `http://prometheus:9090/api/v1/write` over `observability_net`.

## Health Check

- **Endpoint (manifest):** `GET /-/healthy`
- **Readiness:** `GET /-/ready`
- **Expected:** `200 OK`

## Dependencies

- **Alloy** — remote-writes host + container metrics into Prometheus (`prometheus_port` is Alloy's remote_write target).
- **Grafana** — the query frontend; Prometheus is a Grafana data source (metrics).
- Scrape jobs + recording/alert rules are provisioned by the `prometheus-base` plugin into `~/stacks/observability/prometheus/`.
