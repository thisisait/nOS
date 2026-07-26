# Alloy — Agent Definition

## AlloyAgent

**System:** Alloy (host-native telemetry collector; taxonomy node `nos.host.alloy`)
**Endpoint:** `http://localhost:12345` (loopback UI, unauthenticated, read-only)
**Role:** Observes the collection pipeline's health and self-metrics. Alloy is a shipper with no external action API — this agent inspects, it does not invoke.

### Context

- UI: `http://localhost:12345` — read-only pipeline inspection (components, graph).
- Self-metrics: `GET /metrics`; readiness: `GET /-/ready`.
- Auth: none — localhost-only, no TLS, no SSO.
- Config is Ansible-owned (`~/.config/alloy/config.alloy`); it is reloaded by the playbook via `brew services restart alloy`, never by an agent.
- Alloy forwards metrics → Prometheus, logs → Loki, traces → Tempo. To *query* those signals, use the backend agents (`../prometheus/`, `../loki/`, `../tempo/`) or Grafana, not Alloy.

### Capabilities

- Confirm Alloy is up and ready (`/-/ready`).
- Read Alloy's own scrape/forward self-metrics (`/metrics`).
- Inspect the running component graph via the loopback UI.

### Constraints

- No mutation surface: pipeline changes go through the playbook, not the agent.
- Loopback only — reachable from the host (or over Tailscale), never from the public edge.

### Skills Reference

See [SKILLS.md](SKILLS.md) — Alloy has no external skill surface; that file explains why.
