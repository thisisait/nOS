# Alloy — Agent Definition

## AlloyAgent

**System:** Alloy (host-native telemetry collector; taxonomy node `nos.host.alloy`)
**Endpoint:** `http://localhost:12345` (loopback UI, unauthenticated, read-only)
**Role:** Observes the collection pipeline's health and self-metrics. Alloy is a shipper with no external action API — this agent inspects, it does not invoke.

### Context

- UI: `http://localhost:12345` — read-only pipeline inspection (components, graph).
- Self-metrics: `GET /metrics`; readiness: `GET /-/ready`.
- Auth: none — localhost-only, no TLS, no SSO.
- Config is Ansible-owned: the live pipeline renders to `{{ homebrew_prefix }}/etc/grafana-alloy/config.alloy` (default `/opt/homebrew/etc/grafana-alloy/config.alloy`) from `files/observability/alloy/config.alloy.j2`, and only that render notifies the `Restart alloy` handler. The `alloy-base` plugin writes a second, minimal copy to `~/.config/alloy/config.alloy` that reloads nothing — do not send an agent there to "fix the pipeline". Reconfiguration is a playbook run, never an agent action.
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
