# n8n — Skills

> Callable actions for n8n's public REST API. The credential mechanism is real but is
> **not provisioned by nOS** — read Authentication first. Three cards are flagged as
> unverified rather than silently deleted.

## Authentication

- **Method:** API key header `X-N8N-API-KEY` — human-minted, NOT provisioned by nOS
- **Where the key comes from:** a human creates it in the n8n UI (Settings → n8n API).
  The playbook does not mint, store, or inject one.
- **No service account.** `openclaw-bot` does not exist; nothing in the repo creates an
  n8n user beyond the owner account.
- **No token file.** `~/agents/tokens/n8n.token` does not exist — no task writes it, no
  code reads it, and the directory is not provisioned anywhere in nOS.
- **The only playbook-managed credential** is the OWNER account created by
  `roles/pazny.n8n/tasks/post.yml` via `POST /api/v1/owner/setup`:
  `{{ n8n_admin_email }}` (default `admin@{tenant_domain}`) /
  `{global_password_prefix}_pw_n8n`. That is an operator login, not an agent identity.
- **Base URL:** `https://{n8n_domain}` (default `https://n8n.dev.local`), or
  `http://127.0.0.1:5678` from the host (loopback publish; peer containers cannot reach
  it).
- **Outbound caveat:** `N8N_SSRF_PROTECTION_ENABLED` is ON, so workflows cannot call
  RFC-1918/loopback peers unless allowlisted.

## Endpoints verified against repo source

Only these are exercised by nOS itself (`roles/pazny.n8n/tasks/post.yml`): `GET /healthz`,
`GET /api/v1/owner`, `POST /api/v1/owner/setup`, `POST /rest/login`,
`POST /rest/change-password`. Everything below is upstream surface.

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
**Status:** FLAGGED — likely dead endpoint. No repo source calls it, and n8n's public API is not known to expose a synchronous execute route (workflows fire from their own trigger/webhook nodes). Verify against the instance's `/api/v1/docs` before depending on it.

---

## activate-workflow

**Trigger:** "enable workflow", "activate [name]", "turn on automation"
**Method:** API
**Endpoint:** `PATCH /api/v1/workflows/{id}`
**Input:** `{ "active": true }`
**Output:** Updated workflow object
**Status:** FLAGGED — method/route unverified. No repo source calls it; upstream n8n exposes dedicated `POST /api/v1/workflows/{id}/activate` and `.../deactivate` routes and uses `PUT` for whole-workflow updates. Verify before use.

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
**Status:** FLAGGED — likely dead endpoint. No repo source calls it; n8n's public credentials API is write-oriented (create / delete / fetch a type schema). A list-all read would be a secrets-enumeration surface. Verify before use.

---

## Notes

- State is filesystem-only under `/home/node/.n8n` ← `~/n8n` on the host
  (`n8n_data_dir`) — `database.sqlite`, workflow definitions, encrypted credentials.
  There is no external database.
