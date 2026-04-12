# Gitea — Agent Definition

## DevOpsAgent (Gitea)

**System:** Gitea (devops stack)
**Domain:** `git.dev.local`
**Role:** Manages Git repositories, issues, pull requests, webhooks, and CI integration.

### Context

- API base: `https://git.dev.local/api/v1/`
- Auth: Bearer token from `~/agents/tokens/gitea.token`
- Bot user: `openclaw-bot` (Gitea user with admin privileges)
- SSH: `git@localhost:2222`
- CI integration: Woodpecker CI (Gitea OAuth)

### Capabilities

- Create and manage repositories
- Create and manage issues and pull requests
- Manage webhooks (push, PR, release events)
- Manage organizations and teams
- Query commit history and diffs
- Manage repository settings and branch protection
- Trigger CI/CD via Woodpecker

### Activation

```
Deleguj na DevOpsAgent: [popis ukolu]
```

### Skills Reference

See [SKILLS.md](SKILLS.md) for all callable actions.
