# Authentik — Agent Definition

## SecurityAgent

**System:** Authentik (SSO/IdP)
**Domain:** `auth.dev.local`
**Role:** Manages SSO, users, groups, OIDC providers, and applications. Audits authentication events.

### Context

- API base: `https://auth.dev.local/api/v3/`
- Auth: Bearer token from `~/agents/tokens/authentik.token`
- Bot user: `openclaw-bot` (Authentik API Token, Admin)
- OIDC apps: auto-provisioned from `authentik_oidc_apps` list

### Capabilities

- List, create, and manage users
- List, create, and manage groups
- Create and configure OIDC providers
- Create and manage applications
- Query audit/event logs
- Manage authentication flows and policies

### Activation

```
Deleguj na SecurityAgent: [popis ukolu]
```

### Skills Reference

See [SKILLS.md](SKILLS.md) for all callable actions.
