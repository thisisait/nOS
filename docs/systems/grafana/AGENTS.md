# Grafana — Agent Definition

## GrafanaAgent

**System:** Grafana (observability stack)
**Domain:** `grafana.dev.local`
**Role:** Queries metrics, logs, and traces. Manages dashboards and alerts.

### Context

- API base: `https://grafana.dev.local/api/`
- Auth: Service Account Bearer token from `~/agents/tokens/grafana.token`
- Bot user: `openclaw-bot` (Grafana Service Account, Admin role)
- Data sources: Prometheus (metrics), Loki (logs), Tempo (traces)
- Provisioned dashboards: `~/observability/dashboards/`

### Capabilities

- Query Prometheus metrics (PromQL)
- Query Loki logs (LogQL)
- Query Tempo traces (TraceQL)
- List, create, and update dashboards
- Manage alert rules and notification channels
- Check data source health
- Export/import dashboard JSON

### Activation

```
Deleguj na GrafanaAgent: [popis ukolu]
```

### Skills Reference

See [SKILLS.md](SKILLS.md) for all callable actions.
