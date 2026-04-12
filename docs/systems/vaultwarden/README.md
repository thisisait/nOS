# Vaultwarden

> Bitwarden-kompatibilni personal password vault pro tenants.

## Quick Reference

| | |
|---|---|
| **URL** | `https://pass.dev.local` |
| **Port** | `8062` |
| **Stack** | `iiab` |
| **Toggle** | `install_vaultwarden: true` |
| **Compose** | `~/stacks/iiab/docker-compose.yml` |
| **Data** | `~/stacks/iiab/vaultwarden/data` |

## Authentication

- **Admin panel:** `https://pass.dev.local/admin`
- **Admin token:** `{global_password_prefix}_pw_vaultwarden`
- **SSO:** Authentik OIDC (optional)

## API Access

- **Base URL:** `https://pass.dev.local/api/`
- **Auth method:** Bearer token (Bitwarden API)
- **Bot account:** `openclaw-bot` (read-only access)
- **Token location:** `~/agents/tokens/vaultwarden.token`

## Health Check

- **Endpoint:** `GET /alive`
- **Expected:** `200 OK`

## Dependencies

- None (embedded SQLite database)
- Authentik (SSO, optional)
