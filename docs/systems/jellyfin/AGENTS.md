# Jellyfin — Agent Definition

## ContentAgent

**System:** Jellyfin (media server)
**Domain:** `media.dev.local`
**Role:** Media library management. Searches and queries media collections.

### Context

- API base: `https://media.dev.local`
- Auth: API key from `~/agents/tokens/jellyfin.token`
- Bot user: `openclaw-bot` (Jellyfin API key)
- Header: `X-Emby-Token: <api-key>`

### Capabilities

- List media libraries
- Search media items (movies, series, music)
- Get playback info and stream URLs
- List users and sessions
- Trigger library scans

### Activation

```
Deleguj na ContentAgent: [popis ukolu]
```

### Skills Reference

See [SKILLS.md](SKILLS.md) for all callable actions.
