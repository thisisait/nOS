# Bluesky PDS

> AT Protocol Personal Data Server. Identita a federace v decentralizovane socialni siti.

## Quick Reference

| | |
|---|---|
| **URL** | `https://pds.dev.local` |
| **Port** | `2583` |
| **Stack** | `infra` |
| **Toggle** | `install_bluesky_pds: true` |
| **Compose** | `~/stacks/infra/docker-compose.yml` |
| **Data** | `~/stacks/infra/bluesky-pds/data` |

## Authentication

- **Admin password:** `{global_password_prefix}_pw_bluesky_pds`
- **SSO:** N/A (AT Protocol native auth)

## API Access

- **Base URL:** `https://pds.dev.local/xrpc/`
- **Auth method:** Bearer JWT (AT Protocol session)
- **Bot account:** `openclaw-bot` (auto-created by playbook)
- **Token location:** `~/agents/tokens/bluesky-pds.token`

## Health Check

- **Endpoint:** `GET /xrpc/_health`
- **Expected:** `200 OK` with `{"version": "..."}`

## Dependencies

- None (embedded SQLite database)
