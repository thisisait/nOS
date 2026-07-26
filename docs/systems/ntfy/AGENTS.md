# ntfy — Agent Definition

## NtfyAgent

**System:** ntfy (push-notifications server, `iiab` stack)
**Node:** `nos.iiab.ntfy`
**Domain:** `ntfy.<tenant_domain>` (default `ntfy.dev.local`)
**Role:** Publishes and subscribes to HTTP pub/sub notification topics. Serves as
an A9 notification sink (`on_critical`/`on_high` route to `ntfy`).

### Context

- Base URL: `https://ntfy.<tenant_domain>` (Authentik forward-auth gated).
- Auth: Authentik session — no ntfy bearer token is provisioned by the playbook.
- Default access is `deny-all`; ntfy has no admin account.
- SSO bucket: `forward_auth`, Tier 3. No native OIDC.
- Internal callers reach the container by name on `iiab_net` / `shared_net`.

### Capabilities

- Publish a message to a topic (title, priority, tags, click-URL).
- Subscribe to / poll a topic (JSON stream, SSE, WebSocket).
- Check server health (`GET /v1/health`).

### Limits

- No message send without a valid Authentik session (default access `deny-all`).
- No per-topic admin API is provisioned; topic ACLs live in ntfy's own `cache.db`.

### Skills Reference

See [SKILLS.md](SKILLS.md) for all callable actions.
