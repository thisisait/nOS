# Vaultwarden — Agent Definition

## SecurityAgent

**System:** Vaultwarden (personal password vault)
**Domain:** `pass.dev.local`
**Role:** Password management. Read-only access to vault items for agents.

### Context

- API base: `https://pass.dev.local/api/`
- Auth: Bearer token from `~/agents/tokens/vaultwarden.token`
- Bot user: `openclaw-bot` (Bitwarden API, read-only)
- Bitwarden-compatible API (same as Bitwarden Cloud)

### Capabilities

- List vaults/organizations
- Get vault items (read-only)
- Search vault entries
- Check vault health

### Activation

```
Deleguj na SecurityAgent: [popis ukolu]
```

### Skills Reference

See [SKILLS.md](SKILLS.md) for all callable actions.
