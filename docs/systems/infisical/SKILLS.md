# Infisical — Skills

> Callable actions for Infisical CE. Each skill is API-first. Endpoints below are the
> ones the playbook's own seeder (`roles/pazny.infisical/files/seed.py`) exercises, so
> they are known-live on the pinned image — the API is version-mixed, not a single
> `/api/v1/` surface.

## Authentication

- **Method:** Bearer JWT
- **Token:** `infisical_admin_token` — harvested from the seeder's bootstrap response
  and persisted to `~/.nos/secrets.yml`.
  (There is no `~/agents/tokens/infisical.token` file and no `openclaw-bot` service
  token; that pairing is a convention in `files/openclaw/AGENTS.md` that nothing provisions.)
- **Base URL:** `https://{infisical_domain}` (default `https://vault.dev.local`) behind
  the Authentik forward-auth gate, or `http://127.0.0.1:8075` from the host (loopback
  publish, ungated — this is the path the seeder uses).
- **Header:** `Authorization: Bearer <token>`

---

## get-secret

**Trigger:** "get secret", "show password for", "what is the secret"
**Method:** API
**Endpoint:** `GET /api/v3/secrets/raw/<secret-key>`
**Input:** Query params: `workspaceId`, `environment` (nOS pushes to `prod`), `secretPath` (`/`)
**Output:** `{ "secret": { "secretKey": "...", "secretValue": "...", "version": 1 } }`

---

## create-secret

**Trigger:** "create secret", "add secret", "store password"
**Method:** API
**Endpoint:** `POST /api/v3/secrets/raw/<secret-key>` (the seeder `PATCH`es first and
falls back to `POST` on `404` — that pair is the idempotent upsert)
**Input:**
```json
{
  "workspaceId": "<project-id>",
  "environment": "prod",
  "secretPath": "/",
  "secretValue": "<value>"
}
```
**Output:** Created secret object

**Note:** secrets declared in `nos_infisical_projects` are re-pushed on every playbook
run. A hand-written value for one of those keys is overwritten on the next converge.

---

## list-secrets

**Trigger:** "list secrets", "show all secrets", "what secrets exist"
**Method:** API
**Endpoint:** `GET /api/v3/secrets/raw`
**Input:** Query params: `workspaceId`, `environment`, `secretPath` (`/`)
**Output:** `{ "secrets": [{ "secretKey": "...", "secretValue": "...", "version": 1 }] }`

---

## list-projects

**Trigger:** "list projects", "show workspaces", "what projects exist"
**Method:** API
**Endpoint:** `GET /api/v1/workspace`
**Input:** None
**Output:** `{ "workspaces": [{ "id": "...", "name": "...", "slug": "...", "environments": [...] }] }`
