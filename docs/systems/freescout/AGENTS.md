# FreeScout — Agent Definition

## DataAgent

**System:** FreeScout (helpdesk)
**Domain:** `helpdesk.dev.local`
**Role:** Customer support data. Queries conversations, tickets, and mailboxes.

### Context

- API base: `https://helpdesk.dev.local/api/`
- Auth: API key from `~/agents/tokens/freescout.token`
- Bot user: `openclaw-bot` (FreeScout API key)
- Header: `X-FreeScout-API-Key: <api-key>`

### Capabilities

- List and search conversations
- Get conversation details and threads
- List mailboxes
- View customer information

### Activation

```
Deleguj na DataAgent: [popis ukolu]
```

### Skills Reference

See [SKILLS.md](SKILLS.md) for all callable actions.
