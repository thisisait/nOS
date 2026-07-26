# Miniflux — Agent Definition

## MinifluxReader

**System:** Miniflux (iiab stack) — RSS/Atom aggregator.
**Domain:** `rss{host_alias_seg}.{tenant_domain}` (default `rss.dev.local`).
**Role:** Operator-facing feed reader. Human-driven via the web UI behind Authentik SSO.

### Context

- State (subscriptions, read/starred state, sessions) lives in the PostgreSQL
  database `miniflux`; the container holds no data.
- Human access is `native_oidc` (Authentik OAuth2), tier 3.
- Health: `GET /` (DB-aware) — see README.

### Capabilities

- None wired for agents. nOS provisions no agent credential for Miniflux. Miniflux
  ships a REST API upstream, but it requires a user-created API key from the UI
  (Settings → API Keys), which the playbook does not generate.

### For an agent

There is no nOS-provisioned agent surface. See `SKILLS.md`. To automate Miniflux,
a human must first mint an API key in the UI; that is outside the playbook's wiring.
