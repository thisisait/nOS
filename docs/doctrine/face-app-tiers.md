# nOS-app tiers — the face-to-nOS complexity doctrine

> Canonical decisions for how apps attach to nOS through the **nOS face** and how an
> agent picks the right build recipe. Companion to `docs/archive/nos-face.md` (the face
> epic) and `docs/doctrine/filesystem.md` (the data classes). Crystallized while building
> the first face-native utils (Sticky Notes + personalization), 2026-07-18.

## Form — what the thing IS (added 2026-08-07, `docs/idea/13-relations.md` §R3)

This document owns ONE axis — **build**, F1–F4/H, the cost of building an app — and
this section exists to say what it does *not* own, because it used to be asked both
questions at once.

**`form`** is the other axis: what an app IS on screen. Exactly one per app.

| form | what it is | population, measured 2026-08-07 |
|---|---|---|
| `view` | a full window over estate data | 4 — Anatomy, Tables, Explore, Files |
| `utility` | a focused tool with its own state | **0** — §Tier F1 below names Sticky Notes as the reference utility, and it is not in this shell's registry (grepped 2026-08-07). The zero is the finding, not a gap in the table |
| `widget` | a small surface living inside another; **not a window** | 1 — Anatomy at a glance |
| `frame` | a service rendered in an iframe | the hub catalog, ~37 at runtime |

**The two are independent, and only loosely correlated.** A `frame` is usually the
cheapest thing to build and a `view` usually is not — but that is a tendency, not a
definition. The estate already breaks the correlation in both directions: `view` spans
F1 (Files) to F3 (Anatomy, Explore), and F1 is worn by both a view and a widget. Neither
field may be derived from the other; `tests/anatomy/test_face_app_form_axis.py` refuses
a population in which one could be.

**What `form` replaced.** The face recorded one binary — `isNativeApp(slug)`, "a
nos-native API-calling app rather than an iframe", plus a `HubApp.native?: boolean` that
had zero producers and zero consumers for its whole life. A binary answers "component or
iframe" and nothing else, so the first widget — native, component-backed, and not a
window — had no expressible value. `isNativeApp` is deleted; `appForm(slug)` is the
successor and returns `null`, never a guessed `frame`, for an unregistered slug.

**Where each is declared.** Both live on the registry entry
(`files/anatomy/face/src/lib/apps/native/registry.ts`), which is also what
`tools/anatomy-graph-gen.py` harvests into `faceapp:<slug>` nodes. Frames are NOT
harvested: a hub service already has a `service:<id>` node, and a second address for the
same thing is padding.

**Where the VALUES are declared — not here, and not in the face (R4, 2026-08-07).**
`form` and `build` are two of the three adjectives in the genome's `axes` facet
(`state/genome/entity.schema.json`, `definitions.axes`; `layer` is the third).
`tools/genome-codegen.py` emits them into `files/anatomy/module_utils/nos_entity.py`
and `files/anatomy/face/src/lib/contracts/entity.gen.ts`, and both the face and the
anatomy compiler consume the generated vocabulary rather than restating it. This
table is prose about a vocabulary it does not own — adding a fifth form here changes
nothing until the genome declares it. Before that split, nothing anywhere validated
either axis: `form: 'veiw'` compiled into the anatomy graph as a fourth form, and
`formCounts()` seeded its census from four names typed by hand, so a new form would
have been registered, harvested, and silently missing from the count.

**A widget is not a window.** It has no titlebar, no z-order, no snap cell and no entry
in the window store; `launchNative()` refuses to open one. It is mounted by
`WidgetLayer` at the desktop root, which is the whole distinction the form records.

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

## The tiers — the `build` axis

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
