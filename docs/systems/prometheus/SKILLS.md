# Prometheus — Skills

> Callable read-only actions against the native Prometheus v3 HTTP API. Loopback only (`http://localhost:9090`), unauthenticated. There is no bot account and no SSO — these are the estate's metrics-store primitives. For a dashboarded, SSO-attributed query use Grafana (`../grafana/SKILLS.md`) instead.

## Authentication

- **Method:** none — the API is bound to `127.0.0.1:9090` with no auth.
- **Base URL:** `http://localhost:9090`
- **Reachability:** host-local (or via Tailscale to the host); never the public edge.

---

## query-instant

**Trigger:** "query prometheus directly", "evaluate promql now", "current value of a metric on the host"
**Method:** API
**Endpoint:** `GET /api/v1/query`
**Input:** query params — `query` (PromQL), optional `time` (RFC3339 or Unix ts, defaults to now)
**Output:** `{ "status": "success", "data": { "resultType": "vector", "result": [...] } }`

**Example:**
```bash
curl -s 'http://localhost:9090/api/v1/query?query=up'
```

---

## query-range

**Trigger:** "promql over a time window", "range query prometheus", "metric trend for the last hour"
**Method:** API
**Endpoint:** `GET /api/v1/query_range`
**Input:** query params — `query` (PromQL), `start`, `end` (RFC3339/Unix), `step` (e.g. `15s`)
**Output:** `{ "status": "success", "data": { "resultType": "matrix", "result": [...] } }`

**Example:**
```bash
curl -s 'http://localhost:9090/api/v1/query_range?query=rate(node_cpu_seconds_total[5m])&start=2026-07-26T00:00:00Z&end=2026-07-26T01:00:00Z&step=60s'
```

---

## list-targets

**Trigger:** "check scrape targets", "which exporters are up", "is prometheus scraping X"
**Method:** API
**Endpoint:** `GET /api/v1/targets`
**Input:** optional `state=active|dropped`
**Output:** `{ "data": { "activeTargets": [ { "scrapeUrl": "...", "health": "up|down", "lastError": "..." } ] } }`

---

## list-rules

**Trigger:** "list recording rules", "show alerting rules", "what rules is prometheus evaluating"
**Method:** API
**Endpoint:** `GET /api/v1/rules`
**Input:** optional `type=alert|record`
**Output:** `{ "data": { "groups": [ { "name": "...", "rules": [...] } ] } }`

---

## list-alerts

**Trigger:** "any firing alerts", "prometheus alert state", "show pending alerts"
**Method:** API
**Endpoint:** `GET /api/v1/alerts`
**Input:** none
**Output:** `{ "data": { "alerts": [ { "labels": {...}, "state": "firing|pending", "activeAt": "..." } ] } }`

---

## list-label-values

**Trigger:** "what jobs exist", "list label values", "which instances are reporting"
**Method:** API
**Endpoint:** `GET /api/v1/label/<name>/values` (e.g. `.../label/job/values`); all names via `GET /api/v1/labels`
**Input:** label name in the path
**Output:** `{ "status": "success", "data": [ "<value>", ... ] }`

---

## check-health

**Trigger:** "is prometheus healthy", "prometheus readiness"
**Method:** API
**Endpoint:** `GET /-/healthy` (liveness), `GET /-/ready` (readiness)
**Input:** none
**Output:** `200 OK`
