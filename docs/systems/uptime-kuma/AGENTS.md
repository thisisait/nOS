# Uptime Kuma — Agent Definition

## MonitorAgent

**System:** Uptime Kuma (status monitoring)
**Domain:** `uptime.dev.local`
**Role:** Uptime and incident management. Monitors service availability and manages status pages.

### Context

- API base: `https://uptime.dev.local` (loopback: `http://127.0.0.1:3001`)
- Auth: admin user + password from `~/.nos/secrets.yml`, passed to the socket.io login.
  There is no API-key file and no `openclaw-bot` account.
- socket.io is the **only** management API. The handful of REST routes
  (`/api/entry-page`, `/api/status-page/<slug>`, `/api/status-page/heartbeat/<slug>`,
  `/api/badge/...`) are read-only status surfaces.
- Reference implementation: `roles/pazny.uptime_kuma/files/setup-monitors.py`
  (wraps `uptime_kuma_api.UptimeKumaApi`)

### Capabilities

- List and manage monitors
- Add new HTTP/TCP/DNS monitors
- Get current status of all services
- List and manage incidents
- View uptime history and statistics

### Activation

```
Deleguj na MonitorAgent: [popis ukolu]
```

### Skills Reference

See [SKILLS.md](SKILLS.md) for all callable actions.
