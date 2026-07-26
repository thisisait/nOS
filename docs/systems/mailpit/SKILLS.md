# Mailpit — Skills

> Callable actions for Mailpit. Mailpit ships a real REST API (`/api/v1/`) for
> inspecting captured mail, plus an SMTP listener on `1025` for sending test
> mail into the sink. The API is unauthenticated on the loopback UI port; the
> public edge (`mail.<tld>`) is Authentik forward-auth gated.

## Authentication

- **Method:** none at the app layer on loopback (`http://127.0.0.1:8025`);
  Authentik forward-auth on the public edge. No bot token is provisioned.
- **Base URL:** `http://127.0.0.1:8025` (loopback) or `https://mail.<tenant_domain>` (edge).

---

## list-messages

**Trigger:** "list captured emails", "show the mail inbox", "what emails were sent"
**Method:** REST
**Endpoint:** `GET /api/v1/messages`
**Input:** optional query params `start` (offset), `limit`.
**Output:** `{ "total", "unread", "count", "start", "messages": [ { "ID", "From", "To", "Subject", "Created", ... } ] }`

---

## get-message

**Trigger:** "read email [id]", "show the message body", "open captured email"
**Method:** REST
**Endpoint:** `GET /api/v1/message/{ID}`
**Input:** message ID (from list-messages; `latest` is accepted for the newest).
**Output:** full message JSON — `Text`, `HTML`, `Headers`, `Attachments`, envelope.

---

## search-messages

**Trigger:** "search emails for", "find email to/from", "did we receive a mail about"
**Method:** REST
**Endpoint:** `GET /api/v1/search?query=<query>`
**Input:** `query` string (Mailpit search syntax, e.g. `to:alice@dev.local subject:invoice`).
**Output:** same shape as list-messages, filtered.

---

## delete-messages

**Trigger:** "clear the inbox", "delete all captured mail", "empty Mailpit"
**Method:** REST
**Endpoint:** `DELETE /api/v1/messages`
**Input:** empty body deletes ALL; `{ "IDs": ["<id>", ...] }` deletes a subset.
**Output:** `200 OK`.

---

## send-test-mail

**Trigger:** "send a test email", "relay a message into the sink", "verify SMTP capture"
**Method:** SMTP
**Endpoint:** `smtp://127.0.0.1:1025` (any credentials accepted — `MP_SMTP_AUTH_ACCEPT_ANY`)
**Input:** a standard SMTP envelope + message.
**Output:** the message appears in the UI / `GET /api/v1/messages`.

---

## health-check

**Trigger:** "is Mailpit up", "check Mailpit health"
**Method:** REST
**Endpoint:** `GET /livez` (readiness: `GET /readyz`)
**Input:** None
**Output:** `200 OK`
