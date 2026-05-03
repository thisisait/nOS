# nOS State & Migration Framework — Implementation Plan

**Status:** Under construction. Agents: this document is the source of truth. Follow it exactly. If a decision point is not covered here, raise it in your final report rather than inventing a convention.

---

## 1. Philosophy

- **Declarative** — state lives in data files, not scripts. Migrations and upgrade recipes are records. The Ansible layer is a thin executor.
- **Replayable** — every applied action can be described, inverted, and re-applied from the record alone.
- **Idempotent** — running the framework against an already-migrated system is a no-op. Every `detect → apply → verify` step is guarded.
- **Observable** — every significant action emits a structured event. Wing is the read model.
- **Coexistence-capable** — breaking changes can run old + new side-by-side with distinct data until the operator flips the cutover flag.
- **Rollback-first** — every forward step declares its inverse. Per-migration rollback, not per-service.

---

## 2. Directory layout (every new path listed, agent owner in brackets)

```
nOS/
├── state/                                      [agent 1]
│   ├── manifest.yml                            # public "expected state" spec
│   ├── schema/
│   │   ├── state.schema.json                   # ~/.nos/state.yml schema
│   │   ├── manifest.schema.json
│   │   ├── migration.schema.json               [agent 1 + 2]
│   │   ├── upgrade.schema.json                 [agent 6]
│   │   └── event.schema.json                   [agent 3]
│   └── README.md
│
├── migrations/                                 [agent 1]
│   ├── README.md
│   ├── _template.yml
│   └── 2026-04-22-devboxnos-to-nos.yml         # retroactive, idempotent
│
├── upgrades/                                   [agent 6]
│   ├── README.md
│   ├── _template.yml
│   ├── grafana.yml
│   ├── postgresql.yml
│   ├── mariadb.yml
│   ├── authentik.yml
│   ├── redis.yml
│   └── infisical.yml
│
├── callback_plugins/                           [agent 3]
│   └── wing_telemetry.py
│
├── library/                                    # custom Ansible modules
│   ├── nos_state.py                            [agent 1]
│   ├── nos_migrate.py                          [agent 2]
│   ├── nos_authentik.py                        [agent 4]
│   └── nos_coexistence.py                      [agent 5]
│
├── roles/pazny.state_manager/                  [agent 1]
│   ├── defaults/main.yml
│   ├── tasks/{main,introspect,persist,report}.yml
│   ├── handlers/main.yml
│   ├── meta/main.yml
│   └── README.md
│
├── tasks/
│   ├── pre-migrate.yml                         [agent 1]  # orchestrator, imported from main.yml (WIRE-UP PENDING)
│   ├── upgrade-engine.yml                      [agent 6]  # per-service upgrade executor
│   ├── coexistence-provision.yml               [agent 5]
│   ├── coexistence-cutover.yml                 [agent 5]
│   ├── coexistence-cleanup.yml                 [agent 5]
│   └── state-report.yml                        [agent 1]  # post-provision: persist state + push
│
├── files/project-wing/
│   ├── app/Presenters/                         [agent 7]
│   │   ├── MigrationsPresenter.php
│   │   ├── UpgradesPresenter.php
│   │   ├── TimelinePresenter.php
│   │   ├── CoexistencePresenter.php
│   │   └── Api/
│   │       ├── MigrationsPresenter.php
│   │       ├── UpgradesPresenter.php
│   │       ├── CoexistencePresenter.php
│   │       ├── EventsPresenter.php             # ingestion
│   │       └── StatePresenter.php              # proxy to ~/.nos/state.yml via Bone
│   ├── app/Model/                              [agent 7]
│   │   ├── EventRepository.php
│   │   ├── MigrationRepository.php
│   │   ├── UpgradeRepository.php
│   │   └── CoexistenceRepository.php
│   ├── app/Templates/
│   │   ├── Migrations/default.latte            [agent 8]
│   │   ├── Migrations/detail.latte             [agent 8]
│   │   ├── Upgrades/default.latte              [agent 8]
│   │   ├── Timeline/default.latte              [agent 8]
│   │   ├── Coexistence/default.latte           [agent 8]
│   │   └── @widgets/                           [agent 8]
│   │       ├── version-health.latte
│   │       ├── pending-migrations.latte
│   │       └── event-stream.latte
│   ├── db/
│   │   └── schema-extensions.sql               [agent 7]  # events, migrations_applied, upgrades_applied, coexistence_tracks tables
│   └── www/assets/                             [agent 8]
│       ├── migrations.css
│       ├── upgrades.css
│       ├── timeline.css
│       ├── coexistence.css
│       └── widget-*.js
│
└── docs/                                       [agent 9]
    ├── framework-plan.md                       # THIS FILE
    ├── framework-overview.md                   # for users
    ├── migration-authoring.md
    ├── upgrade-recipes.md
    ├── coexistence-playbook.md
    └── wing-integration.md
```

**Strict rule for agents:** only write to files under the paths listed above with your agent-number bracket. Do NOT modify `main.yml`, `ansible.cfg`, any existing role, any existing `tasks/*.yml` (except the new ones you own), or any existing Wing presenter. Integration edits will be made by a human operator after all agents finish.

---

## 3. Data schemas

### 3.1 `state/manifest.yml` — public, committed

Declares the *expected* shape of the system. Used by `nos_state` to know which services to introspect.

```yaml
schema_version: 1
nos:
  brand: "nOS"
  engine_name: "nOS"
  public_name: "This is AIT"
  tagline: "the engine behind AIT"
  state_dir: "~/.nos"
  launchd_prefix: "eu.thisisait.nos"
  rbac_group_prefix: "nos-"
  oidc_client_prefix: "nos-"

services:
  - id: grafana
    category: observability
    stack: observability
    version_var: grafana_version
    version_source: docker_image        # docker_image | homebrew | launchd | git_tag | custom
    image: grafana/grafana-oss
    data_path_var: grafana_data_dir
    health_check:
      type: http
      url_template: "https://{{ grafana_domain | default('grafana.dev.local') }}/api/health"
      expect_status: 200
      timeout_sec: 10
    upgrade_recipe: upgrades/grafana.yml
    breaking_boundaries: ["10->11", "11->12"]

  - id: postgresql
    category: database
    stack: infra
    version_var: postgresql_version
    version_source: docker_image
    image: postgres
    data_path_var: postgresql_data_dir
    health_check:
      type: exec
      command: "docker exec nos-postgresql pg_isready -U postgres"
      expect_rc: 0
    upgrade_recipe: upgrades/postgresql.yml
    breaking_boundaries: ["15->16", "16->17"]

  # ... agent 1 must enumerate ALL active services from default.config.yml +
  # roles/pazny.*/defaults/main.yml. Do not hand-roll; introspect.
```

### 3.2 `~/.nos/state.yml` — private, runtime-generated

```yaml
schema_version: 1
generated_at: "2026-04-22T12:32:00Z"
generator: "pazny.state_manager v1.0"
nos_version: "2026.4.22"

instance:
  name: "nos"
  tld: "dev.local"
  role: "standalone"

services:
  grafana:
    installed: "11.5.0"
    desired: "11.5.0"
    data_path: "/Volumes/SSD1TB/observability/grafana"
    healthy: true
    last_restarted: "2026-04-22T12:40:00Z"
    upgrade_available:
      version: "12.0.0"
      severity: breaking
      recipe: grafana-11-to-12

identifiers:
  state_dir: "~/.nos"
  launchd_prefix: "eu.thisisait.nos"
  rbac_group_prefix: "nos-"
  oidc_client_prefix: "nos-"

migrations_applied:
  - id: "2026-04-22-devboxnos-to-nos"
    at: "2026-04-22T12:45:00Z"
    success: true
    duration_sec: 12
    steps_applied: 4
    rolled_back_from: null
    event_run_id: "run_abc123"

last_run:
  run_id: "run_abc123"
  at: "2026-04-22T12:32:00Z"
  tag: "blank"
  recap: { ok: 326, changed: 85, failed: 0, skipped: 9 }

coexistence:
  # Present only when dual-version is active for a service.
  grafana:
    active_track: "new"
    tracks:
      - tag: "legacy"
        version: "11.5.0"
        port: 3000
        data_path: "/Volumes/SSD1TB/observability/grafana-legacy"
        started_at: "2026-04-20T10:00:00Z"
        ttl_until: "2026-04-29T00:00:00Z"
        read_only: true
      - tag: "new"
        version: "12.0.0"
        port: 3010
        data_path: "/Volumes/SSD1TB/observability/grafana"
        started_at: "2026-04-24T09:00:00Z"
        cutover_at: "2026-04-24T10:00:00Z"
```

### 3.3 `migrations/<ISO-date>-<slug>.yml` schema

```yaml
# REQUIRED fields
id: "2026-04-22-devboxnos-to-nos"          # must match filename sans .yml
title: "Rebrand devBoxNOS → nOS"
summary: "Rename user state dir, launchd bundle IDs, Authentik groups, OIDC client IDs."
severity: breaking                          # patch | minor | breaking
authors: ["pazny"]
created_at: "2026-04-22"

# OPTIONAL metadata
tags: [rebrand, identity]
references: ["https://github.com/thisisait/nOS/pull/XX"]
downtime:
  estimated_sec: 30
  services_affected: [authentik, bone]

# GATE — migration is eligible only when applies_if evaluates true
applies_if:
  any_of:
    - { fs_path_exists: "~/.devboxnos" }
    - { launchagent_matches: "com.devboxnos.*" }
    - { authentik_group_exists: "devboxnos-admins" }

# PRECONDITIONS — must ALL pass before any step runs
preconditions:
  - { type: authentik_api_reachable, timeout_sec: 10 }
  - { type: no_active_coexistence }

# STEPS — ordered, each with detect/action/verify/rollback
steps:
  - id: "move_state_dir"
    description: "Rename user state directory"
    detect:
      fs_path_exists: "~/.devboxnos"
    action:
      type: fs.mv
      src: "~/.devboxnos"
      dst: "~/.nos"
    verify:
      - { fs_path_exists: "~/.nos" }
    rollback:
      type: fs.mv
      src: "~/.nos"
      dst: "~/.devboxnos"

  - id: "bootout_old_launchagents"
    description: "Stop and remove legacy launchagents"
    detect:
      launchagents_matching: "com.devboxnos.*"
    action:
      type: launchd.bootout_and_delete
      pattern: "com.devboxnos.*.plist"
      directory: "~/Library/LaunchAgents"
    verify:
      - { launchagents_matching: "com.devboxnos.*", count: 0 }
    rollback:
      type: noop
      reason: "New launchagents under eu.thisisait.nos.* are deployed by playbook; no rollback needed."

  - id: "rename_authentik_groups"
    detect:
      authentik_group_exists: "devboxnos-admins"
    action:
      type: authentik.rename_group_prefix
      from_prefix: "devboxnos-"
      to_prefix: "nos-"
      preserve_members: true
      preserve_policies: true
    verify:
      - { authentik_group_exists: "nos-admins" }
      - { authentik_group_exists: "devboxnos-admins", negate: true }
    rollback:
      type: authentik.rename_group_prefix
      from_prefix: "nos-"
      to_prefix: "devboxnos-"

  - id: "rename_oidc_clients"
    detect:
      authentik_oidc_client_exists: "devboxnos-grafana"
    action:
      type: authentik.rename_oidc_client_prefix
      from_prefix: "devboxnos-"
      to_prefix: "nos-"
    verify:
      - { authentik_oidc_client_exists: "nos-grafana" }
    rollback:
      type: authentik.rename_oidc_client_prefix
      from_prefix: "nos-"
      to_prefix: "devboxnos-"

# Post-migration verification — run once after all steps
post_verify:
  - { type: fs_path_exists, path: "~/.nos/secrets.yml" }
  - { type: authentik_group_exists, name: "nos-admins" }
```

### 3.4 `upgrades/<service>.yml` schema

```yaml
service: grafana
docs_url: "https://grafana.com/docs/grafana/"
recipes:
  - id: "grafana-11-to-12"
    from_regex: "^11\\."
    to: "12.0.0"
    severity: breaking
    changelog_url: "https://grafana.com/docs/grafana/latest/release-notes/release-notes-12-0/"
    notes: |
      Grafana 12 changes dashboard schema for panel options.
      Recommended: export current dashboards before upgrade.
    coexistence_supported: true
    coexistence_port_offset: 10          # new version runs on port + offset

    pre:
      - id: "backup_data"
        type: backup.volume
        src: "{{ grafana_data_dir }}"
        label: "pre-{{ upgrade_id }}"
      - id: "export_dashboards"
        type: http.get_all
        url: "https://{{ grafana_domain | default('grafana.dev.local') }}/api/search"
        auth:
          type: bearer
          token_var: "grafana_admin_api_token"
        save_to: "~/.nos/backups/{{ upgrade_id }}/dashboards.json"

    apply:
      - id: "bump_image_tag"
        type: compose.set_image_tag
        service: grafana
        tag: "{{ recipe.to }}"

    post:
      - id: "wait_healthy"
        type: http.wait
        url: "https://{{ grafana_domain | default('grafana.dev.local') }}/api/health"
        expect_status: 200
        timeout_sec: 90

    rollback:
      - id: "revert_image_tag"
        type: compose.set_image_tag
        service: grafana
        tag: "{{ recipe.from_version_resolved }}"
      - id: "restore_data"
        type: backup.restore
        label: "pre-{{ upgrade_id }}"
```

### 3.5 Callback event schema (`state/schema/event.schema.json`)

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "nOS Ansible Event",
  "type": "object",
  "required": ["ts", "type", "run_id"],
  "properties": {
    "ts":       { "type": "string", "format": "date-time" },
    "run_id":   { "type": "string", "description": "UUID per playbook invocation" },
    "type": {
      "type": "string",
      "enum": [
        "playbook_start", "playbook_end",
        "play_start", "play_end",
        "task_start", "task_ok", "task_changed", "task_failed", "task_skipped", "task_unreachable",
        "handler_start", "handler_ok",
        "migration_start", "migration_step_ok", "migration_step_failed", "migration_end",
        "upgrade_start", "upgrade_step_ok", "upgrade_end",
        "coexistence_provision", "coexistence_cutover", "coexistence_cleanup"
      ]
    },
    "playbook": { "type": "string" },
    "play":     { "type": "string" },
    "task":     { "type": "string" },
    "role":     { "type": ["string", "null"] },
    "host":     { "type": "string" },
    "duration_ms": { "type": "integer" },
    "changed":  { "type": "boolean" },
    "result":   { "type": "object" },
    "migration_id": { "type": ["string", "null"] },
    "upgrade_id":   { "type": ["string", "null"] },
    "coexistence_service": { "type": ["string", "null"] }
  }
}
```

### 3.6 Wing SQLite schema extension (`db/schema-extensions.sql`)

```sql
-- Events from Ansible callback plugin
CREATE TABLE IF NOT EXISTS events (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  ts            TEXT NOT NULL,            -- ISO-8601
  run_id        TEXT NOT NULL,
  type          TEXT NOT NULL,
  playbook      TEXT,
  play          TEXT,
  task          TEXT,
  role          TEXT,
  host          TEXT,
  duration_ms   INTEGER,
  changed       INTEGER,                  -- 0/1
  result_json   TEXT,                     -- JSON blob
  migration_id  TEXT,
  upgrade_id    TEXT,
  coexist_svc   TEXT,
  created_at    TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_events_run_id ON events(run_id);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(type);
CREATE INDEX IF NOT EXISTS idx_events_migration ON events(migration_id);

-- Migration history mirror (source of truth is ~/.nos/state.yml, this is read cache)
CREATE TABLE IF NOT EXISTS migrations_applied (
  id              TEXT PRIMARY KEY,
  title           TEXT NOT NULL,
  severity        TEXT NOT NULL,
  applied_at      TEXT NOT NULL,
  success         INTEGER NOT NULL,      -- 0/1
  duration_sec    INTEGER,
  steps_applied   INTEGER,
  steps_total     INTEGER,
  rolled_back_from TEXT,
  event_run_id    TEXT,
  raw_record_json TEXT                    -- full migration record
);

-- Upgrade history
CREATE TABLE IF NOT EXISTS upgrades_applied (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  service         TEXT NOT NULL,
  recipe_id       TEXT NOT NULL,
  from_version    TEXT,
  to_version      TEXT,
  severity        TEXT,
  applied_at      TEXT NOT NULL,
  success         INTEGER NOT NULL,
  duration_sec    INTEGER,
  rolled_back     INTEGER DEFAULT 0,
  event_run_id    TEXT,
  raw_record_json TEXT
);

-- Coexistence tracks mirror
CREATE TABLE IF NOT EXISTS coexistence_tracks (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  service         TEXT NOT NULL,
  tag             TEXT NOT NULL,
  version         TEXT,
  port            INTEGER,
  data_path       TEXT,
  active          INTEGER,
  read_only       INTEGER,
  started_at      TEXT,
  cutover_at      TEXT,
  ttl_until       TEXT,
  UNIQUE(service, tag)
);
```

---

## 4. Custom Ansible modules (public API)

### 4.1 `library/nos_state.py` — state read/write (agent 1)

```
module: nos_state
actions:
  read:
    args: [state_path="~/.nos/state.yml"]
    returns: { state: dict }
  write:
    args: [state_path, state: dict, merge: bool=true]
    returns: { changed: bool, prior_state: dict, new_state: dict }
  get:
    args: [path: dotted-key, default]
    returns: { value }
  set:
    args: [path, value]
    returns: { changed: bool }
  introspect:
    args: [manifest_path="state/manifest.yml"]
    returns: { services: dict }   # fills in installed versions from docker/homebrew/launchd
```

### 4.2 `library/nos_migrate.py` — migration engine (agent 2)

```
module: nos_migrate
actions:
  list:
    args: [migrations_dir]
    returns: { migrations: [records] }
  list_pending:
    args: [migrations_dir, state]
    returns: { pending: [records] }
  preview:
    args: [migration: record]
    returns: { plan: [actions], would_change: bool }
  apply:
    args: [migration: record, dry_run: bool=false]
    returns: { success: bool, steps_applied: int, failed_step: id?, error?: str }
  rollback:
    args: [migration_id, state]
    returns: { success: bool, steps_rolled_back: int }
```

Action handlers (inside nos_migrate, dispatched by `step.action.type`):

| action type | purpose |
|---|---|
| `fs.mv` | rename file/dir |
| `fs.cp` | copy file/dir |
| `fs.rm` | remove path |
| `fs.ensure_dir` | create dir (mkdir -p) |
| `launchd.bootout_and_delete` | stop + remove launchagent plist(s) by glob |
| `launchd.kickstart` | restart a running launchagent |
| `authentik.rename_group_prefix` | delegate to nos_authentik |
| `authentik.rename_oidc_client_prefix` | delegate to nos_authentik |
| `authentik.migrate_members` | delegate to nos_authentik |
| `docker.compose_override_rename` | rename override yml file in ~/stacks/<stack>/overrides/ |
| `docker.volume_clone` | copy volume data (via docker run --rm + cp, or fs mv if data_path is bind mount) |
| `state.set` | set value in ~/.nos/state.yml (dotted path) |
| `state.bump_schema_version` | increment schema_version |
| `exec.shell` | arbitrary shell (requires explicit `allow_shell: true` in migration) |
| `noop` | do nothing (for rollback of irreversible actions) |

Detect predicate types (same dispatch):

| type | args |
|---|---|
| `fs_path_exists` | path |
| `launchagent_matches` | pattern (glob) |
| `launchagent_count` | pattern, count |
| `authentik_group_exists` | name |
| `authentik_oidc_client_exists` | name |
| `state_schema_version_lt` | version |
| `compose_image_tag_is` | service, tag |
| `all_of`, `any_of`, `not` | list of sub-predicates |

### 4.3 `library/nos_authentik.py` — Authentik API client (agent 4)

```
module: nos_authentik
auth: reads authentik_bootstrap_token from ~/.nos/secrets.yml
endpoint: http://authentik-server:9000/api/v3 (or https://{{ authentik_domain }})
actions:
  list_groups:          returns list of groups
  get_group:            args: [name], returns group or null
  rename_group:         args: [from, to, preserve_members=true, preserve_policies=true]
  rename_group_prefix:  args: [from_prefix, to_prefix]   # applies to all matching
  create_group:         args: [name, attributes]
  delete_group:         args: [name]
  list_oidc_clients:    returns list of Provider/OIDC definitions
  rename_oidc_client:   args: [from, to]
  rename_oidc_client_prefix: args: [from_prefix, to_prefix]
  migrate_members:      args: [from_group, to_group]
  wait_api_reachable:   args: [timeout_sec], returns reachable: bool
```

All idempotent. All use Authentik REST API v3 (see upstream docs). On network error: retry 3× with backoff.

### 4.4 `library/nos_coexistence.py` — dual-version controller (agent 5)

```
module: nos_coexistence
actions:
  list_tracks:
    args: [service?]
    returns: { tracks: {service: [tracks]} }
  provision_track:
    args: [service, tag, version, port, data_path, data_source?]
      # data_source = 'clone_from:<existing_track_tag>' | 'empty'
    returns: { changed, track_record }
    side_effects:
      - renders a compose override file at ~/stacks/<stack>/overrides/<service>-<tag>.yml
      - renders an nginx vhost at nginx/sites-enabled/<service>-<tag>.conf (if web_service)
      - clones data dir if data_source is a clone_from:
  cutover:
    args: [service, target_tag]
    returns: { changed, previous_active, new_active }
    side_effects:
      - updates nginx vhost primary upstream
      - writes coexistence.<service>.active_track = target_tag in ~/.nos/state.yml
      - emits coexistence_cutover event
  cleanup_track:
    args: [service, tag, force=false]
    returns: { changed, removed_data: bool }
    # Refuses to remove active track unless force=true.
    # Deletes compose override, vhost, data dir (with backup label).
```

Supported services (v1): grafana, postgresql, mariadb, authentik, gitea, nextcloud, wordpress. Stateful services require data cloning; stateless just port-shift.

Data cloning strategies:
- **Postgres**: `pg_dump | pg_restore` between tracks
- **MariaDB**: `mariadb-dump | mariadb` between tracks
- **Grafana/Gitea/etc.**: `cp -R` if bind mount, or `docker run --rm -v src:/src -v dst:/dst alpine cp -R /src/. /dst/` if named volume

---

## 5. Bone endpoint additions (agent 7 coordinates with existing bone role)

Existing Bone at `files/bone/main.py` already has `/api/health`, `/api/status`, `/api/run-tag`. Add:

```
GET  /api/state                     -> ~/.nos/state.yml as JSON
GET  /api/state/services            -> services subset
GET  /api/state/services/{id}       -> single service

GET  /api/migrations                -> list { applied: [...], pending: [...] }
GET  /api/migrations/{id}           -> full record (from migrations/*.yml + state)
POST /api/migrations/{id}/preview   -> dry-run, returns plan
POST /api/migrations/{id}/apply     -> invokes ansible-playbook main.yml --tags migrate --extra-vars 'migration_id=<id>'
POST /api/migrations/{id}/rollback  -> invokes ansible-playbook main.yml --tags migrate-rollback --extra-vars 'migration_id=<id>'

GET  /api/upgrades                  -> matrix: service -> {installed, stable, latest, recipe_available?}
GET  /api/upgrades/{service}        -> all recipes for that service
GET  /api/upgrades/{service}/{recipe_id}
POST /api/upgrades/{service}/{recipe_id}/plan
POST /api/upgrades/{service}/{recipe_id}/apply

GET  /api/coexistence               -> list of all tracks
POST /api/coexistence/{service}/provision   -> body: { tag, version, port?, data_source? }
POST /api/coexistence/{service}/cutover     -> body: { target_tag }
POST /api/coexistence/{service}/cleanup/{tag}

POST /api/events                    -> ingestion from callback plugin (HMAC auth)
GET  /api/events                    -> paginated query (?run_id=..., ?type=..., ?since=..., limit=N)
```

Auth model: existing `BONE_SECRET` header on all POST endpoints. `/api/events` POST uses HMAC with shared secret between callback plugin and Bone. GET endpoints require token too (read-sensitive data).

### 5.1 Agent 7 note: Bone extension scope

Agent 7 extends `files/bone/main.py` with the new routes but **does not** restructure the existing code. Add routes via additional `@app.get` / `@app.post` decorators. New helper modules in `files/bone/state.py`, `files/bone/migrations.py`, `files/bone/upgrades.py` for logic.

---

## 6. Wing integration (agents 7 + 8)

### 6.1 Routes (in `app/router.php` or via attribute routing — check Nette convention)

```
/migrations               -> MigrationsPresenter:default
/migrations/<id>          -> MigrationsPresenter:detail
/upgrades                 -> UpgradesPresenter:default
/upgrades/<service>       -> UpgradesPresenter:service
/timeline                 -> TimelinePresenter:default
/coexistence              -> CoexistencePresenter:default

/api/v1/events            -> Api:EventsPresenter:create (POST from callback)
/api/v1/events            -> Api:EventsPresenter:list (GET)
/api/v1/migrations        -> proxy to Bone
/api/v1/upgrades          -> proxy to Bone
/api/v1/state             -> proxy to Bone /api/state
/api/v1/coexistence       -> proxy to Bone
```

### 6.2 Presenter sketches (agent 7 implements full)

```php
// MigrationsPresenter.php
final class MigrationsPresenter extends BasePresenter {
    public function __construct(private MigrationRepository $migrations) { parent::__construct(); }
    public function renderDefault(): void {
        $this->template->pending = $this->migrations->listPending();
        $this->template->applied = $this->migrations->listApplied();
    }
    public function renderDetail(string $id): void {
        $this->template->migration = $this->migrations->get($id);
        $this->template->events = $this->migrations->getEventsFor($id);
    }
}

// Api/EventsPresenter.php — ingestion from callback
final class EventsPresenter extends BaseApiPresenter {
    public function actionCreate(): void {
        $this->checkHmac();
        $payload = $this->getJsonBody();
        // validate against event.schema.json
        $this->eventRepository->insert($payload);
        $this->sendJson(['accepted' => true, 'id' => $lastId]);
    }
    public function actionList(): void {
        $this->checkToken();
        $filters = $this->buildFilters();
        $this->sendJson($this->eventRepository->query($filters, limit: 100));
    }
}
```

### 6.3 Repositories (agent 7)

Each repository wraps SQLite queries and (where applicable) calls Bone for live state.

- `EventRepository` — query events table
- `MigrationRepository` — merge `~/.nos/state.yml` (live) + events + migrations/*.yml (static) — Bone proxy
- `UpgradeRepository` — upgrades/*.yml (static) + state (live) + events
- `CoexistenceRepository` — tracks table + state

### 6.4 Templates (agent 8)

Latte templates. Follow existing Wing styling conventions (see `app/Templates/Dashboard/default.latte` as reference). Keep visual language consistent — dark theme, teal accent, Inter/mono fonts.

Core views:

**Migrations/default.latte** — two-column card grid: pending (left), applied (right). Each card: severity badge (patch/minor/breaking), title, summary, step count, last applied time.

**Migrations/detail.latte** — full record: steps with status icons, events timeline (from callback), diff preview (for file operations), [Preview] / [Apply] / [Rollback] buttons.

**Upgrades/default.latte** — matrix. Rows: services. Columns: installed / stable / latest / upstream. Color code: green (current), blue (upgrade avail), yellow (breaking), red (security-critical).

**Timeline/default.latte** — merged event stream + migration/upgrade history. Filter chips by event type. Pagination.

**Coexistence/default.latte** — per service, list of active tracks with status, [Cutover] button, TTL countdown.

**@widgets/version-health.latte** — small embeddable widget for Dashboard. Top 5 services needing attention.

### 6.5 Frontend assets (agent 8)

- `migrations.css`: card grid, severity badges, state icons
- `upgrades.css`: matrix layout, color legend
- `timeline.css`: vertical timeline, event type badges
- `coexistence.css`: track status, TTL countdown
- `widget-version-health.js`: polling (30s) against `/api/v1/state` for auto-refresh
- `widget-timeline.js`: infinite scroll + filter
- `widget-cutover-confirm.js`: modal with typed confirmation ("type CUTOVER to proceed")

Use vanilla JS (Wing uses no framework). Follow existing `www/assets/dashboard.js` patterns.

---

## 7. Orchestrator task skeletons

### 7.1 `tasks/pre-migrate.yml` (agent 1)

```yaml
---
# Runs in main.yml pre_tasks after preflight, before host roles.
# Safe to run on every playbook invocation — no-op if no pending migrations.

- name: "[Migrate] Read current state"
  nos_state:
    action: read
  register: _nos_state
  tags: ['always', 'migrate']

- name: "[Migrate] Introspect services against manifest"
  nos_state:
    action: introspect
    manifest_path: "{{ playbook_dir }}/state/manifest.yml"
  register: _nos_introspect
  tags: ['always', 'migrate']

- name: "[Migrate] List pending migrations"
  nos_migrate:
    action: list_pending
    state: "{{ _nos_state.state }}"
    migrations_dir: "{{ playbook_dir }}/migrations"
  register: _pending
  tags: ['always', 'migrate']

- name: "[Migrate] Summary"
  ansible.builtin.debug:
    msg: |
      Pending migrations: {{ _pending.pending | length }}
      {% for m in _pending.pending %}
        - [{{ m.severity }}] {{ m.id }} — {{ m.title }}
      {% endfor %}
  when: _pending.pending | length > 0
  tags: ['always', 'migrate']

- name: "[Migrate] Confirm breaking migrations"
  ansible.builtin.pause:
    prompt: |-
      {{ _pending.pending | length }} migration(s) pending, {{ _pending.pending | selectattr('severity', 'eq', 'breaking') | list | length }} breaking.
      Press ENTER to apply, or Ctrl+C then A to cancel.
  when:
    - _pending.pending | selectattr('severity', 'eq', 'breaking') | list | length > 0
    - not (auto_migrate | default(false))
  tags: ['migrate']

- name: "[Migrate] Apply each pending migration"
  nos_migrate:
    action: apply
    migration: "{{ item }}"
    dry_run: "{{ migrate_dry_run | default(false) }}"
  loop: "{{ _pending.pending }}"
  loop_control:
    label: "{{ item.id }}"
  register: _apply_result
  failed_when:
    - _apply_result is defined
    - _apply_result.success is defined
    - not _apply_result.success
  tags: ['migrate']

- name: "[Migrate] Persist updated state"
  nos_state:
    action: write
    merge: true
  tags: ['always', 'migrate']
```

### 7.2 `tasks/upgrade-engine.yml` (agent 6)

Mirrors pre-migrate but loops over eligible upgrades. Triggered with `--tags upgrade --extra-vars 'upgrade_service=grafana upgrade_recipe_id=grafana-11-to-12'` (explicit) or scans `upgrades/*.yml` for `from_regex` matching `state.services.<svc>.installed`.

### 7.3 `tasks/coexistence-{provision,cutover,cleanup}.yml` (agent 5)

Thin wrappers around `nos_coexistence` module. Each takes `coexist_service`, `coexist_tag`, etc. as extra-vars. Run via `--tags coexist-provision` etc.

### 7.4 `tasks/state-report.yml` (agent 1)

Runs in `post_tasks` at end of every playbook. Dumps `~/.nos/state.yml`, POSTs to Bone `/api/state` for Wing cache refresh, emits `playbook_end` event.

---

## 8. Testing expectations

Agents MUST provide at minimum:

- **Agent 1**: `tests/state_manager/` — state roundtrip, introspect matches manifest, retroactive migration detect/skip.
- **Agent 2**: `tests/migrate/` — each action type happy + failure, rollback inverts, idempotency (apply → apply = no second change).
- **Agent 3**: `tests/callback/` — event schema validation, HTTP retry, SQLite fallback on network error.
- **Agent 4**: `tests/authentik/` — group rename preserves members, OIDC client rename preserves bindings. Use HTTP mocks.
- **Agent 5**: `tests/coexistence/` — provision creates override + vhost + data, cutover flips atomically, cleanup refuses active track.
- **Agent 6**: `tests/upgrades/` — schema validation, recipe ordering (pre → apply → post), rollback on failure.
- **Agent 7**: `tests/wing-api/` — minimal PHP tests (PHPUnit style) for each presenter + repository.
- **Agent 8**: frontend smoke test (headless check that /migrations renders without JS errors) — optional.
- **Agent 9**: docs lint (markdownlint), internal link check.

Tests are non-blocking for commit but **must be runnable**. Non-runnable test files fail the agent review.

---

## 9. Agent outputs (what each agent returns at end)

Each agent's final report must include:

1. List of files created / modified (absolute paths)
2. Line counts
3. Any spec ambiguity they resolved + rationale
4. Test run results (if tests were run)
5. Integration hooks they expose (functions / endpoints / modules other agents depend on)
6. Known gaps (things the spec said should be done that weren't, with reason)

---

## 10. Out of scope for this iteration

- CI/CD pipeline for the framework (skip)
- Web UI for authoring new migrations (skip — migrations authored in YAML by hand)
- Distributed / multi-host state (skip — nOS is single-host by design)
- Encryption at rest for state.yml beyond filesystem permissions (skip)
- Cross-version downgrade (skip — downgrade = rollback, which is already modeled)

---

## 11. Sequencing & wire-up (done by human operator after agents finish)

1. Verify all agents completed without errors.
2. Run `ansible-playbook main.yml --syntax-check`.
3. Edit `main.yml` pre_tasks to include `tasks/pre-migrate.yml`.
4. Edit `ansible.cfg` to add `callback_plugins = ./callback_plugins`.
5. Run `ansible-playbook main.yml -K --tags preflight,migrate --check` — dry-run validation.
6. If clean: apply for real on next full playbook run.
7. Commit framework as 5 section commits (state core, migration engine, callback + authentik, coexistence + upgrades, wing). Push.

---

End of plan. Agents: if something ambiguous, stop and report. Do not invent.
