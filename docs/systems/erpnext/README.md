# ERPNext

> CRM/ERP system. Spravuje obchodni data, faktury, zakazniky a zasoby.

## Quick Reference

| | |
|---|---|
| **URL** | `https://erp.dev.local` |
| **Port** | `8082` |
| **Stack** | `b2b` |
| **Toggle** | `install_erpnext: true` |
| **Compose** | `~/stacks/b2b/docker-compose.yml` |
| **Data** | `~/stacks/b2b/erpnext/data` |

## Authentication

- **Admin user:** `Administrator`
- **Admin password:** `{global_password_prefix}_pw_erpnext`
- **SSO:** Authentik OIDC (optional)

## API Access

- **Base URL:** `https://erp.dev.local/api/resource/`
- **Auth method:** API key + secret
- **Bot account:** `openclaw-bot` (auto-created by playbook)
- **Token location:** `~/agents/tokens/erpnext.token`

## Health Check

- **Endpoint:** `GET /api/method/ping`
- **Expected:** `200 OK` with `{"message": "pong"}`

## Dependencies

- MariaDB (database backend)
- Redis (cache/queue)
- Authentik (SSO, optional)
