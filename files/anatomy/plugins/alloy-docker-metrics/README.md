# alloy-docker-metrics — Phase 3 U12

Composition plugin. Discovers running Docker containers, scrapes
cAdvisor-style metrics into Prometheus, and tails container logs into
Loki — all in one Alloy fragment.

## Status

**Structure landed. Activation pending Phase-3 alloy launch flag.**

Same activation gate as alloy-host-metrics (see that plugin's README).
The fragment lives at `~/.config/alloy/conf.d/docker-metrics.river`
and is dormant until Alloy is launched with multi-file config or the
plugin loader's `compose_river` concatenates it into the master
`config.alloy`.

## What it adds

- `discovery.docker "containers"` — refreshes the target list every 30s.
- `discovery.relabel "containers"` — extracts `container`,
  `compose_project`, `compose_service` labels from Docker metadata.
- `prometheus.exporter.cadvisor "docker"` + `prometheus.scrape "docker"`
  — per-container CPU/mem/net/blkio metrics into Prometheus.
- `loki.source.docker "containers"` — tails stdout/stderr into Loki with
  the relabeled compose-project/service labels attached.

## Verifying activation (post-Phase-3)

Metrics:
```bash
curl -s http://localhost:{{ prometheus_port }}/api/v1/query?query=container_cpu_usage_seconds_total \
  | jq '.data.result | length'
```

Expect: count > 0 (one series per running container per CPU).

Logs (Loki):
```bash
curl -s "http://localhost:{{ loki_port }}/loki/api/v1/labels" \
  | jq '.data | index("compose_project")'
```

Expect: not null (the label is being applied).

## Caveats

- Docker socket path is hardcoded `/var/run/docker.sock`. Docker Desktop
  on Apple Silicon proxies it correctly; rootless Docker installs may
  need an override (operator-level config; not addressed here).
- Container logs may contain GDPR-relevant data — see `gdpr:` block in
  plugin.yml. Operators must redact at the source for any container
  serving end-user traffic.
