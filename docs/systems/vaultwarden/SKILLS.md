# Vaultwarden — Skills

> Callable actions for Vaultwarden. Each skill uses Bitwarden-compatible API. Agent access is read-only.

## Authentication

- **Method:** Bearer token (Bitwarden API)
- **Token:** `~/agents/tokens/vaultwarden.token`
- **Base URL:** `https://pass.dev.local`
- **Header:** `Authorization: Bearer <token>`

---

## list-vaults

**Trigger:** "list vaults", "show organizations", "what vaults exist"
**Method:** API
**Endpoint:** `GET /api/organizations`
**Input:** None
**Output:** `{ "data": [{ "id": "...", "name": "...", "object": "organization" }] }`

---

## get-item

**Trigger:** "get password for", "find login for", "show vault item"
**Method:** API
**Endpoint:** `GET /api/ciphers/<id>`
**Input:** Cipher ID
**Output:** `{ "id": "...", "name": "...", "login": { "username": "...", "password": "..." }, "type": 1 }`

**Note:** Agent access is read-only. Agents cannot create, update, or delete vault items.
