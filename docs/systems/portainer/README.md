# Portainer

> Docker management UI. Sprava kontejneru, stacku, images, volumes.

## Quick Reference

| | |
|---|---|
| **URL** | `https://portainer.dev.local` |
| **Port** | `9002` |
| **Stack** | `infra` |
| **Toggle** | `install_portainer: true` |
| **Compose** | `~/stacks/infra/docker-compose.yml` |
| **Data** | Portainer internal volume |

## Authentication

- **Admin user:** `admin`
- **Admin password:** `{global_password_prefix}_pw_portainer`
- **SSO:** Authentik OIDC (`portainer`) — configured via Settings API

## API Access

- **Base URL:** `https://portainer.dev.local/api/`
- **Auth method:** Bearer JWT (from `POST /api/auth`)
- **Bot account:** `openclaw-bot`
- **Token location:** `~/agents/tokens/portainer.token`

## Health Check

- **Endpoint:** `GET /api/status`
- **Expected:** `200 OK`

## Dependencies

- Docker socket (`/var/run/docker.sock`)
- Authentik (SSO, optional)
