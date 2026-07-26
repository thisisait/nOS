# BookStack — Agent Definition

## BookStackSystem

- **System:** BookStack wiki (`nos.b2b.bookstack`, b2b stack)
- **Domain:** `bookstack.{{ tenant_domain }}` (default `dev.local`)
- **Purpose:** Operator/team knowledge base — Shelf → Book → Chapter → Page, page revisions, per-user accounts linked to Authentik.
- **Auth:** Authentik native OIDC (client `nos-bookstack`, tier 3). Users are provisioned on first "Sign in with Authentik".

### Context

- Image `lscr.io/linuxserver/bookstack:26.05.2`; host port `3013` (loopback) → `:80`.
- MariaDB-backed (`bookstack` db/user, infra stack); config at `/config/www/.env` inside `{{ nos_data_root }}/platform/services/bookstack/data`.
- Health: `GET /login` → 200.

### Skill surface

None nOS-managed. There is no bot account or nOS-provisioned API token for BookStack — access is per-user interactive OIDC. See [SKILLS.md](SKILLS.md).

### Data sensitivity

Holds wiki content, revision history, user accounts, and OAuth session data (GDPR: legitimate interests, EU-residency, 365-day retention). Treat page content as operator data.
