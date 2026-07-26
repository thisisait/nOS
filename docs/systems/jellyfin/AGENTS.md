# Jellyfin — Agent Definition

## ContentAgent

**System:** Jellyfin (media server)
**Domain:** `media{host_alias_seg}.{tenant_domain}` (default `media.dev.local`)
**Role:** Media library management. Searches and queries media collections.

### Context

- API base: `https://media{host_alias_seg}.{tenant_domain}` (default `https://media.dev.local`)
- Auth: an API key minted manually under Dashboard → API Keys. The playbook provisions **no**
  bot account and **no** token file — there is no `openclaw-bot` and no `~/agents/tokens/jellyfin.token`.
- Header: `X-Emby-Token: <api-key>`
- Human sign-in is `native_oidc` through the jellyfin-plugin-sso server plugin (Authentik client
  `nos-jellyfin`), so the agent path (API key) and the human path (OIDC) are separate.

### Capabilities

- List media libraries
- Search media items (movies, series, music)
- Get playback info and stream URLs
- List users and sessions
- Trigger library scans

### Activation

```
Delegate to ContentAgent: [task description]
```

### Skills Reference

See [SKILLS.md](SKILLS.md) for all callable actions.
