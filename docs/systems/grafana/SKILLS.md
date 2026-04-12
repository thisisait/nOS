# Grafana — Skills

> Callable actions for Grafana. Each skill is API-first using `openclaw-bot` service account.

## Authentication

- **Method:** Bearer token (Grafana Service Account)
- **Token:** `~/agents/tokens/grafana.token`
- **Base URL:** `https://grafana.dev.local`
- **Header:** `Authorization: Bearer <token>`

---

## query-prometheus

**Trigger:** "query metrics", "check CPU/memory/disk", "how is [service] performing"
**Method:** API
**Endpoint:** `POST /api/ds/query`
**Input:**
```json
{
  "queries": [{
    "datasource": {"type": "prometheus", "uid": "<uid>"},
    "expr": "<PromQL expression>",
    "refId": "A",
    "instant": true
  }],
  "from": "now-1h",
  "to": "now"
}
```
**Output:** Time-series data `{ results: { A: { frames: [...] } } }`

**Example:**
```
"Check nginx request rate in the last hour"
POST /api/ds/query
expr: rate(nginx_http_requests_total[5m])
```

---

## query-loki

**Trigger:** "check logs", "search logs for errors", "show nginx 5xx"
**Method:** API
**Endpoint:** `POST /api/ds/query`
**Input:**
```json
{
  "queries": [{
    "datasource": {"type": "loki", "uid": "<uid>"},
    "expr": "<LogQL expression>",
    "refId": "A"
  }],
  "from": "now-1h",
  "to": "now"
}
```
**Output:** Log lines `{ results: { A: { frames: [...] } } }`

**Example:**
```
"Show nginx 5xx errors in the last hour"
expr: {job="nginx"} |= "HTTP/1" | pattern `<_> <_> <_> <status> <_>` | status >= 500
```

---

## query-tempo

**Trigger:** "find traces", "trace request", "show slow requests"
**Method:** API
**Endpoint:** `POST /api/ds/query`
**Input:**
```json
{
  "queries": [{
    "datasource": {"type": "tempo", "uid": "<uid>"},
    "query": "<TraceQL expression>",
    "refId": "A"
  }],
  "from": "now-1h",
  "to": "now"
}
```
**Output:** Trace spans

---

## list-dashboards

**Trigger:** "list dashboards", "show available dashboards", "find dashboard"
**Method:** API
**Endpoint:** `GET /api/search?type=dash-db`
**Input:** Query params: `query` (optional search string)
**Output:** `[{ "id": 1, "uid": "abc", "title": "...", "url": "..." }]`

---

## get-dashboard

**Trigger:** "show dashboard [name]", "get dashboard details"
**Method:** API
**Endpoint:** `GET /api/dashboards/uid/<uid>`
**Input:** Dashboard UID
**Output:** Full dashboard JSON model

---

## create-alert-rule

**Trigger:** "create alert", "alert me when", "set up monitoring for"
**Method:** API
**Endpoint:** `POST /api/v1/provisioning/alert-rules`
**Input:** Alert rule JSON (title, condition, folder, evaluation group)
**Output:** Created alert rule with UID

---

## list-alerts

**Trigger:** "show alerts", "any firing alerts", "check alert status"
**Method:** API
**Endpoint:** `GET /api/v1/provisioning/alert-rules`
**Input:** None
**Output:** `[{ "uid": "...", "title": "...", "condition": "...", "state": "..." }]`

---

## check-datasource-health

**Trigger:** "is Prometheus running", "check Loki health", "data source status"
**Method:** API
**Endpoint:** `GET /api/datasources/uid/<uid>/health`
**Input:** Data source UID
**Output:** `{ "status": "OK", "message": "..." }`

---

## list-datasources

**Trigger:** "show data sources", "list backends"
**Method:** API
**Endpoint:** `GET /api/datasources`
**Input:** None
**Output:** `[{ "id": 1, "uid": "...", "name": "...", "type": "...", "url": "..." }]`

---

## create-service-account

**Trigger:** (internal — used by playbook for openclaw-bot setup)
**Method:** API
**Endpoint:** `POST /api/serviceaccounts`
**Input:** `{ "name": "openclaw-bot", "role": "Admin" }`
**Output:** `{ "id": 1, "name": "openclaw-bot" }`

**Token creation:**
```
POST /api/serviceaccounts/<id>/tokens
{ "name": "openclaw-token" }
→ { "key": "<bearer-token>" }
```
