# nOS Integration Map

Compact reference for how the four maintenance suites — **patch**, **migrate**,
**upgrade**, **coexistence** — flow between Ansible, BoxAPI, Glasswing, and
the host state file. Use this as the single page to answer "where does this
event/record actually land?".

Long-form narratives live in [`framework-plan.md`](framework-plan.md),
[`glasswing-integration.md`](glasswing-integration.md), and the per-suite
docs (`migration-authoring.md`, `upgrade-recipes.md`, `coexistence-playbook.md`).

---

## Topology

```
 ┌──────────────────────────────────┐
 │  Ansible playbook  (main.yml)    │
 │  tags: migrate | upgrade |       │
 │        apply-patches |           │
 │        coexist-{provision,...}   │
 └─────────────┬────────────────────┘
               │ emits via callback_plugins/glasswing_telemetry.py
               │ — auto-tags migration_id / upgrade_id / patch_id /
               │   coexistence_service from "[Migrate|Upgrade|Patch|Coexist]"
               │   task-name prefix
               ▼
 ┌──────────────────────────────────┐      ┌───────────────────────────────┐
 │  ~/.nos/state.yml                │      │  ~/.nos/events.sqlite         │
 │  (source of truth on disk)       │      │  (callback fallback when      │
 │    services[]                    │      │   HTTP transport is down)     │
 │    migrations_applied[]          │      └───────────────────────────────┘
 │    upgrades_applied[]            │
 │    patches_applied[]   ← new     │
 │    coexistence{}                 │
 └─────────────┬────────────────────┘
               │ roles/pazny.state_manager/tasks/report.yml
               │   POST /api/state  (full snapshot, X-API-Key)
               ▼
 ┌──────────────────────────────────┐
 │  BoxAPI  (files/boxapi/main.py)  │
 │  :8069   FastAPI + X-API-Key     │
 │                                   │
 │  /api/state              state.py │
 │  /api/events             events.py│
 │  /api/migrations/*    migrations.py│
 │  /api/upgrades/*        upgrades.py│
 │  /api/patches/*   patches.py ← new│
 │  /api/coexistence/*  coexistence.py│
 │                                   │
 │  On apply: subprocess             │
 │    ansible-playbook main.yml      │
 │    --tags <suite> -e <id>=...     │
 └─────────────┬────────────────────┘
               │ HTTP (curl via App\Model\BoxApiClient)
               ▼
 ┌──────────────────────────────────┐
 │  Glasswing  (Nette PHP)          │
 │  :8070   Bearer + proxy auth     │
 │                                   │
 │  SQLite read-mirror:              │
 │    events                         │
 │    migrations_applied             │
 │    upgrades_applied               │
 │    patches_applied   ← new        │
 │    coexistence_tracks             │
 │                                   │
 │  Presenters:                      │
 │    /api/v1/events           ingest│
 │    /api/v1/state/sync       pull  │
 │    /api/v1/migrations/*           │
 │    /api/v1/upgrades/*             │
 │    /api/v1/patches/*    ← new     │
 │    /api/v1/coexistence/*          │
 │    /api/v1/dashboard/summary      │
 │      └── maintenance block ← new  │
 └─────────────┬────────────────────┘
               ▼
 ┌──────────────────────────────────┐
 │  Glasswing Web UI                │
 │  /dashboard /timeline            │
 │  /migrations /upgrades           │
 │  /coexistence   (patches UI TBD) │
 └──────────────────────────────────┘
```

---

## Suite matrix

| Suite | Recipe location | Engine task | BoxAPI | Glasswing read | Glasswing write | State block | Events |
|---|---|---|---|---|---|---|---|
| **migrate** | `migrations/*.yml` | `tasks/pre-migrate.yml` | `/api/migrations/*` | `MigrationRepository` | `POST /api/v1/migrations/<id>/apply` → BoxAPI | `migrations_applied[]` | `migration_start/_step_ok/_step_failed/_end` |
| **upgrade** | `upgrades/<service>.yml` | `tasks/upgrade-engine.yml` | `/api/upgrades/*` | `UpgradeRepository` | `POST /api/v1/upgrades/<svc>/<recipe>/apply` → BoxAPI | `upgrades_applied[]` | `upgrade_start/_step_ok/_end` |
| **patch**   | `patches/PATCH-NNN.yml` | `tasks/apply-patches.yml` | `/api/patches/*` | `PatchRepository` | `POST /api/v1/patches/<id>/apply` → BoxAPI | `patches_applied[]` | `patch_start/_step_ok/_step_failed/_end` |
| **coexist** | (stateful; no recipe files) | `tasks/coexistence-{provision,cutover,cleanup}.yml` | `/api/coexistence/*` | `CoexistenceRepository` | `POST /api/v1/coexistence/<svc>/{provision,cutover,cleanup}` → BoxAPI | `coexistence{}` | `coexistence_provision/_cutover/_cleanup` |

All four suites follow the same contract on the wire: BoxAPI is the only
component that ever invokes `ansible-playbook`. Glasswing never shells out;
it only reads from SQLite (fast) or proxies to BoxAPI (slow-but-authoritative).

---

## What happens when you click "Apply PATCH-001"

1. **Browser** → `POST /api/v1/patches/PATCH-001/apply` with `Authorization: Bearer <token>`.
2. **Glasswing** `PatchesPresenter::actionApply` → `PatchRepository::apply('PATCH-001')` → `BoxApiClient::post('/api/patches/PATCH-001/apply')`.
3. **BoxAPI** `patches_apply` FastAPI route → `files/boxapi/patches.py::apply()` → `migrations.invoke_playbook('apply-patches', {'patch_id': 'PATCH-001'})`.
4. **Subprocess**: `ansible-playbook main.yml --tags apply-patches -e patch_id=PATCH-001`.
5. **`tasks/apply-patches.yml`** runs on `127.0.0.1`:
   - loads `patches/PATCH-001.yml`
   - executes `apply[]` steps (task names prefixed with `[Patch] PATCH-001 | …`)
   - runs `verify[]`; on failure runs `rollback[]`
   - appends a record to `~/.nos/state.yml patches_applied[]` via `nos_state`.
6. **During the run**: `glasswing_telemetry` callback plugin emits `patch_start` → `patch_step_ok|_failed` (one per step) → `patch_end`, each stamped with `patch_id='PATCH-001'` automatically because of the `[Patch]` name prefix. Transport is HTTP → BoxAPI `/api/events` → Glasswing SQLite `events`; if HTTP is down the plugin spools to `~/.nos/events.sqlite` and retries next run.
7. **Post-run**: `pazny.state_manager` role's `report.yml` pushes the updated snapshot to BoxAPI `/api/state`.
8. **Next UI refresh** (or explicit `POST /api/v1/state/sync`): `StatePresenter::actionSync` pulls `/api/state`, iterates `patches_applied[]`, calls `PatchRepository::recordApplied()` for each. Row is deduplicated on `(patch_id, applied_at)` so re-syncing is a no-op.
9. **Dashboard** `GET /api/v1/dashboard/summary` returns the new `maintenance` block with `patches_draft`, `patches_pending`, and related counters.

---

## Event correlation cheatsheet

Every suite tags its events with a suite-specific id so the UI can render a
per-item timeline. The callback plugin auto-detects the tag from the task
name prefix — recipes MUST include it on every dispatched step.

| Task prefix | Sets `events.*` column |
|---|---|
| `[Migrate] <migration-id> | step: …` | `migration_id` |
| `[Upgrade] <service>:<recipe-id> | step: …` | `upgrade_id` |
| `[Patch] PATCH-NNN | step: …` | `patch_id` |
| `[Coexist] <service> | step: …` | `coexist_svc` |

Regexes live in `callback_plugins/glasswing_telemetry.py`: `_MIGRATION_TAG_RE`,
`_UPGRADE_TAG_RE`, `_PATCH_TAG_RE`, `_COEXIST_TAG_RE`.

---

## Extending the map

Adding a new suite follows the same six-step recipe:

1. **DB schema**: add `<suite>_applied` table + an `events.<suite>_id` column
   and index to `files/project-glasswing/db/schema-extensions.sql`.
   Add a sweep for the new column in `bin/init-db.php` (the helper in there
   is reusable).
2. **Glasswing model**: a `<Suite>Repository` with
   `list / getById / statusCount / history / recordApplied (idempotent) /
   getEventsFor / plan / apply` and register it in `app/config/common.neon`.
3. **Glasswing presenter + routes**: one `Api\<Suite>Presenter` + route
   block in `app/Core/RouterFactory.php`. Put specific routes
   (`/history`, `/<id>/plan`, `/<id>/apply`, `/<id>/events`) **before**
   the catch-all `[/<id>]` route.
4. **BoxAPI**: a `files/boxapi/<suite>.py` sibling module with
   `list_all / get_by_id / plan / apply` and 3–4 FastAPI routes in
   `files/boxapi/main.py`.
5. **Ansible engine**: one task file under `tasks/<suite>-engine.yml` (or
   `tasks/apply-<suite>.yml`) gated by `tags: ['<suite>', 'never']` in
   `main.yml` plus a `when: <id-var> is defined` guard.
6. **Callback plugin**: add `_<SUITE>_TAG_RE`, extend
   `_update_synthetic_context`, and surface the new id in `_make_event`'s
   field map. Register the new event types in both
   `state/schema/event.schema.json` and
   `App\Model\EventRepository::VALID_TYPES`.

The patch suite (commits `213824e`, `c257b21`, `6b66967`, `875352c`,
`0845c70`, `2269599`, `a97f64e` and the `feat(glasswing): first-class patch
suite API` commit) is the reference implementation — grep for `PATCH-` and
`_PATCH_TAG_RE` to walk the graph.

---

## See also

- [`framework-plan.md`](framework-plan.md) — full design narrative.
- [`glasswing-integration.md`](glasswing-integration.md) — URL / view / widget catalog.
- [`migration-authoring.md`](migration-authoring.md) — how to write migrations.
- [`upgrade-recipes.md`](upgrade-recipes.md) — how to write upgrade recipes.
- [`coexistence-playbook.md`](coexistence-playbook.md) — dual-version rollouts.
- `patches/_template.yml` — annotated patch recipe template.
