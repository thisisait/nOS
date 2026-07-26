# ntfy — Skills

> Callable actions for ntfy. ntfy exposes a real pub/sub HTTP API (the topic
> name is the path). In nOS every endpoint is behind Authentik forward-auth,
> and no dedicated bot token is provisioned — an external caller authenticates
> with the Authentik session; internal callers reach the container by name on
> `iiab_net` / `shared_net`.

## Authentication

- **Method:** None managed by nOS — access is decided at the edge proxy
  (Authentik forward-auth session); no ntfy bearer token is provisioned or stored.
- **Default access:** `deny-all` — a call without a valid Authentik session is refused.
- **Base URL:** `https://ntfy.<tenant_domain>` (container port `80` internally).

---

## publish-notification

**Trigger:** "send a push notification", "notify me when", "push to topic", "alert my phone"
**Method:** HTTP
**Endpoint:** `POST /<topic>` (or `PUT /<topic>`)
**Input:** request body is the message text; optional headers `X-Title`,
`X-Priority` (1–5), `X-Tags` (comma-separated), `X-Click` (URL).
**Output:** `200 OK` with a JSON message object `{ "id", "time", "topic", "message" }`.

**Example:**
```bash
curl -d "Backup finished" \
  -H "X-Title: nightly-backup" -H "X-Priority: 4" -H "X-Tags: floppy_disk" \
  https://ntfy.dev.local/nos-alerts
```

---

## subscribe-topic

**Trigger:** "subscribe to topic", "stream notifications", "watch a topic for messages"
**Method:** HTTP (streaming)
**Endpoint:** `GET /<topic>/json` (newline-delimited JSON stream); also `/<topic>/sse`, `/<topic>/ws`, `/<topic>/raw`
**Input:** optional query params `since=<timestamp|id|all>`, `poll=1` (return then close), `scheduled=1`.
**Output:** a stream of JSON message objects, one per line.

**Example:**
```bash
curl -s "https://ntfy.dev.local/nos-alerts/json?since=all&poll=1"
```

---

## health-check

**Trigger:** "is ntfy up", "check ntfy health", "ntfy status"
**Method:** HTTP
**Endpoint:** `GET /v1/health`
**Input:** None
**Output:** `{"healthy":true}`
