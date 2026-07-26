# Firefly III — Agent Definition

## FireflySystem

- **System:** Firefly III personal finance manager (`nos.b2b.firefly`, b2b stack)
- **Domain:** `firefly.{{ tenant_domain }}` (default `dev.local`)
- **Purpose:** Accounts, transactions, budgets, tags for the operator/team. State lives in MariaDB; uploads/exports on disk.
- **Auth:** Authentik `header_oidc` — proxy outpost injects a trusted identity header, Firefly auto-provisions the local account (`remote_user_guard`). RBAC tier 2 (manager).

### Context

- Image `fireflyiii/core:version-6.2.21`; host port `3014` (loopback) → `:8080`.
- MariaDB (`mysql`) + Redis, both from the infra stack. Network-isolated on `b2b_net` + `gated_b2b_net` (SEC-02) so peers cannot forge the identity header.
- Health: `GET /health` → 200 (only after schema migration + Redis reachable).

### Skill surface

None nOS-managed. Firefly III has a REST API at `/api/v1/*`, but nOS provisions no Personal Access Token for it — access is header-guard interactive only. See [SKILLS.md](SKILLS.md).

### Data sensitivity

Holds financial data: transaction history, account balances, tags, OAuth session data (GDPR: legitimate interests, EU-residency, retention `-1` = kept for the account's life). This is sensitive personal-finance data — never expose it beyond the Authentik gate.
