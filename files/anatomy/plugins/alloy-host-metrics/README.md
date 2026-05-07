# alloy-host-metrics — Phase 3 U11

Composition plugin. Scrapes host-level metrics (CPU, mem, disk, net) via
`prometheus.exporter.unix` and forwards to the alloy-base
`prometheus.remote_write.default` sink → Prometheus → Grafana.

## Status

**Structure landed. Activation pending Phase-3 alloy launch flag.**

The River fragment renders to
`~/.config/alloy/conf.d/host-metrics.river`. Alloy itself does not
auto-scan that directory yet — the launchd plist/`brew services`
invocation passes a single `config.alloy` file. Two ways forward:

1. Plugin-loader `compose_river` action concatenates `conf.d/*.river` into
   `config.alloy` at render time (alloy-base/README.md spec).
2. `pazny.alloy` thin role launches Alloy with `alloy run ~/.config/alloy/`
   instead of `… config.alloy`. Multi-file config is a stable feature
   in Alloy 1.x — operator just changes the launchd `ProgramArguments`.

Either path unlocks U11+U12+U13 simultaneously.

## What it adds

- `prometheus.exporter.unix "host"` — runs Alloy's built-in node-exporter
  equivalent.
- `prometheus.scrape "host"` — scrapes that exporter every 15s and forwards
  to `prometheus.remote_write.default.receiver`.

## Verifying activation (post-Phase-3)

```bash
curl -s http://localhost:{{ prometheus_port }}/api/v1/targets \
  | jq '.data.activeTargets[] | select(.labels.job=="host") | {url:.scrapeUrl, health}'
```

Expect: one target up, scraping `127.0.0.1:9100` (or whatever port
`prometheus.exporter.unix` chose).

## Why not a service plugin?

The exporter isn't a separate process — it lives inside the Alloy
process. Composition plugins are the right shape: zero new container,
zero new daemon, just structural wiring between two existing peers.
