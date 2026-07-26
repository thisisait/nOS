# Tempo — Skills

> Callable read-only actions against the native Tempo query API. Loopback only (`http://localhost:3200`), unauthenticated. No bot account and no SSO — these are the estate's trace-store primitives. For a dashboarded, SSO-attributed trace view use Grafana → Explore → Tempo (`../grafana/SKILLS.md`).

## Authentication

- **Method:** none — the API is bound to `127.0.0.1:3200` with no auth.
- **Base URL:** `http://localhost:3200`
- **Reachability:** host-local (or via Tailscale to the host); never the public edge.

---

## get-trace

**Trigger:** "fetch trace by id", "show trace <id>", "pull the full span tree for a trace"
**Method:** API
**Endpoint:** `GET /api/traces/<traceID>`
**Input:** trace ID (hex) in the path
**Output:** the full trace (OTLP/JSON batches of spans)

**Example:**
```bash
curl -s 'http://localhost:3200/api/traces/6f3a1c9e0b7d4a25'
```

---

## search-traceql

**Trigger:** "search traces", "traceql query", "find slow requests", "traces for service X"
**Method:** API
**Endpoint:** `GET /api/search`
**Input:** query params — `q` (TraceQL) OR `tags` (logfmt tag selectors); optional `start`, `end`, `limit`
**Output:** `{ "traces": [ { "traceID": "...", "rootServiceName": "...", "durationMs": ... } ] }`

**Example:**
```bash
curl -s --data-urlencode 'q={ duration > 500ms }' 'http://localhost:3200/api/search'
```

---

## list-tag-names

**Trigger:** "what span tags exist", "list searchable tempo tags"
**Method:** API
**Endpoint:** `GET /api/search/tags`
**Input:** none
**Output:** `{ "tagNames": [ "service.name", "http.status_code", ... ] }`

---

## list-tag-values

**Trigger:** "values for a span tag", "which services have traces"
**Method:** API
**Endpoint:** `GET /api/search/tag/<tag>/values` (e.g. `.../tag/service.name/values`)
**Input:** tag name in the path
**Output:** `{ "tagValues": [ "<value>", ... ] }`

---

## check-health

**Trigger:** "is tempo ready", "tempo readiness"
**Method:** API
**Endpoint:** `GET /ready`
**Input:** none
**Output:** `200 OK` (`ready`)
