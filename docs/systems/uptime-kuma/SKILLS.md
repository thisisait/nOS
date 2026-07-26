# Uptime Kuma — Skills

> Callable actions for Uptime Kuma. Monitor management is **socket.io only** — the
> `uptime_kuma_api` Python client, exactly as
> `roles/pazny.uptime_kuma/files/setup-monitors.py` uses it. The only HTTP routes Kuma
> serves are the read-only status surfaces at the bottom of this file.

## Authentication

- **Method:** socket.io session — `UptimeKumaApi(url).login(user, password)` (or
  `.setup(user, password)` on a fresh, never-initialized instance)
- **Credentials:** `~/.nos/secrets.yml` — `uptime_kuma_admin_user` (`admin`) +
  `{global_password_prefix}_pw_uptime_kuma`. No API-key file, no bot account.
- **Base URL:** `https://uptime.dev.local` (loopback: `http://127.0.0.1:3001`)

---

## list-monitors

**Trigger:** "list monitors", "show all monitors", "what is being monitored"
**Method:** socket.io (`uptime_kuma_api`)
**Call:** `api.get_monitors()`
**Input:** None
**Output:** `[{ "id": 1, "name": "...", "url": "...", "type": "http", "active": true }]`

---

## add-monitor

**Trigger:** "add monitor", "monitor this service", "watch URL"
**Method:** socket.io (`uptime_kuma_api`)
**Call:** `api.add_monitor(**kwargs)` — `api.edit_monitor(id, **kwargs)` to update an
existing one (the role upserts by name)
**Input:**
```python
api.add_monitor(
    type=MonitorType.HTTP,
    name="<monitor name>",
    url="<URL to monitor>",
    interval=60,
    maxretries=3,
    accepted_statuscodes=["200-299"],
)
```
**Output:** `{ "monitorID": <id>, "msg": "Added Successfully." }`

---

## add-notification

**Trigger:** "notify me when X goes down", "wire alerts to ntfy"
**Method:** socket.io (`uptime_kuma_api`)
**Call:** `api.add_notification(**kwargs)` / `api.edit_notification(id, **kwargs)`
**Input:** ntfy (`uptime_kuma_ntfy_topic`, default `nos-alerts`) or an HMAC-signed
webhook to Bone at `http://127.0.0.1:{{ bone_port }}/api/events`
**Output:** Created notification with `id`

---

## ensure-status-page

**Trigger:** "publish a status page", "expose service status"
**Method:** socket.io (`uptime_kuma_api`)
**Call:** `api.add_status_page(slug=..., title=...)` then `api.save_status_page(...)`
**Input:** `uptime_kuma_status_page_slug` (default `nos`),
`uptime_kuma_status_page_title` (default `nOS Service Status`)
**Output:** Status page served at `status.<tenant_domain>`

---

## HTTP read-only surfaces

The routes below are the only real REST endpoints Uptime Kuma serves. They are
unauthenticated at the app level (the Authentik forward-auth gate is what protects
them) and read-only. Alongside them Kuma also serves `GET /api/entry-page`,
`GET /api/badge/<id>/<type>`, and `GET /metrics`.

---

## get-status

**Trigger:** "check status", "is everything up", "service health overview"
**Method:** HTTP (read-only)
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
