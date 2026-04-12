# Uptime Kuma — Skills

> Callable actions for Uptime Kuma. Uses REST API and WebSocket (socket.io) for real-time operations.

## Authentication

- **Method:** API key / WebSocket auth
- **Token:** `~/agents/tokens/uptime-kuma.token`
- **Base URL:** `https://uptime.dev.local`

---

## list-monitors

**Trigger:** "list monitors", "show all monitors", "what is being monitored"
**Method:** API
**Endpoint:** `GET /api/monitors`
**Input:** None
**Output:** `[{ "id": 1, "name": "...", "url": "...", "type": "http", "active": true, "status": 1 }]`

---

## add-monitor

**Trigger:** "add monitor", "monitor this service", "watch URL"
**Method:** API
**Endpoint:** `POST /api/monitors`
**Input:**
```json
{
  "name": "<monitor name>",
  "url": "<URL to monitor>",
  "type": "http",
  "interval": 60,
  "maxretries": 3,
  "accepted_statuscodes": ["200-299"]
}
```
**Output:** Created monitor object with `id`

---

## get-status

**Trigger:** "check status", "is everything up", "service health overview"
**Method:** API
**Endpoint:** `GET /api/status-page/heartbeat/<slug>`
**Input:** Status page slug
**Output:** `{ "heartbeatList": { "<id>": [{ "status": 1, "time": "...", "msg": "..." }] } }`

---

## list-incidents

**Trigger:** "show incidents", "any outages", "what went down"
**Method:** API
**Endpoint:** `GET /api/status-page/<slug>`
**Input:** Status page slug
**Output:** `{ "incident": { "id": 1, "title": "...", "content": "...", "style": "danger", "createdDate": "..." } }`
