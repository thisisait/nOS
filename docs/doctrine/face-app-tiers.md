# nOS-app tiers — the face-to-nOS complexity doctrine

> Canonical decisions for how apps attach to nOS through the **nOS face** and how an
> agent picks the right build recipe. Companion to `docs/archive/nos-face.md` (the face
> epic) and `docs/doctrine/filesystem.md` (the data classes). Crystallized while building
> the first face-native utils (Sticky Notes + personalization), 2026-07-18.

## Why tiers

Every nОS-facing app is **agent-built**. The agent has maximal understanding of nOS (docs
+ KEAP deterministic semantic search) and of the tenant's business/domain (also KEAP). To
build correctly it must first classify the app by **complexity of logic / data /
performance** — that classification selects the agent's **system-prompt profile** and the
**build recipe** (which organs to wire, whether to author a DB/schema/migrations, which
tier the companion app defaults to). Getting the tier right is the difference between a
one-shot success and an over- or under-engineered app.

"UI" is in parentheses throughout: an app may be a **headless scheduled task** (a Pulse
job / cron) with no UI — it is still an nOS app, and it is still **visible + operable via
wing-face** (Wing `/pulse`, `/timeline`, `/agents`).

## The tiers

| Tier | Name | Data / logic | Organs used | Recipe | Companion app |
|---|---|---|---|---|---|
| **F1** | Utils (static + KV) | Small structured per-user state; no schema | **user-state** (`/api/v1/userstate`), optionally **VFS** | One face component + a `usSet/usGet` namespace. No DB, no migrations. | face-native window (dock tile) |
| **F2** | Structured app | Dedicated tables, real files, per-tenant data | **apps_runner** (`apps/<name>.yml`: compose + GDPR + Authentik), Postgres/MariaDB, **VFS**, euro-office | A private submodule: docs + code + **schema + idempotent migrations** + idempotent setup commands. Optional Next.js frontend. Default **RBAC tier-3, promotable**. | apps_runner `wing_system` + `/hub` tile (companion) |
| **F3** | Multi-organ app | Business logic spanning services | **F2 organs +** Infisical (secrets), Woodpecker (CI), Stalwart (email), Authentik/2FAuth (2FA), Nextcloud/RustFS (storage), **AgentKit** (agent steps) | F2 recipe + wiring manifests per organ (each organ has a documented capability block). | companion app + deep-links into the organs it uses |
| **F4** | Flow-defined (no-code) | Event/cron pipelines, little/no bespoke code | **n8n** or **Node-RED** flow definitions | The app IS a flow export + a thin trigger/config manifest. | flow visible in its host; status in wing-face |
| **H** | Headless / cron (orthogonal) | A scheduled job, any tier's data | **Pulse** (`pulse_jobs:`) + whatever it touches | A Pulse job manifest + the script. No UI. | **wing-face** visibility only (Pulse/timeline) |

Tiers compose upward: an F3 app still uses F1 user-state for its per-user prefs and F2's
DB for its records. Pick the **lowest** tier that covers the requirement — the agent's
prompt profile escalates only when a hard requirement (a real schema, a second organ, a
flow engine) forces it.

## Tier F1 — the reference recipe (built 2026-07-18)

The simplest, most common app. **Static UI + the per-user KV store**, nothing else:

- **Backend:** none new. Bone's **user-state** organ — one embedded DB per user at
  `tenants/<slug>/users/<uid>/.face/state.db` (class-3; see `filesystem.md`). Namespaced
  KV/JSON rows (`namespace`, `key`, JSON `value`). Encryptable later (SQLCipher/libSQL keyed
  from Infisical) — the schema + API don't change, only the connection factory.
- **Client:** `usGet/usList/usSet/usDelete(ns, key, value)` (nos-face `src/lib/userstate.ts`).
- **Contract:** each app owns a namespace (`app.<name>`; face itself uses `face.*`). Values
  are small structured data (≤256 KB), **not** blobs — blobs are files (VFS).
- **Examples shipped:** `app.sticky-notes` (Sticky Notes), `face.desktop` (wallpaper/theme
  personalization). Favorite folders, an explorer index, per-app config all follow.

An agent building an F1 app writes exactly one thing: a face component that reads/writes its
namespace. No DB provisioning, no migrations, no GDPR compose gate (the data lives in the
user's own class-3 tree, already covered by the face-base GDPR row).

## Cross-cutting rules (all tiers)

- **Identity is free, never invented.** Apps inherit the Authentik forward-auth identity via
  the face BFF; end users never create accounts or databases for an app. `uid` is always
  pinned server-side (the BFF), never trusted from the browser.
- **The filesystem is the boundary.** Per-user data is class-3 (`users/<uid>/…`), contained
  by realpath-∈-scope in Bone. `.face/` (user-state) sits outside the KEAP fs-sync classes,
  so app state is never ingested as knowledge.
- **Everything is agent-built + operator-supervised.** The agent authors a **private
  submodule** (docs + code + migrations + idempotent commands); a human merges; the playbook
  applies (the `MigrationWriteTool` gate pattern — see `docs/sso-and-attribution.md` and the
  agentic epic). Apps default to **RBAC tier-3, promotable**.
- **Everything is visible in a face.** UI apps appear as companion tiles in nОS face;
  headless jobs appear in wing-face. There is no invisible app.

## Roadmap hooks (not built yet)

- **M4 agent app-builder** (`nos-face/harness/` is the seed contract): an AgentKit
  `AppScaffoldTool` that, given a tier classification, scaffolds the submodule for that tier
  (F1 → a component + namespace; F2 → compose + schema + migrations; …). The tier picks the
  system-prompt profile.
- **user-state encryption**: per-user key from Infisical → SQLCipher/libSQL connection.
- **postMessage picker bridge**: let iframe-embedded (non-face-native) apps call the
  file-picker service.
