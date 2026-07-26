# Loki — Skills

> Callable read-only actions against the native Loki HTTP API. Loopback only (`http://localhost:3100`), unauthenticated (`auth_enabled: false`). No bot account and no SSO — these are the estate's log-store primitives. For a dashboarded, SSO-attributed search use Grafana → Explore → Loki (`../grafana/SKILLS.md`).

## Authentication

- **Method:** none — the API is bound to `127.0.0.1:3100` with no auth.
- **Base URL:** `http://localhost:3100`
- **Reachability:** host-local (or via Tailscale to the host); never the public edge.

---

## query-instant

**Trigger:** "query loki directly", "logql instant query", "grep logs on the host"
**Method:** API
**Endpoint:** `GET /loki/api/v1/query`
**Input:** query params — `query` (LogQL), optional `time`, `limit`, `direction`
**Output:** `{ "status": "success", "data": { "resultType": "streams|vector", "result": [...] } }`

**Example:**
```bash
curl -s --data-urlencode 'query={container="nginx"} |= "error"' 'http://localhost:3100/loki/api/v1/query'
```

---

## query-range

**Trigger:** "logs over a time window", "logql range query", "errors in the last hour"
**Method:** API
**Endpoint:** `GET /loki/api/v1/query_range`
**Input:** query params — `query` (LogQL), `start`, `end` (RFC3339/Unix ns), optional `limit`, `step`, `direction`
**Output:** `{ "status": "success", "data": { "resultType": "streams", "result": [...] } }`

**Example:**
```bash
curl -s --data-urlencode 'query={job="varlogs"}' --data-urlencode 'start=2026-07-26T00:00:00Z' --data-urlencode 'end=2026-07-26T01:00:00Z' 'http://localhost:3100/loki/api/v1/query_range'
```

---

## list-labels

**Trigger:** "what log labels exist", "list loki labels", "which streams are available"
**Method:** API
**Endpoint:** `GET /loki/api/v1/labels`
**Input:** optional `start`, `end`
**Output:** `{ "status": "success", "data": [ "container", "job", "level", ... ] }`

---

## list-label-values

**Trigger:** "values for a log label", "which containers are logging", "list job values in loki"
**Method:** API
**Endpoint:** `GET /loki/api/v1/label/<name>/values` (e.g. `.../label/container/values`)
**Input:** label name in the path; optional `start`, `end`
**Output:** `{ "status": "success", "data": [ "<value>", ... ] }`

---

## check-health

**Trigger:** "is loki ready", "loki readiness"
**Method:** API
**Endpoint:** `GET /ready`
**Input:** none
**Output:** `200 OK` (`ready`)
