# WordPress

> CMS pro webovy obsah. Spravuje stranky, clanky a media.

## Quick Reference

| | |
|---|---|
| **URL** | `https://wp.dev.local` |
| **Port** | `8084` |
| **Stack** | `iiab` |
| **Toggle** | `install_wordpress: true` |
| **Compose** | `~/stacks/iiab/docker-compose.yml` |
| **Data** | `~/stacks/iiab/wordpress/data` |

## Authentication

- **Admin user:** `admin`
- **Admin password:** `{global_password_prefix}_pw_wordpress`
- **SSO:** Authentik OIDC (optional)

## API Access

- **Base URL:** `https://wp.dev.local/wp-json/wp/v2/`
- **Auth method:** Basic auth (Application Passwords)
- **Bot account:** `openclaw-bot` (auto-created by playbook)
- **Token location:** `~/agents/tokens/wordpress.token`

## Health Check

- **Endpoint:** `GET /wp-json/`
- **Expected:** `200 OK` with site info JSON

## Dependencies

- MariaDB (database backend)
- Authentik (SSO, optional)
