# Upgrade Recipe Authoring Guide

> How to write a per-service upgrade recipe for `nOS`. Recipes move a specific service
> across a breaking version boundary with declared pre / apply / post / rollback phases.
> Authoritative schema: [framework-plan.md §3.4](framework-plan.md#34-upgradesserviceyml-schema).

---

## Table of contents

- [Migrations vs. upgrade recipes](#migrations-vs-upgrade-recipes)
- [File layout](#file-layout)
- [Anatomy of a recipe](#anatomy-of-a-recipe)
- [Phase reference](#phase-reference)
- [Action types for recipes](#action-types-for-recipes)
- [Idempotency for upgrades](#idempotency-for-upgrades)
- [Coexistence support](#coexistence-support)
- [Database upgrade patterns](#database-upgrade-patterns)
  - [PostgreSQL major upgrade (pg_upgrade)](#postgresql-major-upgrade-pg_upgrade)
  - [MariaDB major upgrade (mariadb-upgrade)](#mariadb-major-upgrade-mariadb-upgrade)
  - [Grafana dashboard-preserving upgrade](#grafana-dashboard-preserving-upgrade)
- [Worked examples](#worked-examples)
- [Testing locally](#testing-locally)
- [Common mistakes](#common-mistakes)
- [See also](#see-also)

---

## Migrations vs. upgrade recipes

| | Migration | Upgrade recipe |
|---|---|---|
| **Scope** | Global system state (identifiers, paths, config) | One service, one version transition |
| **Triggered by** | Time — "last run was pre-2026-04-22" | Version — "installed matches from_regex" |
| **Runs** | Automatically in `pre_tasks` | Explicitly by operator, or proposed in Glasswing |
| **Frequency** | Once, ever | Once per version boundary, per service |
| **File** | `migrations/<date>-<slug>.yml` | `upgrades/<service>.yml` |
| **Idempotency gate** | per-step `detect` + `applies_if` | `from_regex` on `state.services.<svc>.installed` |

**Rule of thumb:** if the change is "bump this service from vX to vY", write a recipe.
If the change is "rename every `foo-*` to `bar-*` across the host", write a migration.

See [migration-authoring.md](migration-authoring.md) for migrations.

---

## File layout

```
upgrades/
├── README.md
├── _template.yml
├── grafana.yml
├── postgresql.yml
├── mariadb.yml
├── authentik.yml
├── redis.yml
└── infisical.yml
```

**One file per service.** A file holds a list of `recipes`, each keyed by an `id` that
uniquely identifies a version transition (e.g. `grafana-11-to-12`, `postgresql-16-to-17`).

When a service has multiple concurrent transitions (e.g. Grafana 10→11 *and* 11→12), both
live in the same file and the engine picks the recipe whose `from_regex` matches the
installed version.

---

## Anatomy of a recipe

```yaml
# File: upgrades/grafana.yml
service: grafana                          # must match a service id in state/manifest.yml
docs_url: "https://grafana.com/docs/grafana/"

recipes:
  - id: "grafana-11-to-12"
    from_regex: "^11\\."                  # installed version pattern that triggers this recipe
    to: "12.0.0"                          # target version exactly
    severity: breaking                    # patch | minor | breaking
    changelog_url: "https://grafana.com/docs/grafana/latest/release-notes/release-notes-12-0/"
    notes: |
      Grafana 12 changes dashboard schema for panel options.
      Recommended: export current dashboards before upgrade; the 'pre' phase does this automatically.
    coexistence_supported: true
    coexistence_port_offset: 10           # new version runs on port + 10

    pre:
      - id: "backup_data"
        type: backup.volume
        src: "{{ grafana_data_dir }}"
        label: "pre-{{ upgrade_id }}"

      - id: "export_dashboards"
        type: http.get_all
        url: "https://{{ grafana_domain | default('grafana.dev.local') }}/api/search"
        auth: { type: bearer, token_var: "grafana_admin_api_token" }
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
        tag: "{{ recipe.from_version_resolved }}"    # populated from state at start of apply
      - id: "restore_data"
        type: backup.restore
        label: "pre-{{ upgrade_id }}"
```

### Required fields per recipe

`id`, `from_regex`, `to`, `severity`, `apply`, `post`, `rollback`.

Optional but strongly encouraged: `notes`, `changelog_url`, `pre`, `coexistence_supported`.

---

## Phase reference

A recipe runs in four phases. Each phase is a list of steps; steps run in declaration
order. If any step fails, the engine runs `rollback` (in **declaration order**, not reverse
— rollbacks are declared as a single undo sequence, not per-step inverses).

| Phase | When | Purpose |
|---|---|---|
| `pre` | Before any change | Snapshot data, export config, set read-only flags |
| `apply` | The actual upgrade | Bump image tag, run `pg_upgrade`, rewrite config |
| `post` | After apply | Wait healthy, run data migrations, warm caches |
| `rollback` | If any step in `apply` or `post` fails | Revert image tag, restore data, re-enable old service |

### Phase event emissions

| Event type | When emitted |
|---|---|
| `upgrade_start` | Before `pre` begins |
| `upgrade_step_ok` | After each step completes |
| `upgrade_step_failed` | On step failure |
| `upgrade_end` | After `post` completes, or after `rollback` completes |

Events flow through the same callback plugin as migrations. See
[framework-plan.md §3.5](framework-plan.md#35-callback-event-schema-stateschemaeventschemajson).

---

## Action types for recipes

Recipes share some action types with migrations and add a few upgrade-specific ones.

### Shared with migrations

`fs.*`, `state.*`, `exec.shell` (with `allow_shell: true` + `justification:`), `noop`.
See [migration-authoring.md §Action types reference](migration-authoring.md#action-types-reference).

### Upgrade-specific

| Action type | Purpose | Key args |
|---|---|---|
| `backup.volume` | Snapshot a Docker volume or bind mount to `~/.nos/backups/<label>/` | `src`, `label` |
| `backup.restore` | Restore a labeled backup to its original path | `label` |
| `compose.set_image_tag` | Rewrite the service's image tag in its compose override | `service`, `tag` |
| `compose.restart_service` | `docker compose restart <svc>` | `service`, `stack` |
| `compose.up_wait` | `docker compose up <svc> --wait` | `service`, `stack`, `timeout_sec` |
| `http.get` | HTTP GET, assert status | `url`, `auth`, `expect_status` |
| `http.get_all` | Paginate an API, save aggregated JSON to file | `url`, `save_to` |
| `http.wait` | Poll until status matches | `url`, `expect_status`, `timeout_sec` |
| `http.post` | HTTP POST with body | `url`, `body`, `auth`, `expect_status` |
| `db.pg_dump` | `pg_dump` of a Postgres database into backup dir | `db`, `label` |
| `db.pg_restore` | `pg_restore` from a labeled dump | `db`, `label` |
| `db.pg_upgrade` | Run Postgres major upgrade in a side container | `from_version`, `to_version`, `data_dir` |
| `db.mariadb_dump` | `mariadb-dump` of a database | `db`, `label` |
| `db.mariadb_restore` | Restore a dumped database | `db`, `label` |
| `db.mariadb_upgrade` | Run `mariadb-upgrade` inside the service container | `service` |
| `cache.purge` | Clear an app's cache directory | `path` |

---

## Idempotency for upgrades

Upgrade recipes are idempotent by design:

- **Matching** is driven by `from_regex`. After a successful apply, `state.services.<svc>.installed`
  becomes `to`, which no longer matches `from_regex`. The recipe becomes ineligible.
- **Individual steps** should still use a detect where cheap (e.g. `backup.volume` checks
  whether the label already exists). The engine does not require per-step detect in
  recipes, but strongly prefers it.
- **Re-running a recipe mid-way** (e.g. playbook interrupted during `post`) is safe as
  long as each step is idempotent on its own. The engine re-plays `pre` and `apply`
  steps; their detects short-circuit if the target state is already reached.

---

## Coexistence support

If a recipe sets `coexistence_supported: true`, the operator can provision a second
track side-by-side instead of upgrading in place:

```bash
# In-place
ansible-playbook main.yml -K --tags upgrade -e 'upgrade_service=grafana upgrade_recipe_id=grafana-11-to-12'

# Coexistence
ansible-playbook main.yml -K --tags coexist-provision \
  -e 'coexist_service=grafana coexist_tag=new coexist_version=12.0.0'
# ... test, then ...
ansible-playbook main.yml -K --tags coexist-cutover -e 'coexist_service=grafana coexist_target_tag=new'
```

When the operator invokes coexistence, the engine:

1. Provisions a new track using the recipe's `coexistence_port_offset`.
2. Runs **only** the `pre` + `apply` phases, targeting the new track.
3. Skips `post`'s user-facing health check (the old track is still primary).
4. Runs the `post` checks against the new track after cutover.

Recipes that cannot support coexistence (e.g. a shared-database that only one version
of the service can schema-own at a time) should set `coexistence_supported: false` and
document why in `notes`. See [coexistence-playbook.md](coexistence-playbook.md).

---

## Database upgrade patterns

Databases are the hardest upgrades because they combine stateful data, schema changes,
and strict ordering constraints. The patterns below are battle-tested.

### PostgreSQL major upgrade (pg_upgrade)

Postgres requires `pg_upgrade` for major version bumps (15→16, 16→17). A minor bump
(e.g. 16.3→16.5) is a simple image-tag swap.

```yaml
# File: upgrades/postgresql.yml
service: postgresql
docs_url: "https://www.postgresql.org/docs/current/pgupgrade.html"

recipes:
  # Minor — image swap only
  - id: "postgresql-16-patch"
    from_regex: "^16\\.[0-9]+$"
    to: "{{ postgresql_latest_16_patch }}"
    severity: patch
    coexistence_supported: false

    pre:
      - id: "dump_all"
        type: db.pg_dump
        db: "postgres"
        label: "pre-{{ upgrade_id }}"

    apply:
      - id: "bump_tag"
        type: compose.set_image_tag
        service: postgresql
        tag: "{{ recipe.to }}"
      - id: "restart"
        type: compose.restart_service
        service: postgresql
        stack: infra

    post:
      - id: "wait_ready"
        type: exec.shell
        allow_shell: true
        command: "docker exec nos-postgresql pg_isready -U postgres"
        justification: "pg_isready is the canonical health probe; first-class action pending."
        timeout_sec: 60

    rollback:
      - id: "revert_tag"
        type: compose.set_image_tag
        service: postgresql
        tag: "{{ recipe.from_version_resolved }}"
      - id: "restore_db"
        type: db.pg_restore
        db: "postgres"
        label: "pre-{{ upgrade_id }}"

  # Major — requires pg_upgrade
  - id: "postgresql-16-to-17"
    from_regex: "^16\\."
    to: "17.0"
    severity: breaking
    changelog_url: "https://www.postgresql.org/docs/17/release-17.html"
    notes: |
      Requires pg_upgrade. The 'pre' phase dumps every database and takes a full data-dir
      snapshot. The 'apply' phase spins up a side container running Postgres 17, runs
      pg_upgrade against the old data dir, then swaps data_dir symlinks.
    coexistence_supported: true
    coexistence_port_offset: 100      # new Postgres runs on 5532

    pre:
      - id: "dump_all_databases"
        type: db.pg_dump
        db: "--all"                   # alias for pg_dumpall
        label: "pre-{{ upgrade_id }}"

      - id: "snapshot_data_dir"
        type: backup.volume
        src: "{{ postgresql_data_dir }}"
        label: "datadir-pre-{{ upgrade_id }}"

      - id: "stop_postgres"
        type: compose.restart_service      # :-) noop; we want stop
        service: postgresql
        stack: infra
        command_override: "stop"

    apply:
      - id: "run_pg_upgrade"
        type: db.pg_upgrade
        from_version: "16"
        to_version: "17"
        data_dir: "{{ postgresql_data_dir }}"

      - id: "bump_tag"
        type: compose.set_image_tag
        service: postgresql
        tag: "{{ recipe.to }}"

      - id: "start_postgres"
        type: compose.up_wait
        service: postgresql
        stack: infra
        timeout_sec: 120

    post:
      - id: "wait_ready"
        type: exec.shell
        allow_shell: true
        command: "docker exec nos-postgresql pg_isready -U postgres"
        justification: "canonical health probe"
        timeout_sec: 90

      - id: "analyze"
        type: exec.shell
        allow_shell: true
        command: "docker exec nos-postgresql psql -U postgres -c 'ANALYZE;'"
        justification: "pg_upgrade leaves planner stats empty; ANALYZE is required for performant queries."

    rollback:
      - id: "stop_postgres_17"
        type: compose.restart_service
        service: postgresql
        stack: infra
        command_override: "stop"
      - id: "restore_datadir"
        type: backup.restore
        label: "datadir-pre-{{ upgrade_id }}"
      - id: "revert_tag"
        type: compose.set_image_tag
        service: postgresql
        tag: "{{ recipe.from_version_resolved }}"
      - id: "start_postgres_16"
        type: compose.up_wait
        service: postgresql
        stack: infra
        timeout_sec: 120
```

Key points:
- Two backups: a logical dump (`db.pg_dump --all`) and a full data-dir snapshot. The
  dump is usable even if the data dir is corrupted; the snapshot is faster to restore.
- Rollback order: stop → restore data dir → revert tag → start. Restoring the data dir
  first ensures that when the old tag restarts, it sees its own format.
- `ANALYZE;` in `post` is not cosmetic — skipping it leaves Postgres with cold statistics
  and surprisingly slow queries for hours.

### MariaDB major upgrade (mariadb-upgrade)

MariaDB is simpler: major bumps don't need a side container, but `mariadb-upgrade` must
run after the new binary starts to fix system-table definitions.

```yaml
# File: upgrades/mariadb.yml
service: mariadb
docs_url: "https://mariadb.com/kb/en/upgrading/"

recipes:
  - id: "mariadb-10-to-11"
    from_regex: "^10\\."
    to: "11.4"
    severity: breaking
    coexistence_supported: true
    coexistence_port_offset: 100      # new MariaDB on 3406

    pre:
      - id: "dump_all"
        type: db.mariadb_dump
        db: "--all-databases"
        label: "pre-{{ upgrade_id }}"
      - id: "snapshot_data_dir"
        type: backup.volume
        src: "{{ mariadb_data_dir }}"
        label: "datadir-pre-{{ upgrade_id }}"

    apply:
      - id: "bump_tag"
        type: compose.set_image_tag
        service: mariadb
        tag: "{{ recipe.to }}"
      - id: "restart"
        type: compose.up_wait
        service: mariadb
        stack: infra
        timeout_sec: 90

    post:
      - id: "run_mariadb_upgrade"
        type: db.mariadb_upgrade
        service: mariadb

      - id: "wait_ready"
        type: exec.shell
        allow_shell: true
        command: "docker exec nos-mariadb mariadb-admin ping -uroot -p\"${MARIADB_ROOT_PASSWORD}\""
        justification: "canonical health probe"
        timeout_sec: 60

    rollback:
      - id: "stop"
        type: compose.restart_service
        service: mariadb
        stack: infra
        command_override: "stop"
      - id: "restore_datadir"
        type: backup.restore
        label: "datadir-pre-{{ upgrade_id }}"
      - id: "revert_tag"
        type: compose.set_image_tag
        service: mariadb
        tag: "{{ recipe.from_version_resolved }}"
      - id: "start"
        type: compose.up_wait
        service: mariadb
        stack: infra
        timeout_sec: 90
```

Key points:
- `db.mariadb_upgrade` runs after the new binary is up. Skipping it leaves system tables
  in the old format and you'll see errors like "Table 'mysql.global_priv' doesn't exist"
  on the first connection attempt.
- Unlike Postgres, MariaDB's on-disk format is typically forward-compatible across one
  major version — but **not** backward. Always rollback via data-dir restore, never via
  running the old binary on the new data dir.

### Grafana dashboard-preserving upgrade

Grafana is stateful but small. The safe pattern is: export dashboards to JSON, upgrade,
re-import dashboards if schema changes broke them.

```yaml
# File: upgrades/grafana.yml
service: grafana
docs_url: "https://grafana.com/docs/grafana/"

recipes:
  - id: "grafana-11-to-12"
    from_regex: "^11\\."
    to: "12.0.0"
    severity: breaking
    changelog_url: "https://grafana.com/docs/grafana/latest/release-notes/release-notes-12-0/"
    notes: |
      Grafana 12 changes dashboard schema for panel options. Export dashboards first;
      re-import only if automatic migration fails.
    coexistence_supported: true
    coexistence_port_offset: 10       # new Grafana on 3010

    pre:
      - id: "export_dashboards"
        type: http.get_all
        url: "https://{{ grafana_domain | default('grafana.dev.local') }}/api/search?type=dash-db"
        auth: { type: bearer, token_var: "grafana_admin_api_token" }
        save_to: "~/.nos/backups/{{ upgrade_id }}/dashboards-index.json"

      - id: "export_each_dashboard"
        type: http.get_all
        url: "https://{{ grafana_domain | default('grafana.dev.local') }}/api/dashboards/uid/{{ item.uid }}"
        loop_from: "~/.nos/backups/{{ upgrade_id }}/dashboards-index.json"
        auth: { type: bearer, token_var: "grafana_admin_api_token" }
        save_to: "~/.nos/backups/{{ upgrade_id }}/dashboards/{{ item.uid }}.json"

      - id: "snapshot_data"
        type: backup.volume
        src: "{{ grafana_data_dir }}"
        label: "pre-{{ upgrade_id }}"

    apply:
      - id: "bump_image_tag"
        type: compose.set_image_tag
        service: grafana
        tag: "{{ recipe.to }}"
      - id: "restart"
        type: compose.up_wait
        service: grafana
        stack: observability
        timeout_sec: 120

    post:
      - id: "wait_healthy"
        type: http.wait
        url: "https://{{ grafana_domain | default('grafana.dev.local') }}/api/health"
        expect_status: 200
        timeout_sec: 90

      - id: "sanity_check_dashboards"
        type: http.get
        url: "https://{{ grafana_domain | default('grafana.dev.local') }}/api/search?type=dash-db"
        auth: { type: bearer, token_var: "grafana_admin_api_token" }
        expect_status: 200
        expect_count_var: "dashboard_count"
        expect_count_equals: "{{ pre_dashboard_count }}"

    rollback:
      - id: "revert_image_tag"
        type: compose.set_image_tag
        service: grafana
        tag: "{{ recipe.from_version_resolved }}"
      - id: "restore_data"
        type: backup.restore
        label: "pre-{{ upgrade_id }}"
      - id: "restart_old"
        type: compose.up_wait
        service: grafana
        stack: observability
        timeout_sec: 120
```

Key points:
- Two-level export: the dashboard *index* first, then each dashboard by UID. This keeps
  the backup structured and restorable one-by-one.
- `sanity_check_dashboards` compares the count before/after — catches the case where
  Grafana 12's stricter schema silently drops dashboards on start.
- If re-import is needed after rollback is insufficient, the operator can invoke
  `tasks/grafana-restore-dashboards.yml` (a utility task, not part of the recipe).

---

## Worked examples

See the following recipe files in the repo:

- `upgrades/grafana.yml` — dashboard-preserving (above)
- `upgrades/postgresql.yml` — major + minor side-by-side (above)
- `upgrades/mariadb.yml` — major via `mariadb-upgrade` (above)
- `upgrades/authentik.yml` — config-reload + blueprint re-apply
- `upgrades/redis.yml` — image-swap only (stateless w.r.t. major bumps)
- `upgrades/infisical.yml` — DB-schema migration via built-in `infisical migrate`

---

## Testing locally

```bash
# 1. Schema lint
python -c "import yaml, jsonschema; \
  schema = yaml.safe_load(open('state/schema/upgrade.schema.json')); \
  rec = yaml.safe_load(open('upgrades/$SERVICE.yml')); \
  jsonschema.validate(rec, schema); print('OK')"

# 2. List matching recipes for installed version
ansible-playbook main.yml -K --tags upgrade -e 'upgrade_dry_run=true upgrade_service=grafana'

# 3. Preview the plan (no changes)
ansible-playbook main.yml -K --tags upgrade \
  -e 'upgrade_service=grafana upgrade_recipe_id=grafana-11-to-12 upgrade_preview=true'

# 4. Apply for real
ansible-playbook main.yml -K --tags upgrade \
  -e 'upgrade_service=grafana upgrade_recipe_id=grafana-11-to-12'

# 5. Rollback
ansible-playbook main.yml -K --tags upgrade-rollback \
  -e 'upgrade_service=grafana upgrade_recipe_id=grafana-11-to-12'
```

### Validate the recipe on a throwaway host

If you have a spare Mac or a clean profile:

1. `ansible-playbook main.yml -K -e blank=true` with the pre-upgrade service version
   pinned in `config.yml`.
2. Populate the service with realistic data.
3. Unpin the version, run the recipe.
4. Verify data + user flows work.
5. Rollback.
6. Verify rollback lands cleanly.

Only after step 6 merge the recipe.

---

## Common mistakes

### 1. No pre-phase backup

**Symptom:** upgrade fails, rollback runs, but data is gone.

**Fix:** every breaking recipe MUST have a `pre` step that snapshots data to
`~/.nos/backups/<upgrade_id>/`. Use `backup.volume` for bind mounts, `db.pg_dump` /
`db.mariadb_dump` for databases, `http.get_all` for config you can export via API.

### 2. `from_regex` too loose

**Symptom:** recipe matches versions it wasn't designed for (e.g. a `grafana-10-to-11`
recipe runs against `9.5.0` because `from_regex: "^[0-9]+\\."` matches any major).

**Fix:** pin the major version explicitly. `from_regex: "^10\\."` matches only 10.x.

### 3. `to` is a range, not a version

**Symptom:** recipe's target changes on every run, producing spurious "upgrade available"
notifications in Glasswing.

**Fix:** `to:` must resolve to a specific version string at runtime. Use a Jinja
expression backed by a version_policy variable, not a range: `to: "{{ grafana_versions.stable_12 }}"`.

### 4. Rollback assumes the old binary works on new data

**Symptom:** rollback flips the image tag back, but the old version refuses to start
because the data directory was migrated.

**Fix:** rollback sequence must restore data **before** starting the old binary. Example
structure:

```yaml
rollback:
  - id: "stop_new"
    type: compose.restart_service
    command_override: "stop"
  - id: "restore_data"
    type: backup.restore
    label: "pre-{{ upgrade_id }}"
  - id: "revert_tag"
    type: compose.set_image_tag
    tag: "{{ recipe.from_version_resolved }}"
  - id: "start_old"
    type: compose.up_wait
```

### 5. `post` health check that always passes

**Symptom:** upgrade reports success; the service is actually broken.

**Fix:** the final `post` step must be a real functional check against the service's
public surface — `http.wait` with `expect_status: 200`, a query that returns a known row,
or a login that returns a valid session. Checking only that the container is running
is not enough.

### 6. Raw shell without `allow_shell: true`

Same rule as migrations. See
[migration-authoring.md §Common mistakes](migration-authoring.md#common-mistakes) item 4.

### 7. Upgrading a service that other services depend on, without warning

**Symptom:** Postgres upgrade runs, Postgres restarts, Authentik/Gitea/etc. lose connections
and their post-start tasks fail.

**Fix:** set `downtime.services_affected:` to include every downstream service. The engine
warns on breaking upgrades affecting > 3 services and suggests coexistence. Database upgrades
should always use coexistence unless the operator explicitly accepts a downtime window.

---

## See also

- [framework-overview.md](framework-overview.md) — what the framework is
- [framework-plan.md](framework-plan.md) — authoritative spec
- [migration-authoring.md](migration-authoring.md) — sibling concept for global state changes
- [coexistence-playbook.md](coexistence-playbook.md) — zero-downtime upgrade path
- [glasswing-integration.md](glasswing-integration.md) — monitor upgrade progress
- `upgrades/_template.yml` — copy-paste starting point
- `state/schema/upgrade.schema.json` — authoritative JSON Schema for lint
