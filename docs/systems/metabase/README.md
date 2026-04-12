# Metabase

> BI dashboardy. SQL dotazy, vizualizace, sdileni reportu.

## Quick Reference

| | |
|---|---|
| **URL** | `https://bi.dev.local` |
| **Port** | `3002` |
| **Stack** | `data` |
| **Toggle** | `install_metabase: true` |
| **Compose** | `~/stacks/data/docker-compose.yml` |
| **Data** | `~/metabase` |

## Authentication

- **Admin user:** `admin@dev.local`
- **Admin password:** `{global_password_prefix}_pw_metabase_admin`
- **SSO:** Authentik proxy auth (`metabase`)

## API Access

- **Base URL:** `https://bi.dev.local/api/`
- **Auth method:** Session token (from `POST /api/session`)
- **Bot account:** `openclaw-bot`
- **Token location:** `~/agents/tokens/metabase.token`

## Health Check

- **Endpoint:** `GET /api/health`
- **Expected:** `200 OK` with `{"status":"ok"}`

## Dependencies

- PostgreSQL (application database)
