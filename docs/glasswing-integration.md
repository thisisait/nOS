# Glasswing Integration

> What the State & Migration Framework adds to Glasswing — the views, the widgets, the
> REST API, and how the data gets there. Glasswing is the read model for framework state.
> Spec: [framework-plan.md §6](framework-plan.md#6-glasswing-integration-agents-7--8).

---

## Table of contents

- [Purpose](#purpose)
- [URL map](#url-map)
- [Views](#views)
  - [/migrations](#migrations)
  - [/migrations/<id>](#migrationsid)
  - [/upgrades](#upgrades)
  - [/upgrades/<service>](#upgradesservice)
  - [/timeline](#timeline)
  - [/coexistence](#coexistence)
- [Widgets](#widgets)
- [REST API](#rest-api)
- [Data flow](#data-flow)
- [Auth model](#auth-model)
- [Styling conventions](#styling-conventions)
- [See also](#see-also)

---

## Purpose

Glasswing already serves as the security-research dashboard (vulnerability reports,
pentest journal, advisory feed). The framework extends it with four views that answer:

- **What's pending?** — migrations, upgrades, breaking changes queued for the next run
- **What's installed?** — service × version matrix with upgrade availability
- **What just happened?** — live event stream from the Ansible callback plugin
- **What's dual-running?** — active coexistence tracks, TTL countdowns, cutover controls

Glasswing is **read + command**, not a scheduler. Clicking "Apply migration" calls
BoxAPI, which invokes `ansible-playbook` in-process. Glasswing does not run Ansible itself.

---

## URL map

| Route | Presenter | Method | What it shows |
|---|---|---|---|
| `/migrations` | `MigrationsPresenter:default` | GET | Pending + applied migrations, card grid |
| `/migrations/<id>` | `MigrationsPresenter:detail` | GET | Single migration, step status, event timeline |
| `/upgrades` | `UpgradesPresenter:default` | GET | Service × version matrix |
| `/upgrades/<service>` | `UpgradesPresenter:service` | GET | All recipes for one service |
| `/timeline` | `TimelinePresenter:default` | GET | Merged event stream, filter chips |
| `/coexistence` | `CoexistencePresenter:default` | GET | Active tracks, cutover controls |
| `/api/v1/events` | `Api:EventsPresenter:create` | POST | Ingestion from callback plugin (HMAC) |
| `/api/v1/events` | `Api:EventsPresenter:list` | GET | Paginated query |
| `/api/v1/migrations` | `Api:MigrationsPresenter` | GET/POST | Proxied to BoxAPI |
| `/api/v1/upgrades` | `Api:UpgradesPresenter` | GET/POST | Proxied to BoxAPI |
| `/api/v1/state` | `Api:StatePresenter` | GET | Proxied to BoxAPI `/api/state` |
| `/api/v1/coexistence` | `Api:CoexistencePresenter` | GET/POST | Proxied to BoxAPI |

Routes are declared in `app/router.php` (or via attribute routing per Nette convention).

---

## Views

### `/migrations`

Two-column card grid. Left: **pending**. Right: **applied**.

```
┌─────────────────────────────────── /migrations ───────────────────────────────────┐
│                                                                                   │
│  PENDING (2)                            │   APPLIED (7)                           │
│  ───────────────                        │   ──────────────                        │
│                                         │                                         │
│  ┌─ [breaking] ───────────────────┐     │   ┌─ [breaking] ✓ ────────────────┐     │
│  │ 2026-04-22-devboxnos-to-nos    │     │   │ 2026-03-01-dockerd-bind-move  │     │
│  │ Rebrand devBoxNOS → nOS        │     │   │ Applied 2026-03-02 11:15      │     │
│  │ 4 steps · ~30s downtime        │     │   │ 4 steps · 8s                  │     │
│  │ [Preview] [Apply] [Details]    │     │   │ [View] [Rollback]             │     │
│  └────────────────────────────────┘     │   └───────────────────────────────┘     │
│                                         │                                         │
│  ┌─ [minor] ──────────────────────┐     │   ┌─ [minor] ✓ ───────────────────┐     │
│  │ 2026-04-25-ollama-to-ssd       │     │   │ ...                            │     │
│  │ ...                            │     │                                         │
│                                                                                   │
└───────────────────────────────────────────────────────────────────────────────────┘
```

Each card shows:
- Severity badge (patch/minor/breaking, colour-coded)
- Migration id + title
- One-line summary
- Step count + estimated downtime
- Action buttons

**Buttons** (pending cards):
- **[Preview]** — opens modal with dry-run plan
- **[Apply]** — triggers `POST /api/v1/migrations/<id>/apply`
- **[Details]** — navigates to `/migrations/<id>`

**Buttons** (applied cards):
- **[View]** — navigates to `/migrations/<id>`
- **[Rollback]** — triggers `POST /api/v1/migrations/<id>/rollback`, disabled if the
  migration is older than 30 days (configurable via `rollback_window_days`)

### `/migrations/<id>`

Single migration detail page.

Sections:

1. **Header** — id, title, summary, severity badge, author, created_at
2. **Gate status** — applies_if evaluation + each precondition with pass/fail
3. **Steps** — ordered list, each step with:
   - Step id + description
   - Current detect status (would run / would skip)
   - Action type + key args
   - Verify predicates
   - Rollback declaration
   - For applied migrations: step status icon (✓ applied, ⟳ rolled back, ✗ failed)
4. **Events timeline** — all events with this migration's `migration_id` tag, most
   recent first, grouped by run
5. **Raw YAML** — collapsible, the original migration record

The same page serves pending and applied migrations; conditional sections hide
irrelevant controls.

### `/upgrades`

Service × version matrix.

```
┌─────────────────────────────────── /upgrades ─────────────────────────────────────┐
│                                                                                   │
│  Service     Installed   Stable    Latest    Recipe        Status                 │
│  ────────    ──────────  ────────  ────────  ────────────  ──────                 │
│  grafana     11.5.0      11.5.0    12.0.0    11-to-12      ● BREAKING available   │
│  postgresql  16.3        16.3      17.0      16-to-17      ● BREAKING available   │
│  authentik   2026.4.1    2026.4.1  2026.4.1  —             ● current              │
│  mariadb     10.11.6     10.11.6   11.4.0    10-to-11      ● BREAKING available   │
│  redis       7.4.1       7.4.1     7.4.1     —             ● current              │
│  infisical   0.87.2      0.88.0    0.88.0    patch         ● minor available      │
│  ...                                                                              │
│                                                                                   │
└───────────────────────────────────────────────────────────────────────────────────┘
```

Columns:
- **Service** — service id
- **Installed** — from `~/.nos/state.yml#services.<svc>.installed`
- **Stable** — manifest-pinned stable version (what `version_policy=stable` installs)
- **Latest** — upstream latest (polled via `nos_state` from manifest check)
- **Recipe** — matching recipe id, or `—` if no transition defined
- **Status** — colour badge: green (current), blue (patch), yellow (minor), red (breaking), grey (security)

Clicking a row navigates to `/upgrades/<service>`.

### `/upgrades/<service>`

All recipes for one service. Similar to migration detail but showing:

- Service manifest entry + current state
- All recipes (most likely to apply first)
- Changelogs + notes
- [Preview] / [Apply] / [Coexistence] buttons per recipe
- Events for past upgrades of this service

### `/timeline`

Merged event stream. Most recent first, infinite scroll.

```
┌─────────────────────────────────── /timeline ─────────────────────────────────────┐
│                                                                                   │
│  Filter: [× all] [● task] [○ migration] [○ upgrade] [○ coexistence] [○ handler]   │
│  Run: [all runs ▾]      Service: [all ▾]      Severity: [all ▾]                  │
│                                                                                   │
│  12:45:33  task_ok          roles/pazny.grafana                  15ms             │
│  12:45:32  task_changed     roles/pazny.grafana Render override  82ms             │
│  12:45:30  task_ok          roles/pazny.state_manager            5ms              │
│  12:45:25  migration_end    2026-04-22-devboxnos-to-nos success  12340ms          │
│  12:45:24  migration_step_ok rename_oidc_clients                  250ms           │
│  12:45:23  migration_step_ok rename_authentik_groups              180ms           │
│  12:45:22  migration_step_ok bootout_old_launchagents             45ms            │
│  12:45:22  migration_step_ok move_state_dir                       8ms             │
│  12:45:20  migration_start  2026-04-22-devboxnos-to-nos                           │
│  12:45:18  play_start       Playbook                                              │
│  12:45:18  playbook_start   run_id=run_abc123                                     │
│                                                                                   │
│  [Load older...]                                                                  │
│                                                                                   │
└───────────────────────────────────────────────────────────────────────────────────┘
```

Features:
- **Filter chips** — click to toggle event types
- **Run selector** — pin view to a specific `run_id`
- **Service selector** — filter by role (e.g. `pazny.grafana`)
- **Live tail** — while the page is open, new events stream in via 5-second polling
  against `/api/v1/events?since=<last_ts>`
- **Click an event** — expands to show full result JSON

### `/coexistence`

Active dual-version tracks, one section per service.

```
┌─────────────────────────────────── /coexistence ──────────────────────────────────┐
│                                                                                   │
│  grafana                                                      [+ Provision track] │
│  ───────                                                                          │
│  ● legacy    11.5.0    port 3000   /SSD/grafana-legacy    read-only  TTL: 6d 3h   │
│  ● new  [*]  12.0.0    port 3010   /SSD/grafana           active     started 1h   │
│                                                                                   │
│    [Cutover to new ▶]      [Cleanup legacy]                                       │
│                                                                                   │
│  postgresql                                                   [+ Provision track] │
│  ──────────                                                                       │
│  ● legacy [*] 16.3      port 5432   /SSD/postgres         active                  │
│                                                                                   │
│    (single track — not in coexistence)                                            │
│                                                                                   │
└───────────────────────────────────────────────────────────────────────────────────┘
```

`[*]` marks the active track (the one Nginx points at for the public hostname).

**Buttons**:
- **[+ Provision track]** — modal: tag, version, data source. Triggers
  `POST /api/v1/coexistence/<service>/provision`.
- **[Cutover to <tag>]** — typed confirmation modal ("type CUTOVER to proceed"), then
  `POST /api/v1/coexistence/<service>/cutover`.
- **[Cleanup <tag>]** — typed confirmation, refuses if tag is active, then
  `POST /api/v1/coexistence/<service>/cleanup/<tag>`.

The cutover widget (`widget-cutover-confirm.js`) enforces the typed confirmation to
prevent accidental user-traffic reroutes.

---

## Widgets

Embeddable snippets, used on the Dashboard view and optionally on service detail pages.

### `version-health.latte` + `widget-version-health.js`

Top 5 services needing attention (breaking upgrades > minor > patch). Polls
`/api/v1/state` every 30 s.

```
┌─ Version health ─────────────────────┐
│ ● grafana       11.5.0 → 12.0.0  BRK │
│ ● postgresql    16.3 → 17.0      BRK │
│ ● mariadb       10.11 → 11.4     BRK │
│ ● infisical     0.87 → 0.88     MIN  │
│ ● gitea         1.21 → 1.22     PAT  │
│ [view all ▶]                         │
└──────────────────────────────────────┘
```

### `pending-migrations.latte`

One-line banner shown on every page when migrations are pending:

```
⚠ 2 pending migrations: 1 breaking, 1 minor. [Review →]
```

Hidden when `pending.length == 0`.

### `event-stream.latte` + `widget-timeline.js`

Compact event stream for the Dashboard. Last 20 events, live-updating. Clicking
expands to `/timeline`.

---

## REST API

Glasswing exposes `/api/v1/*` endpoints. Most are thin proxies to BoxAPI; events ingestion
is native.

### Events

```bash
# Ingest (from callback plugin; HMAC-authenticated)
curl -X POST https://glasswing.dev.local/api/v1/events \
  -H "Content-Type: application/json" \
  -H "X-Hmac: <signature>" \
  -d '{"ts": "2026-04-22T12:45:20Z", "run_id": "run_abc123", "type": "migration_start", ...}'

# List (token-authenticated)
curl https://glasswing.dev.local/api/v1/events?run_id=run_abc123&limit=50 \
  -H "X-Token: $GLASSWING_TOKEN"

# Filter by type + since
curl "https://glasswing.dev.local/api/v1/events?type=migration_step_ok&since=2026-04-22T00:00:00Z&limit=100" \
  -H "X-Token: $GLASSWING_TOKEN"
```

### Migrations (proxied to BoxAPI)

```bash
# List pending + applied
curl https://glasswing.dev.local/api/v1/migrations \
  -H "X-Token: $GLASSWING_TOKEN"

# Single migration detail
curl https://glasswing.dev.local/api/v1/migrations/2026-04-22-devboxnos-to-nos \
  -H "X-Token: $GLASSWING_TOKEN"

# Preview (dry-run)
curl -X POST https://glasswing.dev.local/api/v1/migrations/2026-04-22-devboxnos-to-nos/preview \
  -H "X-Token: $GLASSWING_TOKEN"

# Apply
curl -X POST https://glasswing.dev.local/api/v1/migrations/2026-04-22-devboxnos-to-nos/apply \
  -H "X-Token: $GLASSWING_TOKEN"

# Rollback
curl -X POST https://glasswing.dev.local/api/v1/migrations/2026-04-22-devboxnos-to-nos/rollback \
  -H "X-Token: $GLASSWING_TOKEN"
```

### Upgrades (proxied to BoxAPI)

```bash
# Matrix
curl https://glasswing.dev.local/api/v1/upgrades \
  -H "X-Token: $GLASSWING_TOKEN"

# Recipes for a service
curl https://glasswing.dev.local/api/v1/upgrades/grafana \
  -H "X-Token: $GLASSWING_TOKEN"

# Plan a specific recipe
curl -X POST https://glasswing.dev.local/api/v1/upgrades/grafana/grafana-11-to-12/plan \
  -H "X-Token: $GLASSWING_TOKEN"

# Apply
curl -X POST https://glasswing.dev.local/api/v1/upgrades/grafana/grafana-11-to-12/apply \
  -H "X-Token: $GLASSWING_TOKEN"
```

### State (proxied to BoxAPI)

```bash
# Full state document
curl https://glasswing.dev.local/api/v1/state -H "X-Token: $GLASSWING_TOKEN"

# Service subset
curl https://glasswing.dev.local/api/v1/state/services -H "X-Token: $GLASSWING_TOKEN"

# Single service
curl https://glasswing.dev.local/api/v1/state/services/grafana -H "X-Token: $GLASSWING_TOKEN"
```

### Coexistence (proxied to BoxAPI)

```bash
# List all tracks
curl https://glasswing.dev.local/api/v1/coexistence \
  -H "X-Token: $GLASSWING_TOKEN"

# Provision
curl -X POST https://glasswing.dev.local/api/v1/coexistence/grafana/provision \
  -H "X-Token: $GLASSWING_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"tag": "new", "version": "12.0.0", "port": 3010, "data_source": "clone_from:legacy"}'

# Cutover
curl -X POST https://glasswing.dev.local/api/v1/coexistence/grafana/cutover \
  -H "X-Token: $GLASSWING_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"target_tag": "new"}'

# Cleanup
curl -X POST https://glasswing.dev.local/api/v1/coexistence/grafana/cleanup/legacy \
  -H "X-Token: $GLASSWING_TOKEN"
```

See [framework-plan.md §5](framework-plan.md#5-boxapi-endpoint-additions-agent-7-coordinates-with-existing-boxapi-role)
for the BoxAPI endpoint definitions these proxy to.

---

## Data flow

```
            Ansible playbook
                    │
                    ▼
     callback_plugins/glasswing_telemetry.py
                    │
                    ▼ HTTP POST (HMAC signed)
        BoxAPI /api/events (:8099)
                    │
                    ▼ writes
     Glasswing SQLite (events table)
                    ▲
                    │ reads
              Glasswing presenters
                    │
                    ▼ renders
                 Latte views
                    │
                    ▼ served by
        Glasswing nginx vhost (:443)
                    │
                    ▼
                  operator
```

When the network to BoxAPI is unavailable, the callback plugin spools events to
`~/.nos/events.jsonl` and replays them on the next successful POST.

Live state (the `/api/v1/state` proxy) reads `~/.nos/state.yml` through BoxAPI on every
request — no caching in Glasswing — so values are always fresh.

---

## Auth model

Two separate secrets:

1. **HMAC for event ingestion.** Shared between the Ansible callback plugin and Glasswing's
   `/api/v1/events` POST endpoint. Stored in Infisical as
   `glasswing/event_ingest_hmac`. Rotate by running `tasks/rotate-hmac.yml`.
2. **Token for UI + API queries.** Per-user token issued via Authentik; presented as
   `X-Token:` header. UI obtains it via the normal SSO flow. API clients (e.g. a scripted
   operator tool) use a service token with `nos-admins` tier.

All mutating endpoints (`POST /apply`, `POST /rollback`, `POST /cutover`, `POST /cleanup`)
require tier-1 (`nos-admins`). Read endpoints require tier-2 (`nos-managers`) or higher.

See [README.md §SSO & RBAC](../README.md#sso--rbac) for the broader tier model.

---

## Styling conventions

Glasswing uses vanilla CSS + vanilla JS — no framework. New assets follow the existing
patterns:

- **Dark theme** — `#0b0f14` bg, `#e6edf3` fg, `#2dd4bf` teal accent
- **Font stack** — Inter for UI, `ui-monospace, SFMono-Regular, Menlo, monospace` for code
- **Severity badges** — `.badge-patch` (green), `.badge-minor` (blue), `.badge-breaking`
  (red), `.badge-security` (magenta)
- **Status icons** — check (ok), refresh (rolled back), cross (failed), clock (pending)
- **Card grid** — `display: grid; gap: 1rem; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));`

Assets live in `files/project-glasswing/www/assets/`:

- `migrations.css` — card grid, severity badges, state icons
- `upgrades.css` — matrix layout, column widths, colour legend
- `timeline.css` — vertical timeline, event type badges
- `coexistence.css` — track status table, TTL countdown
- `widget-version-health.js` — 30 s polling, DOM patching
- `widget-timeline.js` — 5 s polling for tail, infinite scroll
- `widget-cutover-confirm.js` — typed confirmation modal

Templates live in `files/project-glasswing/app/Templates/`:

- `Migrations/default.latte`, `Migrations/detail.latte`
- `Upgrades/default.latte`, `Upgrades/service.latte`
- `Timeline/default.latte`
- `Coexistence/default.latte`
- `@widgets/version-health.latte`
- `@widgets/pending-migrations.latte`
- `@widgets/event-stream.latte`

Reference: open `files/project-glasswing/app/Templates/Dashboard/default.latte` for
layout patterns; mimic the tile + header structure.

---

## See also

- [framework-overview.md](framework-overview.md) — what the framework is
- [framework-plan.md](framework-plan.md) — authoritative spec (§6 for Glasswing specifics)
- [migration-authoring.md](migration-authoring.md) — what drives the `/migrations` view
- [upgrade-recipes.md](upgrade-recipes.md) — what drives the `/upgrades` view
- [coexistence-playbook.md](coexistence-playbook.md) — what drives the `/coexistence` view
- `files/project-glasswing/app/` — presenter + repository source
