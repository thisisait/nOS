# Grafana — Agent Definition

## GrafanaAgent

**System:** Grafana (observability stack)
**Domain:** `grafana.dev.local`
**Role:** Queries metrics, logs, and traces. Manages dashboards and alerts.

### Context

- API base: `https://grafana.dev.local/api/` (loopback: `http://127.0.0.1:3000/api/`)
- Auth: Service Account Bearer token from
  `~/nos/platform/services/mcpo/data/.grafana_sa_token` (`{{ mcpo_data_dir }}`)
- Service account: `mcp-gateway` (Grafana Service Account, **Viewer** role — read-only;
  writes below need admin basic auth). Created by `roles/pazny.mcp_gateway/tasks/post.yml`.
  There is no `openclaw-bot` account.
- Data sources: Prometheus (metrics), Loki (logs), Tempo (traces), Wing SQLite (playbook
  + agent telemetry)
- Provisioned dashboards: `~/observability/dashboards/`

### Capabilities

- Query Prometheus metrics (PromQL)
- Query Loki logs (LogQL)
- Query Tempo traces (TraceQL)
- Query the Wing SQLite datasource (playbook events, agent sessions)
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
