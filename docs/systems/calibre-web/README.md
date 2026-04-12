# Calibre-Web

> Ebook server. Webove rozhrani pro spravu a cteni knih z Calibre knihovny.

## Quick Reference

| | |
|---|---|
| **URL** | `https://books.dev.local` |
| **Port** | `8083` |
| **Stack** | `iiab` |
| **Toggle** | `install_calibreweb: true` |
| **Compose** | `~/stacks/iiab/docker-compose.yml` |
| **Data** | `~/stacks/iiab/calibre-web/data` |

## Authentication

- **Admin user:** `admin`
- **Admin password:** `{global_password_prefix}_pw_calibreweb`
- **SSO:** Authentik Proxy Outpost

## API Access

- **Base URL:** N/A (no REST API)
- **Auth method:** N/A
- **CLI access:** `docker exec calibre-web <command>`
- **OPDS feed:** `https://books.dev.local/opds` (read-only catalog)

## Health Check

- **Endpoint:** `GET /` (web UI)
- **Expected:** `200 OK` with login page

## Dependencies

- None (embedded SQLite database)
- Calibre library (mounted volume)
- Authentik (Proxy Outpost, optional)
