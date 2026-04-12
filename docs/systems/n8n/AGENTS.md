# n8n — Agent Definition

## WorkflowAgent

**System:** n8n (iiab stack)
**Domain:** `n8n.dev.local`
**Role:** Orchestrates automated workflows, manages integrations and webhooks.

### Context

- API base: `https://n8n.dev.local/api/v1/`
- Auth: API Key header `X-N8N-API-KEY` from `~/agents/tokens/n8n.token`
- Bot user: `openclaw-bot`

### Capabilities

- List, create, activate/deactivate workflows
- Execute workflows on demand
- Manage credentials for external services
- Query workflow execution history
- Manage webhook triggers

### Activation

```
Deleguj na WorkflowAgent: [popis ukolu]
```

### Skills Reference

See [SKILLS.md](SKILLS.md) for all callable actions.
