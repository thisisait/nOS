# Authentik

> SSO/IdP provider. Centralni identity a access management pro vsechny sluzby.

## Quick Reference

| | |
|---|---|
| **URL** | `https://auth.dev.local` |
| **Port** | `9003` |
| **Stack** | `infra` |
| **Toggle** | `install_authentik: true` |
| **Compose** | `~/stacks/infra/docker-compose.yml` |
| **Data** | `~/stacks/infra/authentik/data` |

## Authentication

- **Admin user:** `akadmin`
- **Admin password:** `{global_password_prefix}_pw_authentik`
- **SSO:** N/A (this is the SSO provider)

## API Access

- **Base URL:** `https://auth.dev.local/api/v3/`
- **Auth method:** Bearer token (API Token)
- **Bot account:** `openclaw-bot` (auto-created by playbook)
- **Token location:** `~/agents/tokens/authentik.token`

## Health Check

- **Endpoint:** `GET /-/health/live/`
- **Expected:** `200 OK`

## OIDC Providers

Authentik auto-creates OIDC providers and applications for all services listed in `authentik_oidc_apps` (default.config.yml). Each service gets a provider + application pair.

## Dependencies

- PostgreSQL (database backend)
- Redis (cache/broker)
