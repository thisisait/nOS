# Loki — Agent Definition

## LokiAgent

**System:** Loki (observability stack — log backend)
**Endpoint:** `http://localhost:3100` (loopback, unauthenticated)
**Role:** Runs read-only LogQL queries and introspects log labels directly against the local Loki HTTP API.

> **Roster note.** `LokiAgent` is a *per-system* definition, not a member of the closed ten-persona OpenClaw roster in `files/openclaw/AGENTS.md` — that roster assigns Loki (with Grafana, Prometheus and Tempo) to **`GrafanaAgent`**. Delegate with `Delegate to GrafanaAgent: …`; this page is the system-scoped API contract that persona reads.

### Context

- API base: `http://localhost:3100/loki/api/v1/`
- Auth: none — `auth_enabled: false`, port bound to `127.0.0.1`; no token, no login, no SSO.
- No admin account, no service account, no bot user (this is a datastore).
- Ingest path: Alloy tails logs and pushes them in; agents do not write logs here directly.
- The SSO-gated, dashboarded search path is Grafana → Explore → Loki — prefer `../grafana/` when a query should be attributed or visualized; use this direct API for scripted/agentic checks on the host.

### Capabilities

- Run instant and range LogQL queries over ingested log streams.
- Enumerate label names and their values (to discover available streams).
- Check Loki readiness.

### Constraints

- Read-only from the agent's side; ingestion belongs to Alloy.
- Loopback only — reachable from the host (or over Tailscale), never from the public edge.

### Skills Reference

See [SKILLS.md](SKILLS.md) for all callable actions.
