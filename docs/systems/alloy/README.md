# Alloy

> Grafana Alloy — the estate's telemetry **collector**. A host binary (not a Docker service) that scrapes metrics, tails logs, and receives OTLP, then forwards everything to Prometheus, Loki and Tempo. It is a shipper, not a store, and not a browser-facing service.

## Quick Reference

| | |
|---|---|
| **URL** | `http://localhost:12345` (loopback UI only — no public domain, no TLS, no SSO) |
| **UI port** | `12345` (`alloy_ui_port`) |
| **OTLP gRPC receiver** | `4317` (`alloy_otlp_grpc_port`) — apps → Alloy |
| **OTLP HTTP receiver** | `4318` (`alloy_otlp_http_port`) — apps → Alloy |
| **OTLP bind addr** | `127.0.0.1` (`alloy_otlp_bind_addr`) |
| **Stack** | host-native (not a compose stack — see Anchor below) |
| **Category** | `observability` |
| **Toggle** | `install_observability: true` |
| **Install** | Homebrew formula `grafana-alloy`, run as a `brew services` daemon |
| **Version** | not pinned — brew installs the current formula (`alloy_version` has no default) |
| **Config (live)** | `{{ homebrew_prefix }}/etc/grafana-alloy/config.alloy` → default `/opt/homebrew/etc/grafana-alloy/config.alloy`, rendered by `tasks/observability.yml` from `files/observability/alloy/config.alloy.j2` (464 lines — the whole pipeline). This is the **only** render wired to the reload handler (`notify: Restart alloy`, `main.yml`). |
| **Config (plugin, second copy)** | `~/.config/alloy/config.alloy` — the `alloy-base` plugin also renders a **minimal core** here (`provisioning.config`, ~5.8 kB: logging + self-scrape + remote_write + loki.write + OTLP receiver). Nothing notifies a reload for it. Editing this file is **not** how you change the running pipeline. |
| **Data** | none persistent — only a small on-disk WAL for send retries (~hours) |

Anchor: Alloy's `state/manifest.yml` row has **no `stack:`** (it is host-installed, outside Docker Compose). `keap_selfmodel_gen.py` buckets a stackless row into `HOST_STACK = "host"`, so its taxonomy node is **`nos.host.alloy`**, not `nos.observability.alloy` — even though its category is `observability`.

Port note: Alloy's `4317`/`4318` are the **public** OTLP receivers apps send to. Tempo's own OTLP receivers are `4327`/`4328` — Alloy forwards there. Don't confuse the two pairs.

## Authentication

- **Admin user:** none — Alloy has no login.
- **Auth:** none. The UI on `:12345` is localhost-only, no TLS. The OTLP receiver binds to `alloy_otlp_bind_addr` (default `127.0.0.1`).
- **SSO:** none. Alloy is not Traefik-routed and has no Authentik provider; `files/anatomy/plugins/alloy-base/plugin.yml` declares `ui_port: 12345 # localhost-only, no TLS, no SSO`.

## API / UI Access

- **UI:** `http://localhost:12345` — a read-only inspection UI for the running pipeline (components, graph, self-metrics). Not an action API.
- **Self-metrics:** `GET /metrics` (Prometheus format, Alloy's own telemetry).
- **Config:** Alloy's config is **Ansible-owned** — rendered to `{{ homebrew_prefix }}/etc/grafana-alloy/config.alloy` and reloaded during a playbook run (the `Restart alloy` handler in `main.yml` unloads/loads `~/Library/LaunchAgents/homebrew.mxcl.grafana-alloy.plist`), not through the API. There is no operator/agent-facing mutation surface. To change what Alloy collects, edit `files/observability/alloy/config.alloy.j2` (or an `alloy_scrape_*` / `alloy_tail_*` toggle) and re-run — **not** `~/.config/alloy/`.

> **Which file does the daemon actually read?** The launch argument lives in the upstream Homebrew formula's plist, which is not vendored here, so the literal path the binary opens cannot be established from this repo. What *is* established from source: `{{ homebrew_prefix }}/etc/grafana-alloy/config.alloy` carries the full pipeline and is the sole render wired to the reload handler, while `~/.config/alloy/` receives a minimal core plus dormant fragments. Treat the Homebrew-prefix file as authoritative; if you need certainty on the running host, read the `ProgramArguments` of `homebrew.mxcl.grafana-alloy.plist`.

## Health Check

- **Endpoint:** `GET /-/ready`
- **Expected:** `200 OK`
- Managed by `brew services` (the plugin loader's `post_compose` health-wait does not cover Alloy, since it is a host service started outside the compose sequence).

## What Alloy forwards

| Signal | Source (collected by Alloy) | Destination |
|--------|-----------------------------|-------------|
| Metrics | host (unix exporter), cAdvisor, exporters (postgres/mysqld/redis/blackbox/qdrant), nginx/php-fpm | Prometheus (remote_write) |
| Logs | Docker container stdout/stderr, nginx/php-fpm/agent logs | Loki (`loki.write`) |
| Traces | OTLP from apps on `:4317`/`:4318` | Tempo (OTLP gRPC `:4327`) |

Which collectors are active is controlled by the `alloy_scrape_*` / `alloy_tail_*` toggles in `default.config.yml`, read by `files/observability/alloy/config.alloy.j2` at render time.

The three composition plugins (`alloy-host-metrics`, `alloy-docker-metrics`, `alloy-syslog`) do **not** control this today. Each is `structure-landed` by its own manifest header: it renders a River fragment to `~/.config/alloy/conf.d/<plugin>.river` and then lies dormant, because activating them needs Alloy launched as `alloy run config.alloy conf.d/` — a launch flag the Homebrew plist does not carry (an explicit Phase-3 TODO in `files/anatomy/plugins/alloy-host-metrics/plugin.yml`). The host-metrics scrape that *is* live comes from the inline block in the Ansible template, not from the plugin.

## Dependencies

- **Prometheus** — metrics remote_write target (`prometheus_port`).
- **Loki** — log write target (`loki_port`).
- **Tempo** — OTLP forward target (`tempo_otlp_grpc_port`).
- **Homebrew** — install + service management (`brew services`).
