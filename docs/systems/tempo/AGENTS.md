# Tempo — Agent Definition

## TempoAgent

**System:** Tempo (observability stack — trace backend)
**Endpoint:** `http://localhost:3200` (loopback, unauthenticated)
**Role:** Fetches traces by ID and runs TraceQL searches directly against the local Tempo query API.

> **Roster note.** `TempoAgent` is a *per-system* definition, not a member of the closed ten-persona OpenClaw roster in `files/openclaw/AGENTS.md` — that roster assigns Tempo (with Grafana, Prometheus and Loki) to **`GrafanaAgent`**. Delegate with `Delegate to GrafanaAgent: …`; this page is the system-scoped API contract that persona reads.

### Context

- API base: `http://localhost:3200/api/`
- Auth: none — port bound to `127.0.0.1`; no token, no login, no SSO.
- No admin account, no service account, no bot user (this is a datastore).
- Ingest path: apps send OTLP to Alloy (`:4317`/`:4318`); Alloy forwards spans to Tempo's OTLP receiver (`:4327`/`:4328`). Agents do not push spans here directly.
- The SSO-gated, dashboarded exploration path is Grafana → Explore → Tempo — prefer `../grafana/` for visualized trace lookups; use this direct API for scripted/agentic checks on the host.

### Capabilities

- Fetch a full trace by trace ID.
- Search for traces by TraceQL or tag selectors.
- Discover searchable span tag names and values.
- Check Tempo readiness.

### Constraints

- Read-only. Ingestion is OTLP-only and belongs to Alloy.
- Do not query `/status/config` (REM-036, accepted-risk — deliberately omitted).
- Loopback only — reachable from the host (or over Tailscale), never from the public edge.

### Skills Reference

See [SKILLS.md](SKILLS.md) for all callable actions.
