# Uptime Kuma

> Status monitoring a incident management. Sleduje dostupnost vsech sluzeb.

## Quick Reference

| | |
|---|---|
| **URL** | `https://uptime.dev.local` |
| **Port** | `3001` |
| **Stack** | `iiab` |
| **Toggle** | `install_uptime_kuma: true` |
| **Compose** | `~/stacks/iiab/docker-compose.yml` |
| **Data** | `~/stacks/iiab/uptime-kuma/data` |

## Authentication

- **Admin user:** configured at first launch
- **Admin password:** `{global_password_prefix}_pw_uptime_kuma`
- **SSO:** Authentik Proxy Outpost

## API Access

- **Base URL:** `https://uptime.dev.local`
- **Auth method:** WebSocket (socket.io) + REST API
- **Bot account:** `openclaw-bot`
- **Token location:** `~/agents/tokens/uptime-kuma.token`

## Health Check

- **Endpoint:** `GET /api/entry`
- **Expected:** `200 OK`

## Dependencies

- None (embedded SQLite database)
- Authentik (Proxy Outpost, optional)
