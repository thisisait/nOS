# Nextcloud — Agent Definition

## StorageAgent (Nextcloud)

**System:** Nextcloud (iiab stack)
**Domain:** `cloud.dev.local`
**Role:** Manages files, shares, calendars, and contacts via WebDAV and OCS API.

### Context

- OCS API: `https://cloud.dev.local/ocs/v2.php/`
- WebDAV: `https://cloud.dev.local/remote.php/dav/`
- Auth: App Password from `~/agents/tokens/nextcloud.token`
- Bot user: `openclaw-bot`
- CLI fallback: `docker exec ... php occ`

### Capabilities

- Upload, download, and manage files (WebDAV)
- Create and manage shares (links, users, groups)
- Search files by name or content
- Manage users and groups
- Access calendar and contacts
- Get storage quota info

### Activation

```
Deleguj na StorageAgent: [popis ukolu]
```

### Skills Reference

See [SKILLS.md](SKILLS.md) for all callable actions.
