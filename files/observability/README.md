# `files/observability/` — LGTM stack source-of-truth

Config templates and static files for Grafana / Loki / Tempo / Prometheus
and Grafana Alloy. Rendered / copied into `{{ stacks_dir }}/observability/`
by `tasks/stacks/core-up.yml`, then bind-mounted into the containers.

Host-side Grafana Alloy (`grafana-alloy` via Homebrew) reads its config
from `{{ homebrew_prefix }}/etc/grafana-alloy/config.alloy` — that file is
rendered from `alloy/config.alloy.j2` by `tasks/observability.yml`.

## Layout

| Path | Purpose | Container |
|---|---|---|
| `alloy/config.alloy.j2` | Alloy pipelines — metrics scrape, log tail, OTLP receive | host-side `grafana-alloy` |
| `prometheus/prometheus.yml` | Prometheus scrape config (owned by A2 for probe targets) | `prom/prometheus` |
| `prometheus/rules/` | Recording + alerting rules (owned by A2) | `prom/prometheus` |
| `loki/local-config.yaml` | Loki single-binary config | `grafana/loki` |
| `tempo/tempo.yaml` | Tempo traces backend | `grafana/tempo` |
| `grafana/provisioning/` | Grafana datasources + dashboard providers | `grafana/grafana` |
| `blackbox/config.yml` | Blackbox-exporter probe module definitions | `prom/blackbox-exporter` |

## What Alloy scrapes (as of Sprint 1 Wave 1)

Alloy runs on the macOS host (outside Docker) and scrapes `localhost:<port>`
endpoints. Each scrape block is gated by a boolean in `default.config.yml`
(listed below in the "toggle" column).

### Metrics → Prometheus (`prometheus.remote_write "default"`)

| Source | Port | Job name | Toggle |
|---|---|---|---|
| `prometheus.exporter.unix` (built-in node-exporter) | n/a | `integrations/node_exporter` | always on |
| `nginx-prometheus-exporter` | `9113` | `nginx` | `alloy_scrape_nginx` |
| `php-fpm_exporter` | `phpfpm_exporter_port` (9253) | `phpfpm` | `alloy_scrape_phpfpm` |
| `prometheus.exporter.redis` (Homebrew Redis) | n/a | `redis` | `alloy_scrape_redis` |
| **NEW** `postgres-exporter` container | `postgres_exporter_port` (9187) | `postgres-exporter` | `alloy_scrape_postgres_exporter` (defaults to `install_postgresql`) |
| **NEW** `mysqld-exporter` container | `mysqld_exporter_port` (9104) | `mysqld-exporter` | `alloy_scrape_mysqld_exporter` (defaults to `install_mariadb`) |
| **NEW** `redis-exporter` container (Dockerized Redis only) | `redis_exporter_port` (9121) | `redis-exporter` | `alloy_scrape_redis_exporter` (defaults to `redis_docker`) |
| **NEW** `cAdvisor` — per-container metrics | `cadvisor_port` (8080) | `cadvisor` | `alloy_scrape_cadvisor` |
| **NEW** `blackbox-exporter` self-metrics | `blackbox_exporter_port` (9115) | `blackbox-exporter` | `alloy_scrape_blackbox_self` |
| Alloy self-metrics | `alloy_ui_port` (12345) | `alloy` | always on |
| Miniflux (if installed) | `miniflux_port` | `miniflux` | `install_miniflux` |
| Firefly III (if installed) | `firefly_port` | `firefly` | `install_firefly` |
| InfluxDB (if installed) | `influxdb_port` | `influxdb` | `install_influxdb` |

Probe scrapes (blackbox `http_2xx` / `tcp_connect` against service URL lists)
are **not** configured in Alloy — they live in Prometheus scrape configs
(`files/observability/prometheus/prometheus.yml`, owned by agent A2).

### Logs → Loki (`loki.write "default"`)

| Source | Path | Toggle |
|---|---|---|
| Nginx access (regex-parsed for method/status labels) | `{{ homebrew_prefix }}/var/log/nginx/*.access.log` | `alloy_tail_nginx_logs` |
| Nginx error | `{{ homebrew_prefix }}/var/log/nginx/*.error.log` | `alloy_tail_nginx_logs` |
| OpenClaw agent `.md` logs | `~/agents/log/*.md` | `alloy_tail_agent_logs` |
| PHP-FPM | `{{ homebrew_prefix }}/var/log/php@<ver>-fpm.log` | `alloy_tail_php_logs` |
| Homebrew services | `{{ homebrew_prefix }}/var/log/*.log` | always on |
| **NEW** All Docker container stdout/stderr (via Docker socket) | `unix:///var/run/docker.sock` | `alloy_tail_docker_logs` |

Docker logs are labelled with `stack` (compose project), `service` (compose
service name), `container` (container name), and `stream` (stdout/stderr) —
so Grafana queries like `{stack="iiab", service="nextcloud"}` Just Work.

### Traces → Tempo

OTLP receiver on `alloy_otlp_grpc_port` (4317) + `alloy_otlp_http_port` (4318),
forwarded to Tempo on `tempo_otlp_grpc_port` (4327). Gated by
`alloy_receive_otlp`.

## Exporter containers (observability stack)

Added in Sprint 1 Wave 1 to the `pazny.grafana` role override — they all
ship under `docker compose -p observability`.

| Service | Image | Networks | Depends on |
|---|---|---|---|
| `postgres-exporter` | `prometheuscommunity/postgres-exporter:v0.15.0` | `observability_net`, `stacks_shared_network` | `postgresql` (infra stack) |
| `mysqld-exporter` | `prom/mysqld-exporter:v0.15.1` | `observability_net`, `stacks_shared_network` | `mariadb` (infra stack) + `mysqld_exporter` MariaDB user |
| `redis-exporter` | `oliver006/redis_exporter:v1.58.0` | `observability_net`, `stacks_shared_network` | `redis` (infra stack, Dockerized only) |
| `cadvisor` | `gcr.io/cadvisor/cadvisor:v0.49.1` | `observability_net`, `stacks_shared_network` | Docker socket (`/var/run/docker.sock`) |
| `blackbox-exporter` | `prom/blackbox-exporter:v0.25.0` | `observability_net`, `stacks_shared_network` | `blackbox/config.yml` bind-mount |

Exporters that need to reach infra databases ride the external
`stacks_shared_network` (not `infra_net`, which is a per-project bridge
scoped to the `infra` compose project). Every infra service
(`mariadb`, `postgresql`, `redis`) advertises itself on
`stacks_shared_network` for exactly this cross-stack case.

### MariaDB exporter user

`mariadb_users` in `default.config.yml` now seeds a
`mysqld_exporter`@`%` user with
`PROCESS, REPLICATION CLIENT, SELECT` on `*.*`. Password defaults to
`{{ global_password_prefix }}_pw_mysqld_exporter` (override with
`mysqld_exporter_password` in `credentials.yml`).

## Blackbox modules (`blackbox/config.yml`)

Module definitions only — not probe targets. Agent A2 wires the actual
probe scrapes in the Prometheus config by passing `module=<name>` and
`target=<url>` as URL parameters.

| Module | Prober | Purpose |
|---|---|---|
| `http_2xx` | http | Generic "site returns 2xx" check, HTTP or HTTPS, self-signed OK |
| `http_post_2xx` | http | Same but POST |
| `https_2xx` | http | Strict HTTPS (fails if not TLS) with cert-expiry metrics |
| `tcp_connect` | tcp | Bare TCP open — for SMTP, SIP, DB ports, etc. |
| `icmp` | icmp | Ping (requires `CAP_NET_RAW`; not enabled by default) |
| `dns_a` | dns | DNS A-record lookup |

## Toggles in `default.config.yml`

```yaml
# Alloy toggles
alloy_scrape_nginx: true
alloy_scrape_phpfpm: true
alloy_scrape_redis: true
alloy_scrape_postgres_exporter: "{{ install_postgresql | default(false) }}"
alloy_scrape_mysqld_exporter:   "{{ install_mariadb   | default(false) }}"
alloy_scrape_redis_exporter:    "{{ redis_docker      | default(false) }}"
alloy_scrape_cadvisor: true
alloy_scrape_blackbox_self: true
alloy_tail_nginx_logs: true
alloy_tail_agent_logs: true
alloy_tail_php_logs: true
alloy_tail_docker_logs: true
alloy_receive_otlp: true

# Exporter ports
postgres_exporter_port: 9187
mysqld_exporter_port:   9104
redis_exporter_port:    9121
cadvisor_port:          8080
blackbox_exporter_port: 9115
```
