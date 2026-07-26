# ONLYOFFICE Document Server — Agent Definition

## OnlyOfficeSystem

- **System:** ONLYOFFICE Document Server (`nos.b2b.onlyoffice`, b2b stack)
- **Domain:** `office.{{ tenant_domain }}` (default `dev.local`)
- **Purpose:** Editing **backend** for DOCX/XLSX/PPTX, embedded by host apps (Nextcloud, BookStack, Outline). It is infrastructure, not a user-facing app — nobody logs in here directly.
- **Auth:** two-layer. Authentik `forward_auth` (tier 3) gates the UI (`/welcome`, admin); the API is JWT-signed with the shared `onlyoffice_jwt_secret`.

### Context

- Image `onlyoffice/documentserver:9.3.1.2` (or the euro-office fork); host port `3015` (loopback) → `:80`. Network alias `onlyoffice` — host apps reach it as `http://onlyoffice/`.
- Embedded PostgreSQL (transient doc-server state only); optional shared Redis.
- Health: `GET /healthcheck` → `true` (unauthenticated).

### Skill surface

None nOS-managed. It is a JWT-secured backend driven by the host apps, with no per-user login and no nOS-provisioned agent credential. See [SKILLS.md](SKILLS.md).

### Data sensitivity

Handles document edits and collaboration sessions in transit (GDPR: legitimate interests, EU-residency, 365-day retention). Documents themselves are persisted by the host apps, not here.
