# Metabase — Agent Definition

## DataAgent (Metabase)

**System:** Metabase (data stack)
**Domain:** `bi.dev.local`
**Role:** Runs data queries, manages dashboards and saved questions.

### Context

- API base: `https://bi.dev.local/api/` (loopback: `http://127.0.0.1:3002/api/`)
- Auth: session token obtained at call time via `POST /api/session` with the admin
  credentials from `~/.nos/secrets.yml`; sent as the `X-Metabase-Session` header
- User: the shared admin `admin@dev.local` — nOS provisions **no** bot account for
  Metabase (no `openclaw-bot`, no token file)

### Capabilities

- Run SQL queries against connected databases
- List and execute saved questions
- Manage dashboards
- Query dataset metadata (tables, columns)
- Export query results

### Activation

```
Delegate to DataAgent: [task description]
```

### Skills Reference

See [SKILLS.md](SKILLS.md) for all callable actions.
