# Apache Superset — Agent Definition

## DataAgent

**System:** Apache Superset (data visualization)
**Domain:** `superset.dev.local`
**Role:** Data visualization and SQL analytics. Manages charts, dashboards, and database connections.

### Context

- API base: `https://superset.dev.local/api/v1/` (loopback: `http://127.0.0.1:8089/api/v1/`)
- Auth: Bearer JWT minted per call via `POST /api/v1/security/login`
- User: the shared `admin` account (Superset Admin role), credentials from
  `~/.nos/secrets.yml`. nOS provisions **no** bot account for Superset (no
  `openclaw-bot`, no token file).

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
