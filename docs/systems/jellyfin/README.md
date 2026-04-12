# Jellyfin

> Media server. Spravuje a streamuje filmy, serialy, hudbu a fotky.

## Quick Reference

| | |
|---|---|
| **URL** | `https://media.dev.local` |
| **Port** | `8096` |
| **Stack** | `iiab` |
| **Toggle** | `install_jellyfin: true` |
| **Compose** | `~/stacks/iiab/docker-compose.yml` |
| **Data** | `~/stacks/iiab/jellyfin/data` |

## Authentication

- **Admin user:** configured at first launch
- **Admin password:** `{global_password_prefix}_pw_jellyfin`
- **SSO:** Authentik OIDC (optional)

## API Access

- **Base URL:** `https://media.dev.local`
- **Auth method:** API key
- **Bot account:** `openclaw-bot` (API key)
- **Token location:** `~/agents/tokens/jellyfin.token`

## Health Check

- **Endpoint:** `GET /health`
- **Expected:** `200 OK` with `"Healthy"`

## Dependencies

- None (embedded database)
- Authentik (SSO, optional)
