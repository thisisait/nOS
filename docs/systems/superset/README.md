# Apache Superset

> Datova vizualizace a BI. Dashboardy, charty a SQL dotazy.

## Quick Reference

| | |
|---|---|
| **URL** | `https://superset.dev.local` |
| **Port** | `8089` |
| **Stack** | `data` |
| **Toggle** | `install_superset: true` |
| **Compose** | `~/stacks/data/docker-compose.yml` |
| **Data** | `~/stacks/data/superset/data` |

## Authentication

- **Admin user:** `admin`
- **Admin password:** `{global_password_prefix}_pw_superset`
- **SSO:** Authentik OIDC (optional)

## API Access

- **Base URL:** `https://superset.dev.local/api/v1/`
- **Auth method:** Bearer JWT
- **Bot account:** `openclaw-bot` (auto-created by playbook)
- **Token location:** `~/agents/tokens/superset.token`

## Health Check

- **Endpoint:** `GET /health`
- **Expected:** `200 OK` with `"OK"`

## Dependencies

- PostgreSQL (metadata database)
- Redis (cache/celery broker)
- Authentik (SSO, optional)
