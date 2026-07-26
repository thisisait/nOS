# Paperclip — Agent Definition

## PaperclipAgent

**System:** Paperclip multi-agent orchestration platform (`devops` stack, node `nos.devops.paperclip`)
**Domain:** `paperclip.<tenant_domain>`
**Role:** Administers a Paperclip instance — onboarding, allowed-hostname registration, and the CEO bootstrap invite. Paperclip itself coordinates other AI agents through an org-chart; nOS only manages its lifecycle.

### Context

- No external HTTP admin API is exposed to agents in nOS. Management is the in-container CLI: `docker compose -p devops exec -T paperclip pnpm paperclipai <subcommand>`.
- App auth is better-auth against Paperclip's own user store; the Authentik proxy gate fronts the route but is not wired into the app's login (no trusted-header adapter upstream).
- PostgreSQL (`paperclip` DB) is the backend; `SELECT COUNT(*) FROM account` distinguishes a genuine first run.
- The primary human interface is the browser UI at `https://paperclip.<tenant_domain>`.

### Capabilities

- Non-interactive onboarding of a fresh instance.
- Register allowed hostnames (required or the app refuses requests).
- Bootstrap the first CEO admin (prints an invite URL).

### Constraints

- Every management action runs via `docker compose exec` inside `devops-paperclip-1`, not over the network.
- Loopback HTTP checks must send an allowed `Host` header or the connection is dropped.
- Native OIDC is not consumed by the upstream image — do not assume header-based SSO into the app.

### Skills Reference

See [SKILLS.md](SKILLS.md) for callable actions.
