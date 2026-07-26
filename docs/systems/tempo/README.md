# Tempo

> Distributed-tracing backend for the estate. Receives OTLP spans (forwarded by Alloy), stores trace blocks locally, and answers TraceQL. Queried through Grafana; no browser UI of its own on nOS.

## Quick Reference

| | |
|---|---|
| **URL** | `http://localhost:3200` (loopback only — no public domain, not Traefik-routed) |
| **HTTP port** | `3200` (`tempo_http_port`, published `127.0.0.1:3200`) |
| **OTLP gRPC** | `4327` (`tempo_otlp_grpc_port`, published `127.0.0.1:4327`) — internal Alloy → Tempo |
| **OTLP HTTP** | `4328` (`tempo_otlp_http_port`, published `127.0.0.1:4328`) — internal Alloy → Tempo |
| **Stack** | `observability` |
| **Toggle** | `install_observability: true` |
| **Image** | `grafana/tempo:2.10.3` |
| **Config** | `~/stacks/observability/tempo/tempo.yaml` |
| **Data** | `{{ tempo_storage_path }}` = `{{ nos_data_root }}/platform/services/tempo/storage` → default `~/nos/platform/services/tempo/storage` |
| **Container mount** | host data → `/var/lib/tempo` |
| **Retention** | `168h` (7 days) — `block_retention` in `tempo.yaml` / `tempo_retention` |
| **Limits** | `mem_limit` = `docker_mem_limit_light` (default `512m`), `cpus` = `0.5` |

Data-path note: `nos_data_root` defaults to `~/nos`. On external storage the path is overridden to `{{ external_storage_root }}/observability/tempo` (`tasks/stacks/external-paths.yml`). The config lives under `stacks_dir` (`~/stacks`), which is config, not persistent data.

OTLP-port note: Tempo's own OTLP receivers are `4327`/`4328`. Do not confuse them with Alloy's public OTLP receivers (`4317`/`4318`) — apps send to Alloy, Alloy forwards to Tempo.

## Authentication

- **Admin user:** none — Tempo has no login.
- **Auth:** none. The HTTP API is unauthenticated and bound to `127.0.0.1` only.
- **SSO:** none. Tempo has no Authentik provider (no `authentik:` block in `files/anatomy/plugins/tempo-base/plugin.yml`); it is a backend trace store, not a browser-facing service. The SSO-gated way to explore traces is through Grafana → Explore → Tempo (see `../grafana/`).

## API Access

- **Base URL:** `http://localhost:3200/api/`
- **Auth method:** none (loopback, unauthenticated)
- **Surface:** the native Tempo query API — fetch a trace by ID, TraceQL search, tag discovery. Span ingestion is OTLP-only (Alloy forwards), not an agent action.
- **Security note:** do not probe `/status/config` (REM-036, accepted-risk) — the estate deliberately omits that link; it is not a documented skill here.

## Health Check

- **Endpoint:** `GET /ready`
- **Expected:** `200 OK`
- The container healthcheck is intentionally disabled (`healthcheck.disable: true`) — the distroless image has no curl/wget and the Tempo CLI has no `-config.verify` flag; readiness is observed via `/ready` on `:3200`.

## Dependencies

- **Alloy** — forwards OTLP spans to Tempo's OTLP gRPC receiver (`tempo_otlp_grpc_port`).
- **Grafana** — the query frontend; Tempo is a Grafana data source (traces).
- **Prometheus** — Tempo's metrics-generator remote-writes span metrics to `http://prometheus:9090/api/v1/write`.
- Master config (receivers, retention, local storage backend) is provisioned by the `tempo-base` plugin into `~/stacks/observability/tempo/tempo.yaml`.
