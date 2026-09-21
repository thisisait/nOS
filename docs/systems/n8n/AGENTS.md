# n8n — Agent Definition

## WorkflowAgent

**System:** n8n (iiab stack) — workflow automation, 400+ integration nodes, webhooks.
**Domain:** `n8n{host_alias_seg}.{tenant_domain}` (default `n8n.dev.local`).
**Role:** A visual workflow editor and runtime. Human-authored automations; nOS wires no
agent credential for it.

### Context

- API base: `https://{n8n_domain}/api/v1/`, or `http://127.0.0.1:5678/api/v1/` from the
  host (loopback publish — peer containers cannot reach it).
- **Auth: `X-N8N-API-KEY`, playbook-minted into `~/.nos/secrets.yml` as
  `n8n_api_key`.** post.yml logs in once to mint it; Pulse `n8n-base:exec-watch`
  and pack sync use that key. Do not invent `~/agents/tokens/n8n.token`.
- Filesystem-only state in `/home/node/.n8n` ← `~/n8n` on the host (`database.sqlite`,
  workflow definitions, encrypted credentials) — no external DB.
- Human access is `native_oidc` (Authentik OAuth2 client `nos-n8n`), RBAC tier 2, with a
  playbook-provisioned owner account as the local fallback.
- Loopback surface: `http://127.0.0.1:5678` (the publish the playbook's own post-tasks
  use). Containers cannot reach a host loopback publish.
- Health: `GET /healthz` → `200`.
- SSRF protection is ON (`N8N_SSRF_PROTECTION_ENABLED`), so workflows n8n runs cannot
  reach RFC-1918/loopback peers unless explicitly allowlisted. An agent that expects n8n
  to call another nOS service will be blocked by design.

### Capabilities

- None wired for agents besides pack sync. **nOS mints `n8n_api_key` into
  `~/.nos/secrets.yml`.** Pack graphs stay `active: false` until the operator
  clicks Activate.
- The only playbook-managed credential is the OWNER account
  (`{{ n8n_admin_email }}` / `{global_password_prefix}_pw_n8n`), created by
  `roles/pazny.n8n/tasks/post.yml`. It is an operator credential, not an agent identity.

### For an agent

There is no nOS-provisioned agent surface. See `SKILLS.md` — it documents the upstream
API shape and flags which of the previously-claimed endpoints are unverified, rather than
asserting a callable contract that no credential can reach.

### Skills Reference

See [SKILLS.md](SKILLS.md).
