# Nextcloud

> Self-hosted cloud. Soubory, sdileni, kalendar, kontakty, spoluprace.

## Quick Reference

| | |
|---|---|
| **URL** | `https://cloud.dev.local` |
| **Port** | `8085` |
| **Stack** | `iiab` |
| **Toggle** | `install_nextcloud: true` |
| **Compose** | `~/stacks/iiab/docker-compose.yml` |
| **Data** | `~/nextcloud` |

## Authentication

- **Admin user:** `admin`
- **Admin password:** `{global_password_prefix}_pw_nextcloud`
- **SSO:** Authentik OIDC (`nextcloud`) — configured via occ CLI

## API Access

- **Base URL:** `https://cloud.dev.local/ocs/v2.php/` (OCS API)
- **WebDAV:** `https://cloud.dev.local/remote.php/dav/`
- **Auth method:** Basic auth or App Password
- **Bot account:** `openclaw-bot`
- **Token location:** `~/agents/tokens/nextcloud.token`
- **Header:** `OCS-APIRequest: true`

## Health Check

- **Endpoint:** `GET /status.php`
- **Expected:** `200 OK` with `{"installed":true,"maintenance":false,...}`

## Dependencies

- MariaDB (database)
- Authentik (SSO, optional)
