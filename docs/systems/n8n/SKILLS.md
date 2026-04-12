# n8n — Skills

> Callable actions for n8n. API-first using API key.

## Authentication

- **Method:** API Key (header `X-N8N-API-KEY`)
- **Token:** `~/agents/tokens/n8n.token`
- **Base URL:** `https://n8n.dev.local`

---

## list-workflows

**Trigger:** "list workflows", "show automations", "what workflows exist"
**Method:** API
**Endpoint:** `GET /api/v1/workflows`
**Input:** Query params: `active` (true/false), `limit`, `cursor`
**Output:** `{ "data": [{ "id": "1", "name": "...", "active": true, "nodes": [...] }] }`

---

## execute-workflow

**Trigger:** "run workflow [name]", "trigger automation", "execute [workflow]"
**Method:** API
**Endpoint:** `POST /api/v1/workflows/{id}/execute`
**Input:** `{ "data": { "key": "value" } }` (optional trigger data)
**Output:** `{ "data": { "executionId": "...", "status": "..." } }`

---

## activate-workflow

**Trigger:** "enable workflow", "activate [name]", "turn on automation"
**Method:** API
**Endpoint:** `PATCH /api/v1/workflows/{id}`
**Input:** `{ "active": true }`
**Output:** Updated workflow object

---

## list-executions

**Trigger:** "show execution history", "what ran recently", "check workflow results"
**Method:** API
**Endpoint:** `GET /api/v1/executions`
**Input:** Query params: `workflowId`, `status` (success/error/waiting), `limit`
**Output:** `{ "data": [{ "id": "...", "workflowId": "...", "status": "...", "startedAt": "..." }] }`

---

## create-workflow

**Trigger:** "create workflow", "new automation for [task]"
**Method:** API
**Endpoint:** `POST /api/v1/workflows`
**Input:** Workflow JSON with nodes and connections
**Output:** Created workflow object with ID

---

## list-credentials

**Trigger:** "show credentials", "what integrations are configured"
**Method:** API
**Endpoint:** `GET /api/v1/credentials`
**Input:** None
**Output:** `{ "data": [{ "id": "1", "name": "...", "type": "..." }] }`
