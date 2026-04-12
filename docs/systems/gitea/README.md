# Gitea

> Self-hosted Git server. Repozitare, issues, pull requesty, webhooky.

## Quick Reference

| | |
|---|---|
| **URL** | `https://git.dev.local` |
| **Port** | `3003` |
| **SSH** | `localhost:2222` |
| **Stack** | `devops` |
| **Toggle** | `install_gitea: true` |
| **Compose** | `~/stacks/devops/docker-compose.yml` |
| **Data** | `~/gitea` |

## Authentication

- **Admin user:** `{ansible_user}` (system username)
- **Admin password:** `{global_password_prefix}_pw_gitea`
- **SSO:** Authentik OIDC (`gitea`) — configured via Admin API

## API Access

- **Base URL:** `https://git.dev.local/api/v1/`
- **Auth method:** Bearer token (Personal Access Token)
- **Bot account:** `openclaw-bot` (auto-created by playbook)
- **Token location:** `~/agents/tokens/gitea.token`
- **Swagger:** `https://git.dev.local/swagger`

## Health Check

- **Endpoint:** `GET /api/v1/version`
- **Expected:** `200 OK` with `{"version":"..."}`

## Dependencies

- None (SQLite built-in)
- Authentik (SSO, optional)
- Woodpecker CI (CI/CD, optional — uses Gitea OAuth)
