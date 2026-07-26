# Grafana — Skills

> Callable actions for Grafana. Each skill is API-first using the `mcp-gateway` service
> account (the only one nOS provisions).

## Authentication

- **Method:** Bearer token (Grafana Service Account)
- **Token:** `~/nos/platform/services/mcpo/data/.grafana_sa_token` (`{{ mcpo_data_dir }}`)
- **Service account:** `mcp-gateway`, role **Viewer**
- **Base URL:** `https://grafana.dev.local` (loopback: `http://127.0.0.1:3000`)
- **Header:** `Authorization: Bearer <token>`

> **Read-only ceiling.** The provisioned token is a **Viewer**. The query / list / get
> skills below work with it; `create-alert-rule` and `create-service-account` are write
> operations and need admin HTTP basic auth (`admin` + `grafana_admin_password`) over
> loopback — which is exactly how the playbook does them.

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

**Trigger:** (internal — this is what `roles/pazny.mcp_gateway/tasks/post.yml` runs)
**Method:** API (admin basic auth over loopback, not the SA token)
**Endpoint:** `POST /api/serviceaccounts`
**Input:** `{ "name": "mcp-gateway", "role": "Viewer", "isDisabled": false }`
**Output:** `{ "id": 1, "name": "mcp-gateway" }` (accepts `400`/`409` = already exists,
then re-reads via `GET /api/serviceaccounts/search?query=mcp-gateway`)

**Token creation:**
```
POST /api/serviceaccounts/<id>/tokens
{ "name": "mcpo-token-<epoch>" }
→ { "key": "<bearer-token>" }
```
The key is written to `{{ mcpo_data_dir }}/.grafana_sa_token` (mode `0600`) so a compose
restart keeps working.
