# Agentic upgrade → migration → coexistence — Phase B implementation spec

> **Status:** Phase A design COMPLETE (2026-06-15, multi-agent design workflow `wijo2jzqc`: 5 grounded codebase maps → 4 parallel designs → 1 synthesis). This is the buildable **Phase B** spec.
> **Vision + the "agents drive, operator supervises" principle:** [agentic-upgrade-migration-coexistence.md](agentic-upgrade-migration-coexistence.md).
>
> Produced by 10 subagents that READ the live codebase. The synthesis corrected the proposals against actual code paths (the non-existent `run_engine` → the real `nos_migrate action=apply`; the upgrade-architect profile contradiction; ALTER-sweep vs `CREATE TABLE` discipline; the already-present `nos:coexistence:write` scope). **Every choice EXTENDS live machinery — no rewrite.**

---

# Phase B Implementation Spec — Agent-Driven recipe → migration → coexistence

**Status:** Phase A synthesis, operator-confirmed vision (`docs/plans/agentic-upgrade-migration-coexistence.md`). Resolves the four parallel proposals into one buildable spec. Every choice EXTENDS live machinery — no rewrite. Grounded against the actual codebase (verified: `nos_coexistence.py` action dispatch, `nos_migrate.py` action enum, `init-db.php` ALTER sweep at L344, `recipe-pr.sh` forge plumbing, `agent.schema.yaml`, `authentik_agent_scopes` already carrying `nos:coexistence:write`, the architect's flat-vs-dir profile contradiction).

---

## 1. Architecture overview

The epic makes the operator's layered model real and **agent-driven end-to-end**. Three layers, four agents, two supervision gates.

```
RECIPE (declarative plan)                    AGENT: upgrade-advisor (queues from existing)
  upgrades/<svc>.yml                          AGENT: upgrade-architect (drafts gaps → forge MR)
   │  validated by upgrade.schema.json                ↑ operator merges recipe MR  ── GATE 1
   ▼
  ── operator clicks "Plan" in Wing /upgrades ──> plan-choice modal ── SUPERVISION POINT
   │        (a) migration in-place      (b) coexisting-with-data-copy
   ▼
MIGRATION (the REAL committed codebase change)   AGENT: migration-author (NEW)
  files/anatomy/migrations/<ISO>-<svc>.yml        reads merged recipe → WRITES the
  + <svc>_version bump in default.config.yml       imperative migration record +
   │  validated by migration.schema.json            version bump → tools/migration-pr.sh
   │                                                 → forge MR  ── operator merges  ── GATE 2
   ▼
COEXISTENCE (parallel track built ON the migration)  AGENT: coexistence orchestrator
  coexistence_tracks (role: primary|secondary)       provision → (data move = the migration's
   │  the migration's apply[] data-transform IS         apply[] run via nos_migrate action=apply)
   │  the cutover procedure                           → toggle-as-primary ⇄ deactivate-secondary
   ▼                                                  → cleanup
  2× in /upgrades with reversible toggle
```

**Who does what (agent-driven; operator + Claude Code supervise):**

| Actor | Role | Supervision |
|---|---|---|
| **upgrade-advisor** (live) | Queues upgrades from EXISTING recipes into `upgrades_planned`. | none needed (propose-only) |
| **upgrade-architect** (live) | Drafts recipes for coverage gaps, opens recipe MR. | **GATE 1**: operator merges the recipe MR on the local GitLab forge |
| **migration-author** (NEW) | Reads a MERGED recipe + the operator's plan-choice, WRITES the real migration record + version bump, opens migration MR. Never applies, never merges, never GitHub. | **GATE 2**: operator merges the migration MR |
| **coexistence orchestrator** (extend existing engine) | Provisions the track built ON the merged migration; the data move at cutover IS the migration's `apply[]` body; drives provision → promote ⇄ deactivate → cleanup. | dry-run-default on every mutating verb; operator confirms in Wing |

**The two supervision gates are the "manual-over-auto for code-writing migrations" rule made structural** (not just doctrine): a coexistence track with `plan_mode='coexist'` is **blocked from provisioning** until its linked `migrations_authored` row reaches `review_status='merged'` (guard **G-PROVISION-MIGRATED**, §5). No agent can flip a recipe to running code without an operator forge-merge.

**The single behavioural correction vs the maps:** the migration's procedure is consumed at cutover via the **existing** `nos_migrate action=apply` (the live migration-engine path, `engine_apply()` resolving by `migration_id`) — NOT a non-existent `run_engine`. The coexistence track records `source_migration_id`; cutover loads that migration record and runs its `apply[]` data-transform against the new track's empty cluster before flipping the pointer.

---

## 2. Data model

All new columns land via the **idempotent ALTER sweep already in `bin/init-db.php`** (the `$addMissingColumns` closure at L344 — `PRAGMA table_info` then `ALTER TABLE ADD COLUMN`). `CREATE TABLE IF NOT EXISTS` is a no-op on a live DB, so **new tables go in `schema-extensions.sql`; new columns on existing tables go in the sweep** (the file's own L72-80 comment documents exactly this). New partial indexes are created **after** the sweep (column must exist first).

### 2.1 New table — `migrations_authored` (the recipe→migration promotion record)

The hub that joins all three islands. Distinct from `migrations_applied` (runtime execution mirror); this is the **authoring/review artifact**.

```sql
-- schema-extensions.sql (CREATE TABLE IF NOT EXISTS — new table, lands here)
CREATE TABLE IF NOT EXISTS migrations_authored (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid            TEXT NOT NULL UNIQUE,            -- UUID4, == the authoring agent_sessions.uuid / actor_action_id
    service         TEXT NOT NULL,                  -- soft FK upgrade_recipes.service
    recipe_id       TEXT NOT NULL,                  -- soft FK upgrade_recipes.recipe_id (the promoted recipe)
    migration_id    TEXT,                           -- files/anatomy/migrations/<ISO>-<slug>.yml id (== filename)
    plan_mode       TEXT NOT NULL DEFAULT 'migration', -- migration | coexist (carried from the plan-choice)
    from_version    TEXT,
    to_version      TEXT,
    severity        TEXT,                           -- patch|minor|breaking|security (mirrors recipe)
    title           TEXT NOT NULL,
    artifact_kind   TEXT NOT NULL DEFAULT 'migration_yaml', -- migration_yaml | recipe_apply_body | role_task
    artifact_path   TEXT,                           -- repo-relative path the MR touches
    forge           TEXT,                           -- gitlab | gitea
    mr_url          TEXT,                           -- LOCAL forge MR/PR URL (NEVER GitHub)
    forge_branch    TEXT,                           -- fix/migration-<svc>-<ts>
    committed_sha   TEXT,                           -- set once review_status=merged
    review_status   TEXT NOT NULL DEFAULT 'draft',  -- draft | in_review | merged | rejected | superseded
    rejected_reason TEXT,
    author_agent    TEXT NOT NULL DEFAULT 'migration-author', -- == actor_id minus "agent:"
    session_uuid    TEXT,                           -- soft FK agent_sessions.uuid (lineage deep-link)
    actor_id        TEXT,                           -- agent:migration-author (or operator on manual promote)
    actor_action_id TEXT,                           -- == session_uuid
    applied_migration_id TEXT,                       -- soft FK migrations_applied.id once it RUNS
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (service, recipe_id, review_status)       -- one live draft/in_review per (svc,recipe); delete-prior to flip
);
CREATE INDEX IF NOT EXISTS idx_mig_authored_service ON migrations_authored (service);
CREATE INDEX IF NOT EXISTS idx_mig_authored_status  ON migrations_authored (review_status);
CREATE INDEX IF NOT EXISTS idx_mig_authored_session ON migrations_authored (session_uuid);
```

The `UNIQUE(service, recipe_id, review_status)` mirrors `upgrades_planned.UNIQUE(service,recipe_id,status)`, so the repo uses the **same delete-prior pattern** as `markPlannedApplied()`/`cancelPlanned()` to flip `draft → in_review → merged` without a collision.

### 2.2 ALTER sweep — `coexistence_tracks` (primary/secondary state machine)

```sql
-- bin/init-db.php $addMissingColumns(db,'coexistence_tracks',[...])
role                 TEXT NOT NULL DEFAULT 'secondary'   -- provisioned|primary|secondary|deactivated|cleaned
lifecycle            TEXT NOT NULL DEFAULT 'provisioned' -- draft|provisioning|provisioned|primary|secondary|deactivated|cleaned
source_migration_id  TEXT                                 -- soft FK migrations_authored.migration_id (built ON)
promoted_at          TEXT
deactivated_at       TEXT
```

`role`/`lifecycle` are the human-facing reversible state; the legacy `active 0/1` stays the live-routing pointer (`active=1 ⟺ role='primary'`) so every existing reader (`idx_coexist_active`, Bone `list_tracks` `row["active"]`, `pendingCutoverCount`) keeps working untouched. The single-version (non-coexistence) case has no `coexistence_tracks` row and is unaffected. The authoritative store remains `~/.nos/state.yml`; `nos_coexistence.py`'s per-track dict gains the matching keys (it already round-trips arbitrary keys via `_get_svc_state`/`_save_state`).

**Single-primary DB invariant** (created AFTER the sweep, same discipline as `idx_events_row_hash`):

```sql
CREATE UNIQUE INDEX IF NOT EXISTS uq_coexist_one_primary
    ON coexistence_tracks (service) WHERE role = 'primary';
```

The toggle writer demotes the old primary → `secondary` **in the same transaction** as it promotes the new one, so this index never trips on a legitimate toggle but blocks any bug that would leave two primaries.

### 2.3 ALTER sweep — `coexistence_planned` (cancel + plan-choice link + data-copy)

```sql
parent_upgrade_id     INTEGER   -- soft FK upgrades_planned.id (the path-(b) plan that spawned this row)
source_migration_uuid TEXT      -- soft FK migrations_authored.uuid (the migration this track is built ON)
data_copy             INTEGER NOT NULL DEFAULT 1  -- 0/1; path (b) "with a copy of the data" → data_source=clone_from:<live>
cancelled_at          TEXT
cancelled_by          TEXT
```

The `cancelled` status is already a documented enum value but **never written** — §5.1 makes it real. `UNIQUE(service,tag,status)` already lets a `cancelled` row coexist with a future `planned`, so the delete-prior trick applies.

### 2.4 ALTER sweep — `upgrades_planned` (the plan-choice branch point)

```sql
plan_mode             TEXT NOT NULL DEFAULT 'migration'  -- migration | coexist
coexistence_planned_id INTEGER                            -- soft FK coexistence_planned.id (set when plan_mode='coexist')
migration_uuid        TEXT                                -- soft FK migrations_authored.uuid
plan_choice_at        TEXT
```

`plan_mode` default `'migration'` means a legacy row reads as today's only behaviour (in-place). The existing `UNIQUE(service,recipe_id,status)` is untouched.

### 2.5 State machine (consolidated)

```
PLAN-CHOICE ── upgrades_planned.plan_mode
   ├─ migration ─→ [--tags upgrade: in-place, no track] ─→ applied
   └─ coexist   ─→ coexistence_planned status=planned
                       ├─ CANCEL ──────────────────────→ cancelled  [terminal]
                       └─ G-PROVISION-MIGRATED (migrations_authored.merged)
                          └─ --tags coexistence ─→ PROVISION
                                role=provisioned, active=0, source_migration_id set
                                  ├─ COPY-DATA (re-runnable) ─→ data_copied_at  (A4/Q3)
                                  │     migration apply[] → SECONDARY cluster; NO flip;
                                  │     re-run right before PROMOTE for freshness
                                  ├─ PROMOTE ─⇄─ role=primary  (POINTER FLIP ONLY, demotes prior)
                                  │                 ↑ reversible (re-promote the other)
                                  │             role=secondary (read_only=1, ttl_until)
                                  ├─ DEACTIVATE [not primary] ─→ role=deactivated (container stopped, data kept)
                                  │             └─ re-PROMOTE possible
                                  └─ CLEANUP (existing destructive) ─→ cleaned [terminal]
                                                (override+vhost+data dir removed, data→.backup-<ts>)
```

Migration-authoring machine (`migrations_authored.review_status`): `draft ──(MR opened)──> in_review ──(operator forge-merge)──> merged` | `──(operator reject)──> rejected` | `──(newer draft)──> superseded`. **`merged` is reachable ONLY through the forge merge** — no agent, no Wing API can flip it (GATE 2).

### 2.6 Event types — the 3-file whitelist sync (NON-NEGOTIABLE, one commit)

Eight new types. Every one MUST be added to **all three** twins in the same commit, or an agent's Bone-proxied POST silently 400s (the 2026-05-17 `remediator_report` incident, documented in `events.py` L56-60):

1. `files/anatomy/bone/events.py` → `VALID_TYPES` Python set
2. `files/anatomy/wing/app/Model/EventRepository.php` → `VALID_TYPES` PHP const
3. `files/anatomy/wing/app/Presenters/Api/EventsPresenter.php` → reads twin #2 in `validateEventPayload()` (the 400 gate — no edit, but it enforces the sync)

| Event type | Emitter | Reuses `events` FK col | result_json |
|---|---|---|---|
| `plan_choice_recorded` | `UpgradesPresenter::actionPlanChoice` | `upgrade_id` | `{service, recipe_id, plan_mode, coexistence_planned_id?, data_copy, port_offset}` |
| `migration_authored` | migration-author agent | `migration_id` (holds uuid) | `{service, recipe_id, migration_uuid, artifact_kind, artifact_path, from_version, to_version}` |
| `migration_pr_opened` | migration-author (via migration-pr.sh) | `migration_id` | `{migration_uuid, forge, mr_url, forge_branch}` |
| `migration_promoted` | operator forge-merge (webhook / `--mark-merged`) | `migration_id` | `{migration_uuid, committed_sha, applied_migration_id?}` |
| `migration_rejected` | operator reject | `migration_id` | `{migration_uuid, rejected_reason}` |
| `coexistence_promote` | toggle-as-primary | `coexist_svc` | `{coexistence_service, from_tag, to_tag, ttl_until}` |
| `coexistence_demote` | deactivate-secondary / implicit demote | `coexist_svc` | `{coexistence_service, tag, from_role, to_role}` |
| `coexistence_cancel` | cancel queued | `coexist_svc` | `{coexistence_service, tag, planned_id, reason}` |

No new `events` columns — all three FK cols (`upgrade_id`, `migration_id`, `coexist_svc`) already exist; `EventRepository::insert` already maps `payload['coexistence_service'] → coexist_svc`.

**Pre-existing drift to reconcile in the SAME change (cheap, prevents a future 400):** Wing's `VALID_TYPES` already carries `patch_*`, `agent_session_*`/`agent_thread_*`/`agent_iteration_*`/`agent_tool_*`/`agent_message`/`agent_grader_decision`/`agent_webhook_*`/`agent_vault_resolved`/`agent_approval_*`/`admin_emergency_*`/`e2e_journey_*` — **absent from Bone's `events.py`**. The migration-author emits through AgentKit (`agent_session_start`…) when run via the runtime, and those traverse Bone. **Backfill the AgentKit + `patch_*` families into `events.py`** so the migration-author's session events don't 400 exactly like the 2026-05-17 incident. Pinned by extending the existing `test_devlog_event_types.py`-style twin-parity gate.

---

## 3. Wing UI

All mutating browser actions inherit Tier-1 via `protected ?int $minAccessTier = 1;` (enforced in `BasePresenter::startup()`) + CSRF via `requirePostMethod()`. **RBAC fix shipped with this epic** (the maps flag it): `CoexistencePresenter` and `MigrationsPresenter` currently declare NO `$minAccessTier` (ungated browser view) — both gain `= 1`, matching `UpgradesPresenter`.

### 3.1 Plan-choice modal (`/upgrades` + `/upgrades/<service>`)

Insert a modal between the "Plan" click and the queue write. Radio **(a) Migration in-place** (default) vs **(b) Coexisting new version with data copy** (enabled only when `recipe.coexistence_supported === true`; disabled with tooltip on the `uptime_kuma 1→2` forward-only case).

**Presenter** — `UpgradesPresenter::actionPlanChoice(string $service, string $recipe)` (Tier-1 inherited):
- reads `plan_mode`, `target_version`, `port_offset` (default 100), `data_copy`, `force` from POST
- calls new repo method `UpgradeRepository::planUpgradeWithMode()` (below)
- `dry_run` defaults **true** when omitted: first POST returns the would-create rows + the migration-prereq status (is there a merged `migrations_authored`?) WITHOUT inserting; operator confirms with `dry_run=false`
- emits `plan_choice_recorded` (Wing-side `EventRepository::insert` directly, like `UsersPresenter`)
- redirects to `Coexistence:default` (mode b) or `Upgrades:default` (mode a) with flash

**Repo** — `UpgradeRepository::planUpgradeWithMode($service,$recipe,$target,$plannedBy,$mode,$portOffset,$dataCopy,$force)`:
- reuses existing `planUpgrade()` (keeps `recipeMismatch()` guard), then stamps `plan_mode`
- for `coexist`: also calls `CoexistenceRepository::planCoexistence()` with a new trailing `?int $parentUpgradeId` arg, writes `coexistence_planned.parent_upgrade_id` + `data_copy`, back-links `upgrades_planned.coexistence_planned_id`
- **wiring:** inject `CoexistenceRepository` into `UpgradeRepository`'s constructor (Nette DI service, no container edits)

**Route** (`RouterFactory.php`, before `upgrades/<service>`, first-match-wins):
```php
$router->addRoute('upgrades/<service>/<recipe>/plan-choice', 'Upgrades:planChoice');
```

**Templates / JS:**
- `app/Templates/Upgrades/@plan-choice-modal.latte` (NEW partial, `{include}`-d into both `default.latte` + `service.latte`) — radio modal, CSRF field, hidden form posting to `{plink Upgrades:planChoice}`
- `default.latte` + `service.latte` — change the Plan control to `data-action="open-plan-choice"` carrying `data-service`, `data-recipe-id`, `data-coexist-supported`, `data-target`; keep the existing `<form>` as a `<noscript>` in-place fallback
- `www/assets/upgrades-plan-choice.js` (NEW, vanilla `data-action` delegation like `migrations.js`) — `open-plan-choice` (populate + toggle the (b) radio off `data-coexist-supported`), `close-plan-choice`, `submit-plan-choice` (sets hidden inputs, submits the real CSRF `<form>` — no `fetch`, preserving the redirect+flash UX)

### 3.2 2×-with-toggle coexistence rows (`/coexistence`)

`CoexistencePresenter` gains `$minAccessTier = 1` and three POST actions; `renderDefault()` reshapes each service into an explicit **primary/secondary pair** + surfaces the **queued rows** (`listPlanned()` — currently NEVER read, gap #4).

**Presenter actions** (Tier-1, CSRF, redirect+flash, proxy to repo → Bone):
- `actionTogglePrimary(string $service)` — body `target_tag`; calls `coexistence->promote()` (BoxAPI passthrough, §5.3) which flips `active_track` + `role` atomically
- `actionDeactivateSecondary(string $service)` — body `tag`; calls `coexistence->deactivate()` (stops container, keeps data)
- `actionCancel(string $service)` — body `tag`; calls `coexistence->cancelPlanned()` (the missing dequeue)

**Repo** (`CoexistenceRepository`):
- `cancelPlanned($service,$tag,$cancelledBy)` — delete-prior `cancelled` row, then `UPDATE … SET status='cancelled', cancelled_at, cancelled_by WHERE status='planned'`; refuse if no `planned` row (pure DB op, no host mutation — a queued row was never provisioned)
- `promote($service,$tag,$dryRun)` + `deactivate($service,$tag,$force,$dryRun)` — BoxAPI passthroughs to the new Bone routes
- extend `planCoexistence()` with trailing `?int $parentUpgradeId`

**Template** — `Coexistence/default.latte` restructures each service into `coex-pair` (primary card + secondary card) with:
- **Toggle as primary** (on non-primary; typed-confirm `PRIMARY` reused from cutover) → `coexistence_promote`
- **Deactivate secondary** (on secondary; `window.confirm`, non-destructive) → `coexistence_demote`
- a `coex-queued` block rendering `listPlanned()` rows each with a **Cancel** button → `coexistence_cancel`

**`/upgrades` matrix 2× rows:** in `UpgradeRepository::matrix()`, when a service has live `coexistence_tracks`, emit **two** matrix rows (role=primary, role=secondary), each with a compact inline toggle that **deep-links** to `/coexistence#<service>` (the authoritative controls live there — no duplicated toggle logic). `default.latte` adds `{if !empty($row['coexist_role'])}` to render the role badge + deep-link.

**Routes** (browser, specific-before-catch-all):
```php
$router->addRoute('coexistence/<service>/toggle-primary', 'Coexistence:togglePrimary');
$router->addRoute('coexistence/<service>/deactivate-secondary', 'Coexistence:deactivateSecondary');
$router->addRoute('coexistence/<service>/cancel', 'Coexistence:cancel');
$router->addRoute('coexistence', 'Coexistence:default');
```

**JS** — extend `widget-cutover-confirm.js` with `toggle-primary` (typed `PRIMARY`), `deactivate-secondary` (`window.confirm`), `cancel-coexist` (`window.confirm`); each posts a real CSRF `<form>` to the browser presenter (operator path) — reserve the API tier for the orchestrator agent.

### 3.3 Recipes / architect / migration-author drafts as reviewable artifacts (with MR link)

Surface `migrations_authored` rows as **proposal cards** — the first place the local-forge MR link ever appears in the UI.

- **New read model** `MigrationAuthoredRepository`: `forService($service)`, `listReviewable()` (`review_status IN ('draft','in_review')`), `setReviewStatus($id,$status)` (`in_review`|`rejected` only — `merged`/`committed_sha` set by the forge webhook, NOT Wing).
- **`/upgrades/<service>`** (`renderService`): `$this->template->drafts = $authored->forService($service)`; a **Proposals** strip above the recipe cards, each card showing `artifact_kind`, `review_status` badge, `author_agent`, a **Review MR →** link (`mr_url`, the local forge), and a **Lineage** link (`/agents/<author>/sessions/<session_uuid>` — `session_uuid == agent_sessions.uuid == events.actor_action_id`).
- **`/migrations`** (`MigrationsPresenter`, now Tier-1): a third "Proposed (agent drafts)" column from `listReviewable()`, each with **Review MR** + Tier-1 `mark-reviewed`/`mark-rejected` buttons. **The operator never merges in Wing** — the MR link sends them to the local GitLab forge to review + merge (GATE 2); Wing only records `in_review`/`rejected`.
- **Producer contract:** the migration-author writes the row via a new bearer-scoped `POST /api/v1/migrations/authored` (`author_agent`/`actor_id` derived from the bearer identity, NEVER body-supplied — same anti-spoof gate as `actionQueue`), emitting `migration_authored` + `migration_pr_opened`. This replaces the lossy "draft into a `conductor_report` event" path.

### 3.4 New UI gates

- `test_coexistence_presenter_tier1.py` — asserts `CoexistencePresenter` + `MigrationsPresenter` declare `$minAccessTier = 1`.
- extend the event-whitelist twin gate to assert all 8 new types in `events.py` + `EventRepository.php`.

---

## 4. Agent roles

### 4.1 The `migration-author` agent (dual profile, BOTH shapes "write + MR")

**Resolve the architect's profile contradiction** (verified: `upgrade-architect/agent.yml:8` says "never writes or commits files" while `system.md:34-35` says "WRITE it … run recipe-pr.sh"). Author migration-author **consistently** as write+MR in both shapes. Files:

- `files/anatomy/agents/migration-author/agent.yml` (AgentKit dir form, validates against `agent.schema.yaml`)
- `files/anatomy/agents/migration-author/system.md`
- `files/anatomy/agents/migration-author/rubric.md`
- `files/anatomy/agents/migration-author.yml` (flat profile + `pulse:` block for `discover-pulse-catalog.py`)

**`agent.yml` key constraints (verified against `state/schema/agent.schema.yaml`):**
- `name: migration-author` (matches `^[a-z][a-z0-9-]{1,38}[a-z0-9]$`)
- `model.primary: anthropic-claude-opus-4-7`, `fallback: openclaw-qwen-coder-32b` (matches `^(anthropic|openclaw|openai|local)-…`)
- `tools[].id: bash-read-only` + `mcp-wing` — **NOT `bash-write`**: AgentKit's `ToolRegistry` registers no `bash-write` impl yet, so the actual file write happens via `pulse-run-agent.sh`'s `claude --permission-mode bypassPermissions` (the exact path the architect uses today). The schema enum lists `bash-write` but it's unimplemented.
- `audit.capability_scopes` (required block): `[mcp.tool_use, wing.read, wing.write, events.write, nos.migration.write, audit.read]` — items match `^[a-z][a-z._-]+$`
- `outcomes.rubric_path: rubric.md`, `max_iterations: 3`
- `exit_code_semantics` (required, pinned by `test_agent_exit_semantics_documented`): exit_0 = nothing to author / already merged-backed; exit_1 = authored + MR opened, awaiting review (HIGH A9 notify); exit_2 = env/forge/auth error (CRITICAL A9 notify)

**`system.md` (the work, in order):** (1) read the named recipe `upgrades/<service>.yml`, confirm the `recipe_id` + that installed matches `from_pattern` via `GET /api/v1/upgrades`; (2) read `state/manifest.yml` for `stack`/`domain_var`/`port_var`; (3) **author** `files/anatomy/migrations/<YYYY-MM-DD>-<service>-<from>-to-<to>.yml` valid against `migration.schema.json` (model on `_template.yml`): `id == filename`, `applies_if` gating on the installed=from track (idempotency — no-op on an already-migrated host), each recipe `apply[]` step → a migration `steps[]` entry with `detect`/`action`/`verify`/`rollback` (carry the recipe `rollback[]`), `post_verify` asserts the new version is live; (4) **bump `<service>_version` in `default.config.yml`** to the recipe `to` (config WINS over the engine's in-place compose-override edit — `upgrades/README.md` caveat; WITHOUT this the upgrade reverts on the next normal run); (5) validate read-only: `pytest -q tests/migrations/` + `ansible-playbook main.yml --syntax-check`, fix-and-retry max 3; (6) `tools/migration-pr.sh <service> <migration-id> --open-pr`; (7) POST the report event `migration_authored`. **Never merge, never GitHub, never run any apply tag, never provision a track.** End with `NOS_AGENT_EXIT: 0|1`.

**Coexistence note in `system.md`:** when the plan-choice `plan_mode=coexist`, author the `apply[]`/`post[]` data-transform steps (e.g. Postgres `pg_dumpall` dump → restore) **isolated and re-runnable against an empty target cluster** — the SAME migration artifact serves both consumers: in-place (`--tags upgrade/migrate` applies it live) and coexistence (its data-transform phase runs against the new track at cutover).

### 4.2 Authentik identity + scopes

- **New scope** in `authentik_agent_scopes` (`default.config.yml` ~L2177): `"nos:migration:write"` (singular "author one migration"; deliberately distinct from the existing plural `nos:migrations:apply` which is the engine apply path). **Declarative until a Bone route enforces it** — the real gate stays the forge MR + operator merge.
- **New client** in `authentik_agent_clients` (~after `nos-upgrade-architect` at L2293): `nos-migration-author`, `client_secret: "{{ global_password_prefix }}_pw_agent_migration_author"`, capabilities `[nos:upgrades:read, nos:state:read, nos:migrations:read, nos:coexistence:read, nos:migration:write]`. `30-agent-clients.yaml.j2` mints provider/app/scopemappings via its data-driven `{% for agent in authentik_agent_clients %}` loop — **zero template edits**.
- **Wing bearer token** in `default.credentials.yml` (~after `upgrade_architect_wing_api_token` at L396): `migration_author_wing_api_token: "{{ global_password_prefix }}_pw_wing_migration_author"`. Provisioned in `roles/pazny.wing/tasks/post.yml` via the existing `provision-token.php --name=migration-author` block + exported `NOS_MIGRATION_AUTHOR_WING_API_TOKEN`.

All new config/cred vars use **stock-Jinja2 + real defaults defined in `default.config.yml`/`default.credentials.yml`** (loaded before the core-up loader), honoring the `{{ vars }}` eager-resolve trap.

### 4.3 Audit lineage (automatic, no new code)

`pulse-run-agent.sh` already wires it: `actor_id = "agent:" + CLIENT_ID` → `agent:nos-migration-author`; `actor_action_id = uuid4()` groups `agent_run_start` + the agent's `migration_authored` + `agent_run_end` into one run. The `migrations_authored` row's `session_uuid`/`actor_action_id` == that uuid, so a single `SELECT WHERE actor_action_id=?` reconstructs the run (A14 audit contract).

### 4.4 The migration MR review gate + the coexistence orchestrator consuming the migration

- **`tools/migration-pr.sh`** (NEW, generalized sibling of `recipe-pr.sh`): signature `<service> <migration-id> [--open-pr] [--base dev] [--forge gitlab|gitea]`; validates via `pytest -q tests/migrations/` + `--syntax-check`; stages **the artifact SET** (`files/anatomy/migrations/<id>.yml` AND `default.config.yml` — `recipe-pr.sh` stages only the single recipe); branch `fix/migration-<svc>-<ts>`, commit `feat(migration): <svc> <from>→<to>`. **Reuses verbatim** (confirmed in `recipe-pr.sh`): `nos_agent_forge` discovery (L114), the `127.0.0.1:${GL_PORT}` `%2F`-dodge (L130-136), base-branch preflight (L168), the never-merge / never-GitHub / never-force-push boundary, the exit-2 forge-unavailable fallback, the `oauth2:${TOKEN}@${DOMAIN}` push URL.
- **`tools/run-migration-author.sh`** (NEW, near-clone of `run-upgrade-architect.sh`): takes positional `<service> <recipe_id>`, exports `NOS_MIGRATION_SERVICE`/`NOS_MIGRATION_RECIPE_ID` into `NOS_AGENT_TASK`, tracks `migrations_authored WHERE review_status='draft'` before/after, verdict 0 GREEN / 1 REVIEW / 2 RED. Pulse `promote-migration` job is `paused: true` (on-demand doctrine).
- **Coexistence consumes the migration at cutover** — extend `nos_coexistence.action_cutover` (and `tasks/coexistence-cutover.yml`): when the track's `source_migration_id` is set, BEFORE flipping `active_track`, run that migration's data-transform via the **existing migration engine** — `nos_migrate action=apply` with `migration_id=<source_migration_id>` and the new track's port/data_dir threaded as engine tokens (the recipe's `pg_dumpall` dump→restore targets the new track's empty cluster). Only after the migration's `verify` passes does cutover flip the pointer. **This reuses `engine_apply()` — there is no `run_engine` action** (the maps' phrasing; the real action enum is `[list, list_pending, preview, apply, rollback, apply_upgrade]`).

### 4.5 Agent gates

`test_agent_schema.py` covers the new dir profile automatically; `test_agent_exit_semantics_documented` pins the exit block. New `tests/migrations/` gate set (schema + idempotency + template-var-resolvable) is the migration twin of `tests/upgrades/` that `migration-pr.sh` runs.

---

## 5. Lifecycle API

All API-tier methods follow the existing `Api\CoexistencePresenter` pattern: `requireMethod('POST')`, `getJsonBody()`, **reject body-supplied identity**, `getActorId() ?: 'api'`, `proxyBoxApi(...)`. Bone gates each. **`nos:coexistence:write` already exists (L2183)** — promote/deactivate/cancel need NO new Bone scope.

| Verb | Method + path (API) | Tier / scope | Payload | Effect | Audit |
|---|---|---|---|---|---|
| **Cancel** | `POST /api/v1/coexistence/<svc>/cancel` | Tier-1 / Wing-DB only | `{tag}` | `cancelPlanned()` — flip `planned`→`cancelled`. **No Bone route, no host mutation** (queued row never provisioned). Refuse if no `planned` row. | `coexistence_cancel` |
| **Plan-choice** | `POST /api/v1/upgrades/<svc>/<recipe>/plan-choice` | Tier-1 / `nos:upgrades:apply` | `{plan_mode, data_source, port_offset, target_version, dry_run}` | `migration`: `planUpgrade(plan_mode='migration')`. `coexist`: + `planCoexistence(parent_upgrade_id)` + back-link + `data_copy`. **dry_run default true.** | `plan_choice_recorded` |
| **Promote** (toggle-as-primary, reversible) | `POST /api/v1/coexistence/<svc>/promote` | Tier-1 / `nos:coexistence:write` | `{tag, dry_run, ttl_seconds}` | Bone `POST /api/coexistence/<svc>/promote/<tag>` → new module action `promote_track` (reuses `action_cutover` mechanics: flip `active_track`+vhost+nginx reload; sets new `role=primary active=1 read_only=0 promoted_at`, prior `role=secondary read_only=1 ttl_until`). Symmetric — re-promoting the other reverts. **dry_run default true.** | `coexistence_promote` |
| **Deactivate** (secondary) | `POST /api/v1/coexistence/<svc>/deactivate` | Tier-1 / `nos:coexistence:write` | `{tag, dry_run, force}` | Bone `POST /api/coexistence/<svc>/deactivate/<tag>` → new module action `deactivate_track`: `role=deactivated lifecycle=deactivated deactivated_at`; remove the track's upstream from the vhost; `docker compose stop` (NOT down — keeps container + data + override). **dry_run default true.** | `coexistence_demote` |
| **Authored** (producer) | `POST /api/v1/migrations/authored` | bearer / `nos:migration:write` | `{service, recipe_id, migration_uuid, artifact_kind, mr_url, forge_branch, session_uuid, summary}` | INSERT `migrations_authored` (anti-spoof `author_agent` from bearer). | `migration_authored` + `migration_pr_opened` |

**Guards:**
- **G-PROVISION-MIGRATED** (the layered-model enforcer): a `coexistence_planned` row with `plan_mode='coexist'` may only provision once its linked `migrations_authored.review_status='merged'`. Enforced in `tasks/coexistence-apply.yml` + the module — refuses until the operator forge-merges (GATE 2).
- **G-PROMOTE-EXISTS / G-PROMOTE-LIFECYCLE / G-PROMOTE-NOOP / G-PROMOTE-HEALTH**: target must be a provisioned/secondary track, not draft/cleaned; promoting the already-primary is a no-op; dry-run surfaces a port-down target (refuse unless `force`).
- **G-DEACTIVATE-NOT-PRIMARY** (critical): refuse to deactivate the `active_track`/`role=primary` unless `force` AND another track exists to fail over to (else 502). **G-DEACTIVATE-LAST**: refuse the only track.
- **Cancel only `status='planned'`**: an `applied` track must go `deactivate` → `cleanup` (the destructive path with its existing force/TTL guards).

**Bone + Ansible additions:** `main.py` 2 new routes (`promote/<tag>`, `deactivate/<tag>`, scope `nos:coexistence:write`); `coexistence.py` `promote()`/`deactivate()` mirroring `cutover`/`cleanup` (`_validate()` regex gate, `invoke_playbook("coexist-promote"|"coexist-deactivate", …)`); `nos_coexistence.py` adds `promote_track`/`deactivate_track` to `choices` (currently `[list_tracks, provision_track, cutover, cleanup_track]` at L109), `run_action` dispatch (L874), and `argument_spec`; new `tasks/coexistence-promote.yml` + `tasks/coexistence-deactivate.yml` (tags `coexist-promote`/`coexist-deactivate` + `never`). CLI bridge `planned-coexistence.php --cancel --service --tag`.

**API gates:** `test_coexistence_state_machine.py` (one-primary invariant, deactivate-primary refusal, cancel-only-planned), `test_plan_choice_persistence.py` (plan_mode / coexistence_planned_id / parent_upgrade_id links).

---

## 6. Build order for Phase B

Sequenced by dependency. **B1–B3 are the foundation (serial); B4a/B4b/B4c parallelize; B5–B6 integrate; B7 is acceptance.**

| Step | Size | Work | Pinning gate(s) | Depends on |
|---|---|---|---|---|
| **B1 — Schema + event twins** | M | `migrations_authored` table; ALTER-sweep columns on `coexistence_tracks`/`coexistence_planned`/`upgrades_planned`; `uq_coexist_one_primary` index; the 8 new event types in all 3 twins + the AgentKit/`patch_*` Bone drift backfill — ALL ONE COMMIT. | extend `test_devlog_event_types.py` twin-parity; new `test_plan_choice_persistence.py` (column presence) | — |
| **B2 — Lifecycle module + Bone** | L | `nos_coexistence` `promote_track`/`deactivate_track` actions + `role`/`lifecycle` state keys + `source_migration_id`; `tasks/coexistence-{promote,deactivate}.yml`; Bone `promote`/`deactivate` routes + impls; `planned-coexistence.php --cancel`. | `test_coexistence_state_machine.py` (one-primary, deactivate-primary refusal, cancel-only-planned) | B1 |
| **B3 — Repos + API tier** | M | `CoexistenceRepository::{cancelPlanned,promote,deactivate}` + `planCoexistence(parent)`; `UpgradeRepository::planUpgradeWithMode` (+ inject `CoexistenceRepository`); `MigrationAuthoredRepository`; `Api\CoexistencePresenter::{actionCancel,actionPromote,actionDeactivate}`; `Api\UpgradesPresenter::actionPlanChoice`; `POST /api/v1/migrations/authored`; routes. | `test_plan_choice_persistence.py` (link writes); contract drift gate | B1, B2 |
| **B4a — migration-author agent** ∥ | M | The 4 profile files; `tools/migration-pr.sh`; `tools/run-migration-author.sh`; `authentik_agent_scopes`+`_clients` entries; `migration_author_wing_api_token`; `provision-token.php` block + env export. | `test_agent_schema.py`, `test_agent_exit_semantics_documented`; new `tests/migrations/` set | B1 (event types) |
| **B4b — Plan-choice UI** ∥ | M | `@plan-choice-modal.latte`; Plan→`open-plan-choice` in both upgrade templates; `upgrades-plan-choice.js`; route. | manual UI smoke (no presenter gate beyond inherited Tier-1) | B3 |
| **B4c — 2×-toggle + drafts UI + RBAC** ∥ | L | `CoexistencePresenter`+`MigrationsPresenter` `$minAccessTier=1` + browser actions; `Coexistence/default.latte` primary/secondary pair + queued rows; `matrix()` 2× rows + deep-link; Proposals strip on `/upgrades/<svc>` + `/migrations` Proposed column; extend `widget-cutover-confirm.js`. | `test_coexistence_presenter_tier1.py` | B3 |
| **B5 — Coexistence-consumes-migration hook** | M | `action_cutover` (+ `coexistence-cutover.yml`): when `source_migration_id` set, run `nos_migrate action=apply migration_id=<…>` against the new track BEFORE the pointer flip; G-PROVISION-MIGRATED in `coexistence-apply.yml`. | `test_coexistence_state_machine.py` (provision-blocked-until-merged) | B2, B4a |
| **B6 — Forge merge → review_status** | S | webhook (or `migration-pr.sh --mark-merged` / next-deploy ingest) flips `migrations_authored.review_status='merged'`+`committed_sha`, emits `migration_promoted`. | (covered by twin gate) | B3, B4a |
| **B7 — pg16→17 acceptance** | M | Run §8 end-to-end on a real blank; capture audit lineage. | the live walkthrough is the gate | all |

**Parallelizable:** B4a / B4b / B4c after B3 lands (independent surfaces — agent profiles vs upgrade UI vs coexistence UI). **Serial spine:** B1 → B2 → B3, and B5 needs both B2 (module) + B4a (the migration artifact + `tests/migrations/`).

**One-commit discipline reminder:** B1's event-type edits MUST touch `events.py` + `EventRepository.php` together (the twin rule); the migration-author's version bump + migration record MUST land in the same MR (the apply-reverts-without-bump caveat).

---

## 7. Open questions / risks — operator decisions (the supervision points)

These are the calls only the operator can make. They become the build's gating questions:

1. **Forge merge → `merged` flip mechanism (B6).** Do you want a **GitLab webhook** into Bone to auto-flip `migrations_authored.review_status='merged'` on MR-merge, or a **pull model** (`migration-pr.sh --mark-merged` run by the operator / a next-deploy ingest pass)? Webhook is more "agent-driven"; pull keeps Bone's inbound surface smaller. (Affects whether Bone gains an inbound forge-webhook route.)

2. **`nos:migration:write` enforcement.** It ships **declarative** (no Bone route enforces it; the forge MR is the real gate). Acceptable for Phase B, or do you want a Bone enforcement surface now? Doctrine says the merge is the gate, so I recommend declarative — confirm.

3. **Plan-choice (b) data-copy timing.** The stateful-env lesson says a MAJOR upgrade boots a **fresh empty cluster** and moves data via logical dump/restore **at cutover** (not a raw clone at provision). So for pg16→17, `data_copy` drives the *cutover* dump/restore, not a provision-time clone. Confirm this is the intended semantics for "coexisting new version WITH a copy of the data" (i.e. the copy lands at toggle-time, not at provision-time) — it's the only correct path for a major Postgres bump.

4. **Toggle reversibility window / TTL.** When you toggle pg17 primary, pg16 becomes secondary with `read_only=1` + a `ttl_until` (default `coexistence_secondary_ttl_days: 7`). Is 7 days the right cooling window before cleanup is allowed, and should re-promoting pg16 (rollback) be a **one-click reverse-toggle** (my design) or require a typed confirm like the forward promote?

5. **Who fires migration-author.** Two entry points exist: a Wing **"Promote to migration"** Tier-1 button (Bone → Pulse job) OR `tools/run-migration-author.sh` (operator/CI). Do you want the Wing button in Phase B, or is the CLI fire sufficient for the first acceptance run (button deferred)?

6. **RBAC tier for the toggle.** I've set toggle-as-primary / deactivate-secondary / cancel to **Tier-1** (parity with `/upgrades`). Confirm — or should the reversible toggle (non-destructive) be Tier-2 while only cleanup stays Tier-1?

7. **`uptime_kuma 1→2` already queued (coexistence_supported=false).** It's in the upgrade queue but is forward-only (no coexistence path). Plan-choice (b) will be disabled for it. Confirm it stays a **migration-only** path (no coexistence offered) — and whether migration-author should author it alongside pg16→17 in the first run or pg-only first.

8. **AgentKit vs pulse-run-agent.sh runtime for migration-author.** The architect runs via `pulse-run-agent.sh` (claude CLI, `bypassPermissions` write). The migration-author writes files too, so I've kept it on that runtime (AgentKit has no `bash-write` impl). Confirm you're OK with the CLI runtime for the writing agent (vs waiting to implement AgentKit `bash-write`).

---

## 8. Postgres 16→17 acceptance walkthrough

The first real end-to-end exercise — every step an agent/operator action visible in Wing with audit lineage; no host hand-poking.

1. **Recipe exists + queued (today, live).** `upgrades/postgresql.yml` ships `16-to-17` (breaking, `coexistence_supported=true`, `port_offset=100`, `pg_dumpall` dump/restore). **upgrade-advisor** already queued it: `upgrades_planned(postgresql, 16-to-17, status=planned)`. Visible on `/upgrades` as a "planned → 17" badge.

2. **Operator picks the path (SUPERVISION POINT).** On `/upgrades`, click **Plan** on postgresql → plan-choice modal → pick **(b) Coexisting, port +100, with data copy** → confirm (`dry_run=false`). `actionPlanChoice` → `planUpgradeWithMode`: stamps `upgrades_planned.plan_mode='coexist'`, inserts `coexistence_planned(service=postgresql, tag='v17', port_offset=100, data_copy=1, parent_upgrade_id=<…>)`, back-links. Emits **`plan_choice_recorded`** (`actor_id` = operator forward-auth username). *No host poking — a Tier-1 CSRF browser action.*

3. **migration-author writes the real migration (agent, GATE 2 setup).** Operator fires `tools/run-migration-author.sh postgresql postgresql-16-to-17` (or the Wing "Promote" button). The agent: reads `upgrades/postgresql.yml`, confirms installed `16.x` matches `from_regex`, authors `files/anatomy/migrations/2026-06-15-postgresql-16-to-17.yml` (`applies_if` installed=16, `steps[]` = backup → `pg_dumpall` dump → fresh-cluster restore with `detect`/`verify`/`rollback`, isolated/re-runnable against an empty target per the coexist note), bumps `postgresql_version: "17"` in `default.config.yml`, validates (`pytest tests/migrations/` + `--syntax-check`), runs `tools/migration-pr.sh postgresql 2026-06-15-postgresql-16-to-17 --open-pr` → **local GitLab MR**. POSTs `migrations_authored(plan_mode='coexist', mr_url, session_uuid, review_status='draft')`. Emits **`migration_authored`** + **`migration_pr_opened`** (`actor_id=agent:nos-migration-author`, `actor_action_id == session_uuid`). Exits 1 → HIGH A9 notify "awaiting your review". The card appears on `/upgrades/postgresql` with **Review MR →** + **Lineage** links.

4. **Operator reviews + merges the MR (GATE 2 — manual-over-auto).** On the local GitLab forge, the operator reviews the imperative migration + the version bump, merges. Webhook (or `--mark-merged`) flips `migrations_authored.review_status='merged'`, sets `committed_sha`, emits **`migration_promoted`**. The migration is now committed code on `dev`.

5. **coexistence orchestrator provisions the track built ON the migration (G-PROVISION-MIGRATED now passes).** `ansible-playbook main.yml --tags coexistence` (or the orchestrator agent): `coexistence-apply.yml` reads the queue, sees `review_status='merged'` → provisions. `nos_coexistence.provision_track` boots a fresh empty pg17 cluster on port `5432+100`, override derived from the legacy `postgresql.yml` block, stamps `coexistence_tracks(service=postgresql, tag='v17', role='provisioned', active=0, source_migration_id='2026-06-15-postgresql-16-to-17')`. Emits **`coexistence_provision`**. `/coexistence` now shows postgresql with **primary v16 (active)** + **secondary v17 (provisioned)**.

6. **Copy data into v17 — the manual, re-runnable data move (A4 / Q3).** Operator clicks **Copy data** on the v17 secondary card. `actionCopyData` → Bone `copy-data/v17` → `coexistence-copy-data.yml`: because v17's `source_migration_id` is set, it runs `nos_migrate action=apply migration_id=2026-06-15-postgresql-16-to-17` (the `pg_dumpall` dump from live v16 → restore into v17's empty cluster), threading v17's port/data_path/tag tokens, then stamps `data_copied_at` via `nos_coexistence action=copy_data`. **NO pointer flip** — v16 stays primary. Emits **`coexistence_copy_data`**. Re-runnable: the operator re-runs Copy data right before step 7 to capture the latest data from the advancing live v16. (Guards: G-COPY-HAS-MIGRATION, G-COPY-NOT-PRIMARY, G-COPY-ENGINE.)

7. **Toggle v17 primary — a pure POINTER FLIP (A4 / Q3).** Operator clicks **Toggle as primary** on v17 (typed `PRIMARY`). `actionTogglePrimary` → Bone `promote/v17` → `nos_coexistence.promote_track`: the B5 auto-at-promote hook is REVERTED, so this is a dumb, instantaneous flip — it runs NO migration (the data move already happened in step 6). It flips `active_track='v17'` (atomic state write + zero-downtime nginx/Traefik reload), sets v17 `role=primary active=1 read_only=0`, v16 `role=secondary read_only=1 ttl_until=+<coexistence_secondary_ttl_days>d demoted_from_primary_at=<now>`. Emits **`coexistence_promote`**. `/upgrades` now shows postgresql **TWICE** (primary v17 / secondary v16) with a one-click **Roll back** on v16; `upgrades_planned` flips to `applied`.

8. **Validate, then deactivate the secondary.** After confirming v17 serves traffic, click **Deactivate secondary** on v16 → `deactivate_track` stops the v16 container (data kept, override kept), `role=deactivated`. Emits **`coexistence_demote`**. (Rollback path stays open: re-promote v16 within the TTL — one-click via the `demoted_from_primary_at` rollback button.) Later, **Cleanup** reclaims v16 (`.backup-<ts>` rename) once the TTL elapses.

**Every step** is a visible, audit-lineaged agent/operator action in Wing — `SELECT … WHERE actor_action_id=?` reconstructs each run. No manual `ansible-playbook` dry-run, no `docker exec`, no direct DB write. The previously-invisible queue rows, drafts, MR links, and primary/secondary state all render in the UI.

---

**Files Phase B creates/edits (all absolute):**
- Schema/DB: `/Users/pazny/projects/nOS/files/anatomy/wing/db/schema-extensions.sql`, `/Users/pazny/projects/nOS/files/anatomy/wing/bin/init-db.php`
- Event twins: `/Users/pazny/projects/nOS/files/anatomy/bone/events.py`, `/Users/pazny/projects/nOS/files/anatomy/wing/app/Model/EventRepository.php` (gate: `/Users/pazny/projects/nOS/files/anatomy/wing/app/Presenters/Api/EventsPresenter.php`)
- Module/Bone/tasks: `/Users/pazny/projects/nOS/files/anatomy/library/nos_coexistence.py`, `/Users/pazny/projects/nOS/files/anatomy/bone/main.py`, `/Users/pazny/projects/nOS/files/anatomy/bone/coexistence.py`, `/Users/pazny/projects/nOS/tasks/coexistence-cutover.yml`, `/Users/pazny/projects/nOS/tasks/coexistence-apply.yml`, + NEW `/Users/pazny/projects/nOS/tasks/coexistence-promote.yml`, `/Users/pazny/projects/nOS/tasks/coexistence-deactivate.yml`
- Wing repos/presenters/templates/JS: `app/Model/{UpgradeRepository,CoexistenceRepository}.php` + NEW `app/Model/MigrationAuthoredRepository.php`; `app/Presenters/{UpgradesPresenter,CoexistencePresenter,MigrationsPresenter}.php` + `app/Presenters/Api/{UpgradesPresenter,CoexistencePresenter}.php`; `app/Core/RouterFactory.php`; `app/Templates/Upgrades/{default,service}.latte` + NEW `@plan-choice-modal.latte`; `app/Templates/Coexistence/default.latte`; `app/Templates/Migrations/default.latte`; NEW `www/assets/upgrades-plan-choice.js` + extend `www/assets/widget-cutover-confirm.js`; `bin/planned-coexistence.php`
- Agent: NEW `/Users/pazny/projects/nOS/files/anatomy/agents/migration-author/{agent.yml,system.md,rubric.md}` + `/Users/pazny/projects/nOS/files/anatomy/agents/migration-author.yml`; NEW `/Users/pazny/projects/nOS/tools/migration-pr.sh`, `/Users/pazny/projects/nOS/tools/run-migration-author.sh`
- Config/creds/role: `/Users/pazny/projects/nOS/default.config.yml` (`nos:migration:write` scope + `nos-migration-author` client + coexistence knobs), `/Users/pazny/projects/nOS/default.credentials.yml` (`migration_author_wing_api_token`), `/Users/pazny/projects/nOS/roles/pazny.wing/tasks/post.yml`
- Gates: NEW `tests/anatomy/test_coexistence_presenter_tier1.py`, `tests/anatomy/test_coexistence_state_machine.py`, `tests/anatomy/test_plan_choice_persistence.py`, `tests/migrations/` set; extend the event-whitelist twin gate

**Correction to the proposals folded in:** the cutover-consumes-migration hook uses the **existing** `nos_migrate action=apply` (`engine_apply()`, resolves by `migration_id`) — Proposals 3 & 4's `run_engine` action does not exist (the real enum is `[list, list_pending, preview, apply, rollback, apply_upgrade]`).

---

## 9. Phase B execution — overnight agent-driven build (watcher)

**Authorized by the operator 2026-06-15 as an overnight run.** A session cron watcher (`bd2d6b80`, fires 00:01) launches the Phase B build workflow. Agents build; Claude Code + the operator supervise.

- **Build workflow script:** `/Users/pazny/.claude/projects/-Users-pazny-projects-nOS/phase-b-agentic-upgrade-build.workflow.js`
- **Branch:** `feat/agentic-upgrade-coexistence` (created off the current HEAD, which carries this spec). Built in the main checkout; the operator's prior branch stays preserved in git history.
- **What it builds:** B1→B6 from §6, **sequential** (dependency order, shared working tree — no parallel file races), each step self-verifying its pinning gate(s) + the offline anatomy suite for regressions. Build agents read THIS doc for grounding.
- **Deliverable:** the framework implemented as committed code on the branch + a **review-gated MR on the local GitLab forge** (base `dev`). Morning report at `docs/archive/phase-b-build-report.md`.

### Safety rails (non-negotiable — repeated in every git/host-touching agent prompt)

- **NO merge. NO push to `master`. NO GitHub push** — local GitLab forge only, via the `tools/recipe-pr.sh` plumbing.
- **NO live apply:** no `--tags upgrade` / `--tags coexistence` apply, no `docker`, no `blank`, no live `wing.db` writes, **no live Postgres 16→17 cutover**. **B7 (the live acceptance walkthrough, §8) is EXCLUDED** from the overnight run — it stays operator-supervised.
- Read-only against the live host; all output is code on the branch + the MR.
- **no-interrupt guard:** if a workflow is mid-stage at fire time, the watcher waits for a clean boundary (re-checks ~10 min later).

### Morning supervision

The operator reviews the MR on the local forge, answers the §7 open questions (which gate the final shape), and — once satisfied — merges + runs a **supervised** playbook. Only then can pg16→17 (§8) be driven through the live UI. Nothing in the overnight run touches the live host or merges.

---

## 7-RESOLVED — operator decisions (2026-06-16) + the adjustment round

The §7 open questions were resolved by the operator. The overnight build (`feat/agentic-upgrade-coexistence`, merged to `dev` `d37c5f9f`) shipped the §7 **defaults**; this **adjustment round** applies the four deviations. The build agents for the adjustment round MUST honor these as the source of truth.

**As built (no change needed):**
- **Q1 pull** ✅ — Wing learns of the merge via `migration-pr.sh --mark-merged` / next-deploy ingest; no inbound Bone webhook.
- **Q2 declarative** ✅ — `nos:migration:write` is the agent's audit identity; the forge MR + operator merge is the real gate.
- **Q6 Tier-1 (admin)** ✅ — all coexistence toggle/cancel/copy/promote controls are admin-only.
- **Q7 pg-only first** ✅ — author `postgresql 16→17` only on the first run; `uptime_kuma 1→2` (migration-only, `coexistence_supported=false`) deferred until PG is proven.

**Deviations to BUILD (the adjustment round):**
- **Q8 — AgentKit-native migration-author (was: `pulse-run-agent.sh` CLI).** migration-author runs NATIVELY in AgentKit so it appears in Wing `/agents`, creates `agent_sessions`/`threads`/`iterations`, and emits OTel spans → Grafana `22-ai-agents` + the timeline (one unified runtime for all operational agents). **Requires a NEW gated file-write tool in AgentKit's `ToolRegistry`** — scoped to the repo working tree, PATH-ALLOWLISTED to exactly the migration YAML dir (`files/anatomy/migrations/`) + `default.config.yml`, NO path escape, every write audited (`agent_tool_use`/`agent_tool_result` events). **Security is unchanged: the write tool makes NOTHING live — the review MR + operator merge remains the wall.** Pin the write-tool path-scope + escape-refusal with a security gate.
- **Q5 — Wing "Promote to migration" button → AgentKit (was: CLI-first).** The agent is fired by a Wing `/upgrades` Tier-1 "Promote to migration" button → Bone → AgentKit `run-agent` (NOT the CLI wrapper as the primary path). The CLI wrapper `run-migration-author.sh` may remain as an operator/CI fallback.
- **Q3 — manual "Copy data" action (was: auto data-copy at cutover).** The data move (`pg_dumpall` dump → restore into the secondary's fresh cluster) is an EXPLICIT operator-triggered action in the coexistence/migration UI section, SEPARATE from the promote toggle, and **RE-RUNNABLE** (idempotent into the secondary cluster) so the operator runs it right before promote to capture the latest data. **UNDO the B5 auto-at-cutover hook** — cutover no longer implicitly runs the migration's data-transform; the explicit "Copy data" action does. Flow becomes: provision (empty) → **[operator: Copy data]** → **[operator: Promote primary]**. (Freshness: re-run "Copy data" right before promote; no implicit final-sync coupling.)
- **Q4 — TTL configurable [3,60] default 7; rollback one-click (was: fixed 7).** `coexistence_secondary_ttl_days` is operator-configurable, VALIDATED to the inclusive range **[3, 60]** days, default **7**. Forward promote keeps the typed `PRIMARY` confirm; the **rollback** (re-promote the prior primary) is **ONE-CLICK** (fast, emergency-friendly).

The adjustment round is built agent-driven on `feat/migration-author-agentkit` (off `dev`), review-gated MR, NO live run — same charter as §9. Its build spec is synthesized into `docs/archive/agentic-upgrade-adjustments-design.md`.
