# Infisical — Skills

> Callable actions for Infisical. Each skill is API-first using `openclaw-bot` service token.

## Authentication

- **Method:** Service token
- **Token:** `~/agents/tokens/infisical.token`
- **Base URL:** `https://vault.dev.local`
- **Header:** `Authorization: Bearer <service-token>`

---

## get-secret

**Trigger:** "get secret", "show password for", "what is the secret"
**Method:** API
**Endpoint:** `GET /api/v1/secrets/<secret-name>`
**Input:** Query params: `workspaceId`, `environment` (e.g. `dev`, `prod`)
**Output:** `{ "secret": { "secretName": "...", "secretValue": "...", "version": 1 } }`

---

## create-secret

**Trigger:** "create secret", "add secret", "store password"
**Method:** API
**Endpoint:** `POST /api/v1/secrets/<secret-name>`
**Input:**
```json
{
  "workspaceId": "<project-id>",
  "environment": "dev",
  "secretValue": "<value>",
  "type": "shared"
}
```
**Output:** Created secret object

---

## list-secrets

**Trigger:** "list secrets", "show all secrets", "what secrets exist"
**Method:** API
**Endpoint:** `GET /api/v1/secrets/`
**Input:** Query params: `workspaceId`, `environment`
**Output:** `{ "secrets": [{ "secretName": "...", "secretValue": "...", "version": 1 }] }`

---

## list-projects

**Trigger:** "list projects", "show workspaces", "what projects exist"
**Method:** API
**Endpoint:** `GET /api/v1/workspace/`
**Input:** None
**Output:** `{ "workspaces": [{ "_id": "...", "name": "...", "environments": [...] }] }`
