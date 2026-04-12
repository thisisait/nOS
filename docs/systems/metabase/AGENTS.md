# Metabase — Agent Definition

## DataAgent (Metabase)

**System:** Metabase (data stack)
**Domain:** `bi.dev.local`
**Role:** Runs data queries, manages dashboards and saved questions.

### Context

- API base: `https://bi.dev.local/api/`
- Auth: Session token from `~/agents/tokens/metabase.token`
- Bot user: `openclaw-bot`

### Capabilities

- Run SQL queries against connected databases
- List and execute saved questions
- Manage dashboards
- Query dataset metadata (tables, columns)
- Export query results

### Activation

```
Deleguj na DataAgent: [popis ukolu]
```

### Skills Reference

See [SKILLS.md](SKILLS.md) for all callable actions.
