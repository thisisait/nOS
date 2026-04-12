# Bluesky PDS — Agent Definition

## CommAgent

**System:** Bluesky PDS (AT Protocol)
**Domain:** `pds.dev.local`
**Role:** Social federation and communication. Manages AT Protocol identity, posts, and feeds.

### Context

- API base: `https://pds.dev.local/xrpc/`
- Auth: Bearer JWT from `~/agents/tokens/bluesky-pds.token`
- Bot user: `openclaw-bot` (AT Protocol account)
- XRPC protocol (AT Protocol native)

### Capabilities

- Create and manage posts
- Read feed and timeline
- Get and update profile
- Manage account settings
- Handle AT Protocol identity (DID)

### Activation

```
Deleguj na CommAgent: [popis ukolu]
```

### Skills Reference

See [SKILLS.md](SKILLS.md) for all callable actions.
