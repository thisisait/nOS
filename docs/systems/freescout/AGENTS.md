# FreeScout — Agent Definition

## DataAgent

**System:** FreeScout (helpdesk)
**Domain:** `helpdesk.dev.local`
**Role:** Customer support data. Queries conversations, tickets, and mailboxes.

### Context

- API base: `https://helpdesk.dev.local/api/`
- Auth: API key, `X-FreeScout-API-Key: <api-key>`
- Bot user: none provisioned — generate an API key in Manage -> API & Webhooks
- Header: `X-FreeScout-API-Key: <api-key>`

### Capabilities

- List and search conversations
- Get conversation details and threads
- List mailboxes
- View customer information

### Activation

```
Delegate to DataAgent: [task description]
```

### Skills Reference

See [SKILLS.md](SKILLS.md) for all callable actions.
