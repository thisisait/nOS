# Infisical

> Centralni secrets vault pro infrastrukturni secrets. REST API + CLI.

## Quick Reference

| | |
|---|---|
| **URL** | `https://vault.dev.local` |
| **Port** | `8075` |
| **Stack** | `infra` |
| **Toggle** | `install_infisical: true` |
| **Compose** | `~/stacks/infra/docker-compose.yml` |
| **Data** | `~/stacks/infra/infisical/data` |

## Authentication

- **Admin user:** configured at first launch
- **Admin password:** `{global_password_prefix}_pw_infisical`
- **SSO:** Authentik OIDC (optional)

## API Access

- **Base URL:** `https://vault.dev.local/api/v1/`
- **Auth method:** Service token
- **Bot account:** `openclaw-bot` (service token)
- **Token location:** `~/agents/tokens/infisical.token`

## Health Check

- **Endpoint:** `GET /api/status`
- **Expected:** `200 OK`

## Dependencies

- PostgreSQL (database backend)
- Redis (cache)
