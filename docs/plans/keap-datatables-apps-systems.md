# KEAP DataTables — "Apps" + "Systems" (the LeanIX-style catalog)

> Design + definitions, 2026-07-18. The catalog substrate for nOS-face and the
> **first real test of the app-gen agent**. Table definitions (SoT in code):
> `state/keap-tables/{apps,systems}.table.yml`. Companion: `docs/doctrine/face-app-tiers.md`
> (the app tiers), `docs/plans/nos-face.md` (the shell).

## Why KEAP DataTable

KEAP already ships a rich, abstract **DataTable(Store)** (Track R2′, contract
`nos-keap/shared/contracts/table.ts`) — exactly the robust, LeanIX-grade substrate we want,
and it's already wired into the knowledge universe:

- **libsql (SQLite) driver** — per owner direction "DataTable(Store) je klíčový; musí být
  dost abstraktní". Other drivers (rustfs/postgres/grist) speak the same contract.
- **Rich columns**: `text/number/boolean/date/select/json/file/vector/taxonomyRef/objectRef/user`,
  each with an OLAP `role` (dimension/measure/attribute) → group-by/aggregate for free.
- **`taxonomyRef` anchors a row into the universe** — the row renders as a body orbiting its
  taxonomy star in `/explore` (asteroid for a table, station for a service).
- **`vector` column = brain-embedding** — a 768-dim nomic-embed-text vector of the row's
  `description` gives free local **deterministic semantic search** across the catalog.
- **Full API**: `POST /api/tables` (create), `POST /api/tables/:id/rows` (upsert),
  `GET …/rows`, `POST …/aggregate`; tier-mapped `visibility`.

So we don't build a catalog — we **define two tables** and seed them from nOS's source of truth.

## The two tables

| | **Apps** (`apps.table.yml`) | **Systems** (`systems.table.yml`) |
|---|---|---|
| LeanIX analogue | Application fact sheet | IT-Component fact sheet |
| Rows are | **agent-generated** business apps + face-native utils | high-level platform systems (Grafana, Kuma, Nextcloud, KEAP, Authentik…) |
| SoT | the app-gen registry (AgentKit harness upserts) | `state/manifest.yml` + plugin `hub_card`/`authentik` blocks + version pins |
| visibility | `tier-users` (everyone sees the catalog) | `tier-managers` (operator inventory) |
| anchor star | `nOS / Applications` | `nOS / Systems` |
| nOS-face UI | **"Apps" desktop icon** — mini dataTable app | **"Systems" folder** — read-mostly inventory |

Both carry the LeanIX spine: `lifecycle` (plan→phase_in→active→phase_out→end_of_life),
`business_criticality`, `status`, classification dimensions, and JSON **relationship** columns
(`organs`/`dependencies`/`depends_on`) that become edges in the universe graph.

## Seeding pipelines

- **Systems** — a playbook task (post-provision, alongside the service registry) walks
  `state/manifest.yml`, enriches each with plugin `hub_card` (icon), `authentik.mode`
  (sso_mode), version pin, stack/kind, and upserts a row keyed by `slug`. Idempotent
  (WHERE-guarded upsert → `changed=0` steady state), like `bin/ingest-registry.php`.
  **Install-gated (owner direction 2026-07-18):** by default only systems that are actually
  installed (`install_* == true`) land in KEAP. The toggle **`keap_nos_full_catalog`**
  (default `false`; `profiles/all-on.yml` sets `true`) mirrors the ENTIRE nOS self-model —
  every system regardless of install state — for a complete architecture map.
- **Apps** — the **app-gen agent** upserts a row when it scaffolds an app, and the nOS-face
  "Apps" UI upserts on enable/disable / on-desktop / description edits. The agent surface is
  **`McpKeapTool`** (AgentKit already has it) extended with table upsert — the "harness in
  AgentKit" the owner asked about. This is what makes agent-built apps **programmatically
  appear in KEAP** and, via the taxonomy anchor + embedding, become searchable + rendered.

Embedding: the `description` → 768-dim vector on upsert (or via the nightly `keap-embed-sync`
Pulse job, same corpus path). Editing an app's description in the face re-embeds it.

## nOS-face UI

- **"Apps"** (desktop icon, a mini DataTable app): lists the Apps table with per-row actions —
  **enable/disable** (`status`), **add to desktop** (`on_desktop`), **edit description**
  (re-embeds for brain search), open (`entry_url`). Enabled + `on_desktop` rows become dock/desktop
  tiles. Reads/writes go face-BFF → KEAP `/api/tables` (uid-pinned, same edge-trust as VFS).
- **"Systems"** (a folder): a different, read-mostly view of the Systems table — health/status,
  SSO mode, version, dependency edges. Operator inventory, not an install surface.

## Agent identity — on-behalf-of, downscoped, fully audited (owner Q, 2026-07-18)

When the app-gen agent upserts an **Apps** row (or touches any organ), it must act as a
**subordinate of the human who triggered it** — separable in the audit, never exceeding that
human's roles. The model (yes, this is arrangeable end-to-end):

- **Authentik**: each agent is a first-class identity (service account) in a `nos-agents`
  group, but **never acts standalone**. Every run is bound to a **principal** (the triggering
  human, or the tenant for autonomous runs) via a delegation token — OAuth2 token-exchange
  (RFC 8693) or an `act` (actor) claim: `sub = agent:X`, `act = { sub: human:Y }`.
- **Downscoping is the invariant**: effective permission = **intersection(agent ceiling,
  principal's roles)**. An agent can never do what its principal can't. Enforced at every
  boundary — Bone `require_scope` (+ `act` ⊆ principal), the **VFS/user-state uid is the
  principal's** (so the agent physically can only touch that human's tree), KEAP table
  visibility = principal's tier, Wing tier = `min(agent, principal)`.
- **No token "bordel"**: ONE ephemeral, short-lived credential minted at session-open (AgentKit
  `CredentialResolver`, `agent_credentials.secret_ref` — never plaintext), scoped to
  `(agent, principal, session)`. Not a pile of long-lived static tokens.
- **Observability = subordinate-of-human**: AgentKit's `actor_id` + `actor_action_id` lineage
  gains an **`on_behalf_of`** (principal) field. Every action → `events` row
  `{ actor_id: agent:X, on_behalf_of: human:Y, actor_action_id: <session> }`. The Grafana
  "agent sessions" view groups agent activity **under the human**: separable by `actor_id`,
  attributed by `on_behalf_of`, and provably within the human's roles. This is a **new design
  doc + roadmap epic** (extends `docs/sso-and-attribution.md`); the table-write surface is its
  first consumer.

## First test of the app-gen agent

This catalog is the **first end-to-end exercise of the app-gen agent**:

1. Agent classifies a request to an app tier (`face-app-tiers.md`), scaffolds the app
   (F1 = static UI + user-state KV; higher tiers add DB/schema/migrations via apps_runner).
2. Agent upserts an **Apps** row via `McpKeapTool` (name, slug, tier, organs, description, …).
3. The row **renders in KEAP** (`/explore`, orbiting the `nOS / Applications` star) and is
   **semantically searchable** (embedding); it appears as a **companion tile** on the nOS-face
   desktop (once enabled + on_desktop).
4. Everything stays operator-supervised (the row + submodule land via the gated write pattern).

## Open items (before wiring the seeders)

- **Agent write surface**: `/api/tables` is the SSO-user route; add an `/agent/v1/tables`
  (bearer, scope-split) in nos-keap, or have `McpKeapTool` present an agent identity. (KEAP change.)
- **Anchor nodes** (owner-confirmed: part of the self-model): `nOS / Applications` +
  `nOS / Systems` are authored by the **self-model generator** (`keap_selfmodel_gen.py` /
  `roles/pazny.keap/tasks/selfmodel.yml`) into the "nOS" constellation, so the anchors exist
  before either table seeds; the seeder resolves `anchors: [nos.applications|nos.systems]` to
  their real node ids.
- **Seeder homes**: Systems → a playbook post-provision task; Apps → the AgentKit `McpKeapTool`
  upsert + the nOS-face "Apps" app.
- **Version note**: nos-keap dev clone is at **v1.9.1**; the pinned/deployed tag is **v1.9.0**
  (GitHub's latest). The DataTable contract is present in both.
