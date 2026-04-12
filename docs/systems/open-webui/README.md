# Open WebUI

> Chat UI pro Ollama LLM modely. Multi-user, RAG, model management.

## Quick Reference

| | |
|---|---|
| **URL** | `https://ai.dev.local` |
| **Port** | `3004` |
| **Stack** | `iiab` |
| **Toggle** | `install_openwebui: true` |
| **Compose** | `~/stacks/iiab/docker-compose.yml` |
| **Data** | `~/open-webui` |

## Authentication

- **Admin user:** `admin@dev.local`
- **Admin password:** `{global_password_prefix}_pw_openwebui_admin`
- **SSO:** Authentik OIDC (`open-webui`)

## API Access

- **Base URL:** `https://ai.dev.local/api/`
- **Auth method:** Bearer token (JWT from signin)
- **Bot account:** `openclaw-bot` (auto-created)
- **Token location:** `~/agents/tokens/open-webui.token`

## Health Check

- **Endpoint:** `GET /api/config`
- **Expected:** `200 OK`

## Dependencies

- Ollama (LLM backend, `http://host.docker.internal:11434`)
- Authentik (SSO, optional)
