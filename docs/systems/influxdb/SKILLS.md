# InfluxDB — Skills

> Callable actions for InfluxDB 2.x. All skills are HTTP API against the
> loopback port `http://127.0.0.1:8086` (which bypasses the Authentik proxy
> gate) and authenticate with the native InfluxDB token.

## Authentication

- **Method:** InfluxDB token
- **Header:** `Authorization: Token <influxdb_admin_token>`
- **Base URL:** `http://127.0.0.1:8086`
- **Org:** `nos`

---

## write-points

**Trigger:** "write a measurement", "push time-series data", "record a metric to InfluxDB"
**Method:** API
**Endpoint:** `POST /api/v2/write?org=nos&bucket=default&precision=ns`
**Input:** line-protocol body, e.g.

```
cpu,host=mac-studio usage=42.1 1700000000000000000
```

**Output:** `204 No Content` on success.

---

## query-flux

**Trigger:** "query InfluxDB", "run a Flux query", "read time-series data"
**Method:** API
**Endpoint:** `POST /api/v2/query?org=nos`
**Input:** header `Content-Type: application/vnd.flux` (or `application/json`),
Flux body:

```flux
from(bucket: "default")
  |> range(start: -1h)
  |> filter(fn: (r) => r._measurement == "cpu")
```

**Output:** annotated CSV (`Accept: application/csv`).

---

## list-buckets

**Trigger:** "list InfluxDB buckets", "what buckets exist"
**Method:** API
**Endpoint:** `GET /api/v2/buckets`
**Input:** optional `?org=nos`
**Output:** `{ "buckets": [{ "id": "...", "name": "default", "retentionRules": [...] }] }`

---

## create-bucket

**Trigger:** "create an InfluxDB bucket", "add a new bucket"
**Method:** API
**Endpoint:** `POST /api/v2/buckets`
**Input:**

```json
{ "orgID": "<org-id>", "name": "myapp", "retentionRules": [{ "type": "expire", "everySeconds": 7776000 }] }
```

**Output:** created bucket JSON with `id`.

---

## list-orgs

**Trigger:** "list InfluxDB orgs", "get the org id"
**Method:** API
**Endpoint:** `GET /api/v2/orgs`
**Input:** optional `?org=nos`
**Output:** `{ "orgs": [{ "id": "...", "name": "nos" }] }` — use `id` as `orgID` elsewhere.

---

## check-health

**Trigger:** "is InfluxDB up", "check InfluxDB health"
**Method:** API
**Endpoint:** `GET /health`
**Input:** none (no auth required)
**Output:** `{ "name": "influxdb", "status": "pass", "version": "2.7.12" }`
