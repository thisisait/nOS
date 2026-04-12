# Apache Superset — Agent Definition

## DataAgent

**System:** Apache Superset (data visualization)
**Domain:** `superset.dev.local`
**Role:** Data visualization and SQL analytics. Manages charts, dashboards, and database connections.

### Context

- API base: `https://superset.dev.local/api/v1/`
- Auth: Bearer JWT from `~/agents/tokens/superset.token`
- Bot user: `openclaw-bot` (Superset Admin role)
- JWT obtained via `POST /api/v1/security/login`

### Capabilities

- List and manage charts
- Execute SQL queries against connected databases
- List and manage dashboards
- List connected databases
- Export/import dashboard definitions

### Activation

```
Deleguj na DataAgent: [popis ukolu]
```

### Skills Reference

See [SKILLS.md](SKILLS.md) for all callable actions.
