# FreeScout

> Helpdesk system. Spravuje zakaznicke konverzace a emaily.

## Quick Reference

| | |
|---|---|
| **URL** | `https://helpdesk.dev.local` |
| **Port** | `8090` |
| **Stack** | `b2b` |
| **Toggle** | `install_freescout: true` |
| **Compose** | `~/stacks/b2b/docker-compose.yml` |
| **Data** | `~/stacks/b2b/freescout/data` |

## Authentication

- **Admin user:** configured at first launch
- **Admin password:** `{global_password_prefix}_pw_freescout`
- **SSO:** Authentik OIDC (optional)

## API Access

- **Base URL:** `https://helpdesk.dev.local/api/`
- **Auth method:** API key
- **Bot account:** `openclaw-bot` (API key)
- **Token location:** `~/agents/tokens/freescout.token`

## Health Check

- **Endpoint:** `GET /api/conversations` (with API key)
- **Expected:** `200 OK` with conversations JSON

## Dependencies

- MariaDB (database backend)
- Authentik (SSO, optional)
