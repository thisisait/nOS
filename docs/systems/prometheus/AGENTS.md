# Prometheus — Agent Definition

## PrometheusAgent

**System:** Prometheus (observability stack — metrics backend)
**Endpoint:** `http://localhost:9090` (loopback, unauthenticated)
**Role:** Runs read-only PromQL queries and inspects scrape/alert state directly against the local Prometheus HTTP API.

### Context

- API base: `http://localhost:9090/api/v1/`
- Auth: none — the port is bound to `127.0.0.1`; there is no token, no login, no SSO.
- No admin account, no service account, no bot user (this is a datastore).
- Ingest path: Alloy remote-writes metrics in; Prometheus also scrapes exporters listed in `prometheus.yml`.
- The SSO-gated, dashboarded query path is Grafana — prefer `../grafana/` when a query should be attributed or visualized; use this direct API for scripted/agentic checks on the host.

### Capabilities

- Run instant and range PromQL queries.
- List scrape targets and their up/down health.
- List recording + alerting rules and currently firing alerts.
- Enumerate label names and values.

### Constraints

- Read-only. Config reload via API is disabled (no `--web.enable-lifecycle`); config changes go through the playbook.
- Loopback only — reachable from the host (or over Tailscale), never from the public edge.

### Skills Reference

See [SKILLS.md](SKILLS.md) for all callable actions.
