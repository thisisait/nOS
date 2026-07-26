# HedgeDoc — Agent Definition

## HedgeDocSystem

- **System:** HedgeDoc collaborative markdown editor (`nos.b2b.hedgedoc`, b2b stack)
- **Domain:** `hedgedoc.{{ tenant_domain }}` (default `dev.local`)
- **Purpose:** Real-time collaborative markdown notes for the operator/team. Notes + edit history in PostgreSQL; uploads on disk.
- **Auth:** Authentik native OIDC (client `nos-hedgedoc`, tier 3). OIDC-only: anonymous access and email registration are disabled; accounts are created on first Authentik login.

### Context

- Image `quay.io/hedgedoc/hedgedoc:1.11.0`; host port `3012` (loopback) → `:3000`.
- PostgreSQL-backed (`hedgedoc` db/user, infra stack). Container liveness is a TCP probe on `:3000`; app status is `GET /status`.
- No post-start setup — the role finishes at compose render/up.

### Skill surface

None nOS-managed. HedgeDoc has no bot account and no nOS-provisioned API token. See [SKILLS.md](SKILLS.md).

### Data sensitivity

Holds document content, edit history, and OAuth session data (GDPR: legitimate interests, EU-residency, 365-day retention). Note bodies are operator/team content behind the Authentik gate.
