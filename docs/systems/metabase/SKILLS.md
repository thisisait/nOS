# Metabase — Skills

> Callable actions for Metabase. API-first using session token.

## Authentication

- **Method:** Session token (header `X-Metabase-Session`)
- **Obtain:** `POST /api/session` with `{ "username": "...", "password": "..." }`
- **Token:** `~/agents/tokens/metabase.token`
- **Base URL:** `https://bi.dev.local`

---

## run-query

**Trigger:** "run SQL query", "query database", "show data from [table]"
**Method:** API
**Endpoint:** `POST /api/dataset`
**Input:**
```json
{
  "database": 1,
  "type": "native",
  "native": { "query": "SELECT * FROM table LIMIT 10" }
}
```
**Output:** `{ "data": { "rows": [...], "cols": [...] } }`

---

## list-questions

**Trigger:** "show saved questions", "list reports"
**Method:** API
**Endpoint:** `GET /api/card`
**Input:** None
**Output:** `[{ "id": 1, "name": "...", "display": "table", "collection_id": ... }]`

---

## run-saved-question

**Trigger:** "run [question name]", "execute report"
**Method:** API
**Endpoint:** `POST /api/card/{id}/query`
**Input:** Card ID
**Output:** `{ "data": { "rows": [...], "cols": [...] } }`

---

## list-dashboards

**Trigger:** "show dashboards", "list BI dashboards"
**Method:** API
**Endpoint:** `GET /api/dashboard`
**Input:** None
**Output:** `[{ "id": 1, "name": "...", "description": "..." }]`

---

## list-databases

**Trigger:** "show connected databases", "what data sources"
**Method:** API
**Endpoint:** `GET /api/database`
**Input:** None
**Output:** `{ "data": [{ "id": 1, "name": "...", "engine": "postgres" }] }`

---

## get-table-metadata

**Trigger:** "show table schema", "what columns in [table]"
**Method:** API
**Endpoint:** `GET /api/table/{id}/query_metadata`
**Input:** Table ID
**Output:** Table metadata with fields, types, foreign keys
