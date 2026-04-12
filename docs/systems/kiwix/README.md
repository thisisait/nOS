# Kiwix

> Offline content server. Poskytuje offline pristup k Wikipedii, Gutenbergu a dalsim zdrojum.

## Quick Reference

| | |
|---|---|
| **URL** | `https://kiwix.dev.local` |
| **Port** | `8888` |
| **Stack** | `iiab` |
| **Toggle** | `install_kiwix: true` |
| **Compose** | `~/stacks/iiab/docker-compose.yml` |
| **Data** | `~/stacks/iiab/kiwix/data` |

## Authentication

- **Admin user:** N/A (no authentication)
- **SSO:** N/A

## API Access

- **Base URL:** `https://kiwix.dev.local`
- **Auth method:** None (public read-only)
- **Search endpoint:** `/search`

## Health Check

- **Endpoint:** `GET /`
- **Expected:** `200 OK` with library page

## Content Libraries

| ZIM File | Content |
|----------|---------|
| Wikipedia | Offline Wikipedia (selected language) |
| Gutenberg | Project Gutenberg ebooks |

## Dependencies

- None (standalone, reads ZIM files from mounted volume)
