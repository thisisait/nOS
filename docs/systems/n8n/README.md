# n8n

> Workflow automation. Vizualni editor, 400+ integracnich nodu, webhooky.

## Quick Reference

| | |
|---|---|
| **URL** | `https://n8n.dev.local` |
| **Port** | `5678` |
| **Stack** | `iiab` |
| **Toggle** | `install_n8n: true` |
| **Compose** | `~/stacks/iiab/docker-compose.yml` |
| **Data** | `~/n8n` |

## Authentication

- **Admin user:** `admin@dev.local`
- **Admin password:** `{global_password_prefix}_pw_n8n`
- **SSO:** Authentik OIDC (`n8n`)

## API Access

- **Base URL:** `https://n8n.dev.local/api/v1/`
- **Auth method:** API Key (header `X-N8N-API-KEY`)
- **Bot account:** `openclaw-bot`
- **Token location:** `~/agents/tokens/n8n.token`

## Health Check

- **Endpoint:** `GET /healthz`
- **Expected:** `200 OK`

## Dependencies

- Authentik (SSO, optional)
