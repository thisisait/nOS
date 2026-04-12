# Outline

> Tymova wiki a knowledge base. Markdown editor, kolekce, vyhledavani.

## Quick Reference

| | |
|---|---|
| **URL** | `https://wiki.dev.local` |
| **Port** | `3005` |
| **Stack** | `b2b` |
| **Toggle** | `install_outline: true` |
| **Compose** | `~/stacks/b2b/docker-compose.yml` |
| **Data** | `~/outline` |

## Authentication

- **SSO:** Authentik OIDC (`outline`) — SSO is the only login method
- **Admin:** First user who logs in via SSO

## API Access

- **Base URL:** `https://wiki.dev.local/api/`
- **Auth method:** Bearer token (Personal API Token)
- **Bot account:** `openclaw-bot` (create via SSO login + API key)
- **Token location:** `~/agents/tokens/outline.token`

## Health Check

- **Endpoint:** `GET /_health`
- **Expected:** `200 OK`

## Dependencies

- PostgreSQL (database)
- Redis (cache/sessions)
- Authentik (SSO, required)
