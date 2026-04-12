# FreeScout — Skills

> Callable actions for FreeScout. Each skill is API-first using `openclaw-bot` API key.

## Authentication

- **Method:** API key
- **Token:** `~/agents/tokens/freescout.token`
- **Base URL:** `https://helpdesk.dev.local`
- **Header:** `X-FreeScout-API-Key: <api-key>`

---

## list-conversations

**Trigger:** "list conversations", "show tickets", "open support requests"
**Method:** API
**Endpoint:** `GET /api/conversations`
**Input:** Query params: `status` (optional: `active`, `pending`, `closed`), `mailbox_id` (optional), `page` (optional)
**Output:** `{ "_embedded": { "conversations": [{ "id": 1, "number": 100, "subject": "...", "status": "active", "mailboxId": 1 }] } }`

---

## get-conversation

**Trigger:** "show conversation", "get ticket details", "read thread"
**Method:** API
**Endpoint:** `GET /api/conversations/<id>`
**Input:** Conversation ID
**Output:** `{ "id": 1, "number": 100, "subject": "...", "status": "active", "_embedded": { "threads": [{ "id": 1, "body": "...", "createdBy": {...}, "type": "customer" }] } }`

---

## list-mailboxes

**Trigger:** "list mailboxes", "show inboxes", "what mailboxes exist"
**Method:** API
**Endpoint:** `GET /api/mailboxes`
**Input:** None
**Output:** `{ "_embedded": { "mailboxes": [{ "id": 1, "name": "Support", "email": "support@dev.local" }] } }`
