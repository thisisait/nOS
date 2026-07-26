# InfluxDB — Agent Definition

## InfluxDBAgent

**System:** InfluxDB 2.x (time-series database, taxonomy anchor `nos.data.influxdb`)
**Domain:** `influxdb.<tenant_domain>` (local default `influxdb.dev.local`)
**Role:** Writes and queries time-series measurements. Manages buckets and retention.

### Context

- API base: `http://127.0.0.1:8086` (loopback — bypasses the Authentik `forward_auth` proxy gate)
- Auth: InfluxDB token via `Authorization: Token <influxdb_admin_token>` (NOT `Bearer`)
- Org: `nos` · initial bucket: `default` (90d retention)
- Data at rest: `{{ nos_data_root }}/platform/services/influxdb/data`
- No native OIDC — the web UI is gated by Authentik at the proxy; the API uses the InfluxDB token.

### Capabilities

- Write points in line protocol (`POST /api/v2/write`)
- Query with Flux (`POST /api/v2/query`)
- List and create buckets (`/api/v2/buckets`)
- Resolve the org id (`/api/v2/orgs`)
- Check node health (`GET /health`)

### Caveats

- The admin token is applied only on first-run init; a re-rendered token does not rotate the live one. Read the live token before calling the API.

### Skills Reference

See [SKILLS.md](SKILLS.md) for all callable actions.
