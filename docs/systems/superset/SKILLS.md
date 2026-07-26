# Apache Superset — Skills

> Callable actions for Superset. Each skill is API-first using an admin JWT.

## Authentication

- **Method:** Bearer JWT
- **Credentials:** `~/.nos/secrets.yml` (`{global_password_prefix}_pw_superset`). There is
  no persisted token file and no bot account — the JWT is minted per session.
- **Base URL:** `https://superset.dev.local` (loopback: `http://127.0.0.1:8089`)
- **Header:** `Authorization: Bearer <jwt>`
- **Token mint / refresh:** `POST /api/v1/security/login` with
  `{ "username": "admin", "password": "...", "provider": "db" }`

---

## list-charts

**Trigger:** "list charts", "show visualizations", "what charts exist"
**Method:** API
**Endpoint:** `GET /api/v1/chart/`
**Input:** Query params: `q` (optional, RISON-encoded filter)
**Output:** `{ "count": 5, "result": [{ "id": 1, "slice_name": "...", "viz_type": "...", "datasource_name_text": "..." }] }`

---

## execute-query

**Trigger:** "run SQL query", "query database", "execute SQL"
**Method:** API
**Endpoint:** `POST /api/v1/sqllab/execute/`
**Input:**
```json
{
  "database_id": 1,
  "sql": "<SQL query>",
  "schema": "public",
  "runAsync": false
}
```
**Output:** `{ "data": [...], "columns": [...], "status": "success" }`

---

## list-dashboards

**Trigger:** "list dashboards", "show dashboards", "what dashboards exist"
**Method:** API
**Endpoint:** `GET /api/v1/dashboard/`
**Input:** Query params: `q` (optional, RISON-encoded filter)
**Output:** `{ "count": 3, "result": [{ "id": 1, "dashboard_title": "...", "url": "...", "status": "published" }] }`

---

## list-databases

**Trigger:** "list databases", "show data sources", "what databases are connected"
**Method:** API
**Endpoint:** `GET /api/v1/database/`
**Input:** None
**Output:** `{ "count": 2, "result": [{ "id": 1, "database_name": "...", "backend": "postgresql", "sqlalchemy_uri": "..." }] }`
