# Home Assistant

> Domaci automatizace. Zarizeni, sceny, automatizace, dashboardy.

## Quick Reference

| | |
|---|---|
| **URL** | `https://home.dev.local` |
| **Port** | `8123` |
| **Stack** | `iiab` |
| **Toggle** | `install_homeassistant: true` |
| **Compose** | `~/stacks/iiab/docker-compose.yml` |
| **Data** | `~/homeassistant` |

## Authentication

- **Admin user:** `admin`
- **Admin password:** `{global_password_prefix}_pw_homeassistant`
- **SSO:** Authentik proxy auth (`home-assistant`)

## API Access

- **Base URL:** `https://home.dev.local/api/`
- **Auth method:** Long-Lived Access Token (Bearer)
- **Bot account:** `openclaw-bot` (HA user with long-lived token)
- **Token location:** `~/agents/tokens/home-assistant.token`

## Health Check

- **Endpoint:** `GET /api/`
- **Expected:** `200 OK` with `{"message":"API running."}`

## Dependencies

- None (standalone)
- Authentik proxy (SSO, optional)
