# Authentik — Skills

> Callable actions for Authentik. Each skill is API-first using `openclaw-bot` API token.

## Authentication

- **Method:** Bearer token (Authentik API Token)
- **Token:** `~/agents/tokens/authentik.token`
- **Base URL:** `https://auth.dev.local`
- **Header:** `Authorization: Bearer <token>`

---

## list-users

**Trigger:** "list users", "show all users", "who has access"
**Method:** API
**Endpoint:** `GET /api/v3/core/users/`
**Input:** Query params: `search` (optional), `page` (optional)
**Output:** `{ "pagination": {...}, "results": [{ "pk": 1, "username": "...", "name": "...", "email": "...", "is_active": true }] }`

---

## create-user

**Trigger:** "create user", "add new user", "register user"
**Method:** API
**Endpoint:** `POST /api/v3/core/users/`
**Input:**
```json
{
  "username": "<username>",
  "name": "<display name>",
  "email": "<email>",
  "is_active": true,
  "groups": [<group_pk>]
}
```
**Output:** Created user object with `pk`

---

## list-applications

**Trigger:** "list applications", "show SSO apps", "what services use SSO"
**Method:** API
**Endpoint:** `GET /api/v3/core/applications/`
**Input:** Query params: `search` (optional)
**Output:** `{ "pagination": {...}, "results": [{ "pk": "...", "name": "...", "slug": "...", "provider": <id>, "launch_url": "..." }] }`

---

## create-provider

**Trigger:** "create OIDC provider", "add SSO provider", "set up SSO for"
**Method:** API
**Endpoint:** `POST /api/v3/providers/oauth2/`
**Input:**
```json
{
  "name": "<provider-name>",
  "authorization_flow": "<flow-slug>",
  "client_type": "confidential",
  "client_id": "<client-id>",
  "client_secret": "<client-secret>",
  "redirect_uris": "<redirect-uri>"
}
```
**Output:** Created provider object with `pk`

---

## get-events

**Trigger:** "show audit log", "check login events", "who logged in", "security events"
**Method:** API
**Endpoint:** `GET /api/v3/events/events/`
**Input:** Query params: `action` (optional, e.g. `login`), `user__username` (optional), `ordering` (optional, e.g. `-created`)
**Output:** `{ "pagination": {...}, "results": [{ "pk": "...", "action": "login", "user": {...}, "created": "...", "client_ip": "..." }] }`
