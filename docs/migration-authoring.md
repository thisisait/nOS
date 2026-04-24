# Migration Authoring Guide

> How to write, test, and ship a migration for `nOS`. A migration is a one-shot transition
> that moves every `nOS` host from version N to N+1. Authoritative schema:
> [framework-plan.md §3.3](framework-plan.md#33-migrationsiso-date-slugyml-schema).

---

## Table of contents

- [When to write a migration](#when-to-write-a-migration)
- [File layout](#file-layout)
- [Anatomy of a migration](#anatomy-of-a-migration)
- [Action types reference](#action-types-reference)
- [Detect predicates reference](#detect-predicates-reference)
- [Idempotency patterns](#idempotency-patterns)
- [Rollback patterns](#rollback-patterns)
- [Worked examples](#worked-examples)
  - [Example 1 — Rename a state directory (simple)](#example-1--rename-a-state-directory-simple)
  - [Example 2 — Rotate launchagents (idempotent cleanup)](#example-2--rotate-launchagents-idempotent-cleanup)
  - [Example 3 — Rebrand Authentik groups + OIDC clients (API)](#example-3--rebrand-authentik-groups--oidc-clients-api)
  - [Example 4 — Migrate a Docker bind mount to a named volume (irreversible)](#example-4--migrate-a-docker-bind-mount-to-a-named-volume-irreversible)
- [Testing locally](#testing-locally)
- [Common mistakes](#common-mistakes)
- [See also](#see-also)

---

## When to write a migration

Write a migration when a **persistent identifier, path, or external system fact** needs
to change on every existing `nOS` install. Typical triggers:

- Rename a directory under `$HOME` (e.g. `~/.devboxnos` → `~/.nos`)
- Rename a launchd bundle ID (e.g. `com.devboxnos.*` → `eu.thisisait.nos.*`)
- Rename Authentik groups, OIDC client IDs, role names
- Move a Docker data path from `~/service` to `/Volumes/SSD1TB/service`
- Bump a schema version in `~/.nos/state.yml` that gates other features
- Retire a config variable in favour of a new one (with a data copy)

Do **not** write a migration for:

- A service version bump — write an upgrade recipe instead. See
  [upgrade-recipes.md](upgrade-recipes.md).
- A transient fix that only matters on hosts provisioned in the last week — use
  `when:` guards in the relevant role.
- First-time installs — if it's not a transition from a previous nOS state, it belongs in
  `default.config.yml` or a role default.

Rule of thumb: **if a user who last ran the playbook three months ago would hit it, it's
a migration.**

---

## File layout

```
migrations/
├── README.md
├── _template.yml
├── 2026-04-22-devboxnos-to-nos.yml
└── <ISO-date>-<slug>.yml          ← your new file
```

**Filename convention:** `YYYY-MM-DD-<kebab-slug>.yml`. The `id` field inside the file must
match the filename sans `.yml`. The engine enforces this — mismatched id/filename fails at
lint time.

Migrations execute in filename order. If you need deterministic ordering within the same
day (rare), put them in separate dated files (use the following day), or serialize them
as steps in a single migration.

---

## Anatomy of a migration

A migration is three sections: **metadata**, **gates**, **steps**.

```yaml
# === METADATA ===
id: "2026-05-01-move-ollama-models"     # required, must match filename
title: "Move Ollama models to external SSD"
summary: "Copy ~/.ollama/models to /Volumes/SSD1TB/ollama/models and symlink."
severity: minor                         # patch | minor | breaking
authors: ["pazny"]
created_at: "2026-05-01"
tags: [storage, ollama]
references: ["https://github.com/thisisait/nOS/pull/123"]
downtime:
  estimated_sec: 180
  services_affected: [openclaw, open_webui]

# === GATES ===
# applies_if: runs only when this predicate is true. Think of it as the outermost detect.
applies_if:
  all_of:
    - { fs_path_exists: "~/.ollama/models" }
    - { fs_path_exists: "/Volumes/SSD1TB" }
    - { fs_path_exists: "/Volumes/SSD1TB/ollama/models", negate: true }

# preconditions: must ALL pass before any step runs. Checked at runtime.
preconditions:
  - { type: fs_free_space_gb, path: "/Volumes/SSD1TB", gb: 50 }

# === STEPS ===
# Each step has four parts: detect (should I run?), action (do it),
# verify (did it work?), rollback (undo).
steps:
  - id: "copy_models"
    description: "Copy model blobs to the SSD"
    detect:
      fs_path_exists: "/Volumes/SSD1TB/ollama/models", negate: true
    action:
      type: fs.cp
      src: "~/.ollama/models"
      dst: "/Volumes/SSD1TB/ollama/models"
      preserve_perms: true
    verify:
      - { fs_path_exists: "/Volumes/SSD1TB/ollama/models" }
    rollback:
      type: fs.rm
      path: "/Volumes/SSD1TB/ollama/models"

  - id: "symlink_original"
    detect:
      fs_path_is_symlink: "~/.ollama/models", negate: true
    action:
      type: exec.shell
      allow_shell: true                    # required for shell actions
      command: |
        mv ~/.ollama/models ~/.ollama/models.bak
        ln -s /Volumes/SSD1TB/ollama/models ~/.ollama/models
      justification: "No first-class module for atomic rename+symlink."
    verify:
      - { fs_path_is_symlink: "~/.ollama/models" }
    rollback:
      type: exec.shell
      allow_shell: true
      command: |
        rm ~/.ollama/models
        mv ~/.ollama/models.bak ~/.ollama/models

# === POST-VERIFY ===
# Runs once after ALL steps succeed.
post_verify:
  - { type: fs_path_is_symlink, path: "~/.ollama/models" }
  - { type: fs_path_exists, path: "/Volumes/SSD1TB/ollama/models" }
```

### Required fields

`id`, `title`, `summary`, `severity`, `authors`, `created_at`, `steps`.

### Severity

- **patch** — transparent cleanup, no user-visible change (e.g. removing a deprecated
  marker file). Auto-applies without confirmation.
- **minor** — visible change but non-breaking (e.g. renaming a data dir with a symlink
  for back-compat). Auto-applies without confirmation.
- **breaking** — may change behaviour or identifiers the user depends on (e.g. renaming
  Authentik groups). Prompts for confirmation unless `-e auto_migrate=true` is set.

### Gates vs. detect

- `applies_if` runs *once*, before any step. If false, the entire migration is skipped.
  Use for cheap fast-path (filesystem checks, shell-free).
- `preconditions` also run before steps but may do expensive checks (API reachability,
  disk space). Failing a precondition blocks the migration with a clear error.
- per-step `detect` runs immediately before each step's action. Use to make steps
  individually re-entrant — a migration can be interrupted after step 2 and resume
  correctly on the next run.

---

## Action types reference

Implemented by `library/nos_migrate.py`. See also
[framework-plan.md §4.2](framework-plan.md#42-librarynos_migratepy--migration-engine-agent-2).

| Action type | Purpose | Key args |
|---|---|---|
| `fs.mv` | Rename file or directory | `src`, `dst` |
| `fs.cp` | Copy file or directory | `src`, `dst`, `preserve_perms` |
| `fs.rm` | Remove path | `path`, `recursive` |
| `fs.ensure_dir` | `mkdir -p` | `path`, `mode` |
| `launchd.bootout_and_delete` | Stop + remove matching launchagent plists | `pattern`, `directory` |
| `launchd.kickstart` | Restart a running launchagent | `label` |
| `authentik.rename_group_prefix` | Rename all groups matching a prefix | `from_prefix`, `to_prefix`, `preserve_members`, `preserve_policies` |
| `authentik.rename_oidc_client_prefix` | Rename all OIDC providers matching a prefix | `from_prefix`, `to_prefix` |
| `authentik.migrate_members` | Move users from one group to another | `from_group`, `to_group` |
| `docker.compose_override_rename` | Rename a compose-override file in `~/stacks/<stack>/overrides/` | `stack`, `from`, `to` |
| `docker.volume_clone` | Clone data between Docker volumes or bind mounts | `src`, `dst` |
| `state.set` | Set a value in `~/.nos/state.yml` (dotted path) | `path`, `value` |
| `state.bump_schema_version` | Increment `schema_version` | `to` |
| `exec.shell` | Arbitrary shell (requires `allow_shell: true` + `justification:`) | `command` |
| `noop` | Do nothing — used as a rollback placeholder for irreversible actions | `reason:` required |

Unknown action types fail at lint time — the engine validates the migration record
against `state/schema/migration.schema.json` before running anything.

---

## Detect predicates reference

Used in `applies_if`, per-step `detect`, and `verify` blocks.

| Predicate | Args | Meaning |
|---|---|---|
| `fs_path_exists` | `path` | True if the path exists (file or dir) |
| `fs_path_is_symlink` | `path` | True if the path is a symbolic link |
| `fs_free_space_gb` | `path`, `gb` | True if the filesystem containing `path` has ≥ `gb` free |
| `launchagent_matches` | `pattern` | True if at least one launchagent plist matches the glob |
| `launchagent_count` | `pattern`, `count` | True if the count of matching plists equals `count` |
| `authentik_group_exists` | `name` | True if an Authentik group with this exact name exists |
| `authentik_oidc_client_exists` | `name` | True if an OIDC provider with this exact name exists |
| `state_schema_version_lt` | `version` | True if `~/.nos/state.yml#schema_version` < `version` |
| `compose_image_tag_is` | `service`, `tag` | True if the running compose service uses this image tag |
| `all_of` | list of sub-predicates | Logical AND |
| `any_of` | list of sub-predicates | Logical OR |
| `not` / `negate: true` | inline | Logical NOT |

### Composing predicates

Two equivalent styles — use whichever reads clearer in context:

```yaml
# style 1: explicit any_of/all_of/not
applies_if:
  all_of:
    - { fs_path_exists: "~/.devboxnos" }
    - not:
        fs_path_exists: "~/.nos"

# style 2: inline negate shorthand
applies_if:
  all_of:
    - { fs_path_exists: "~/.devboxnos" }
    - { fs_path_exists: "~/.nos", negate: true }
```

---

## Idempotency patterns

The most common authoring bug is a non-idempotent `detect`. A good `detect` asks **"Is
there work left to do?"** — not **"Has anything happened yet?"**.

### Good detect

```yaml
# Good: "~/.nos does not yet exist, so the mv is still needed"
detect:
  all_of:
    - { fs_path_exists: "~/.devboxnos" }
    - { fs_path_exists: "~/.nos", negate: true }
```

After the action runs, `~/.devboxnos` is gone and `~/.nos` exists — detect returns false,
the step is a no-op on re-run.

### Bad detect (runs forever)

```yaml
# Bad: always true — even after the action, ~/.devboxnos exists because the action failed
# to remove it, OR because some other process recreated it
detect:
  fs_path_exists: "~/.devboxnos"
```

If the action is `fs.mv` and the source+destination both live on an encrypted volume,
the mv might succeed but `~/.devboxnos` gets silently recreated by launchd (bug). The
step loops forever on subsequent runs.

### Detect must be observable after action

Before writing a step, answer this question out loud:

> "After this action runs and succeeds, what observable fact about the system flips from
> true to false? That's my detect."

If you can't answer, the action is not well-scoped for the framework. Split it.

---

## Rollback patterns

Every step declares `rollback`. The engine runs the rollbacks of **already-applied steps
in reverse order** when any subsequent step fails verify.

### Pattern A — Symmetric inverse

The simplest and strongest rollback. The action and its rollback swap src/dst.

```yaml
action:
  type: fs.mv
  src: "~/.devboxnos"
  dst: "~/.nos"
rollback:
  type: fs.mv
  src: "~/.nos"
  dst: "~/.devboxnos"
```

### Pattern B — State mutator

For API changes (Authentik), use the API's own rename in reverse.

```yaml
action:
  type: authentik.rename_group_prefix
  from_prefix: "devboxnos-"
  to_prefix: "nos-"
rollback:
  type: authentik.rename_group_prefix
  from_prefix: "nos-"
  to_prefix: "devboxnos-"
```

### Pattern C — Noop with justification

For legitimately irreversible actions (e.g. bootout_and_delete of a legacy plist that the
new playbook already replaces). Required: a `reason:` explaining why forward-only is safe.

```yaml
action:
  type: launchd.bootout_and_delete
  pattern: "com.devboxnos.*.plist"
rollback:
  type: noop
  reason: |
    New launchagents under eu.thisisait.nos.* are deployed by the playbook on every run.
    A rollback would only re-create orphaned plists that the next run would remove again.
```

The engine requires `reason:` whenever `type: noop` is used. Lint fails without it.

### Pattern D — Backup + restore

For data mutations (Docker volume clones, dashboard exports), the action snapshots data
to `~/.nos/backups/<migration_id>/` and the rollback restores from the snapshot.

```yaml
action:
  type: docker.volume_clone
  src: "grafana-data"
  dst: "grafana-data-new"
  backup_label: "pre-{{ migration.id }}"
rollback:
  type: docker.volume_clone
  src: "grafana-data-new"
  dst: "grafana-data"
  # no backup needed — backup from forward step is still on disk
```

---

## Worked examples

### Example 1 — Rename a state directory (simple)

Scenario: rename `~/.devboxnos` to `~/.nos` across every host.

```yaml
id: "2026-04-22-devboxnos-to-nos"
title: "Rebrand devBoxNOS → nOS"
summary: "Rename user state dir."
severity: breaking
authors: ["pazny"]
created_at: "2026-04-22"

applies_if:
  fs_path_exists: "~/.devboxnos"

steps:
  - id: "move_state_dir"
    description: "Rename ~/.devboxnos to ~/.nos"
    detect:
      all_of:
        - { fs_path_exists: "~/.devboxnos" }
        - { fs_path_exists: "~/.nos", negate: true }
    action:
      type: fs.mv
      src: "~/.devboxnos"
      dst: "~/.nos"
    verify:
      - { fs_path_exists: "~/.nos" }
      - { fs_path_exists: "~/.devboxnos", negate: true }
    rollback:
      type: fs.mv
      src: "~/.nos"
      dst: "~/.devboxnos"

post_verify:
  - { type: fs_path_exists, path: "~/.nos/secrets.yml" }
```

Points of note:
- `applies_if` is cheap — a single filesystem check — so it runs on every playbook
  invocation without cost.
- Steps' `detect` is stricter than `applies_if` because after the action runs, `applies_if`
  is still plausibly re-checked on a subsequent run, but the step's detect flips and the
  step becomes a no-op.

### Example 2 — Rotate launchagents (idempotent cleanup)

Scenario: remove legacy `com.devboxnos.*` launchagents; the playbook deploys
`eu.thisisait.nos.*` in their place.

```yaml
id: "2026-04-22-retire-legacy-launchagents"
title: "Retire com.devboxnos.* launchagents"
severity: minor
authors: ["pazny"]
created_at: "2026-04-22"

applies_if:
  launchagent_matches: "com.devboxnos.*"

steps:
  - id: "bootout_openclaw"
    detect:
      launchagent_matches: "com.devboxnos.openclaw"
    action:
      type: launchd.bootout_and_delete
      pattern: "com.devboxnos.openclaw.plist"
      directory: "~/Library/LaunchAgents"
    verify:
      - { launchagent_matches: "com.devboxnos.openclaw", count: 0 }
    rollback:
      type: noop
      reason: |
        The new eu.thisisait.nos.openclaw.plist is deployed on every playbook run by
        roles/pazny.openclaw. A rollback would resurrect a plist that the next run
        would immediately replace.

  - id: "bootout_hermes"
    detect:
      launchagent_matches: "com.devboxnos.hermes"
    action:
      type: launchd.bootout_and_delete
      pattern: "com.devboxnos.hermes.plist"
      directory: "~/Library/LaunchAgents"
    verify:
      - { launchagent_matches: "com.devboxnos.hermes", count: 0 }
    rollback:
      type: noop
      reason: "Same as bootout_openclaw."
```

### Example 3 — Rebrand Authentik groups + OIDC clients (API)

Scenario: rename all Authentik groups from `devboxnos-*` to `nos-*`, preserving members
and policy bindings. Rename OIDC client prefixes in the same migration.

```yaml
id: "2026-04-22-authentik-nos-prefix"
title: "Rename Authentik identifiers to nos-"
summary: "Rename all devboxnos-* groups and OIDC clients to nos-*."
severity: breaking
authors: ["pazny"]
created_at: "2026-04-22"
downtime:
  estimated_sec: 20
  services_affected: [authentik]

applies_if:
  any_of:
    - { authentik_group_exists: "devboxnos-admins" }
    - { authentik_oidc_client_exists: "devboxnos-grafana" }

preconditions:
  - { type: authentik_api_reachable, timeout_sec: 10 }
  - { type: no_active_coexistence }

steps:
  - id: "rename_groups"
    description: "Bulk rename devboxnos-* groups to nos-*"
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
    description: "Rename devboxnos-* OIDC providers to nos-*"
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

post_verify:
  - { type: authentik_group_exists, name: "nos-admins" }
  - { type: authentik_group_exists, name: "nos-users" }
  - { type: authentik_oidc_client_exists, name: "nos-grafana" }
```

Points of note:
- `preconditions` checks `authentik_api_reachable` — the migration is useless if Authentik
  is down, and failing fast is better than a partially-renamed prefix.
- `no_active_coexistence` prevents renaming groups while two tracks depend on them — see
  [coexistence-playbook.md](coexistence-playbook.md#interactions-with-migrations).
- Both steps use `authentik.*` actions, which delegate to `library/nos_authentik.py`.
  The module handles idempotency, retry, and rollback atomicity internally — see
  [framework-plan.md §4.3](framework-plan.md#43-librarynos_authentikpy--authentik-api-client-agent-4).

### Example 4 — Migrate a Docker bind mount to a named volume (irreversible)

Scenario: move Nextcloud data from a bind mount at `/Volumes/SSD1TB/nextcloud-data` to a
Docker named volume. Requires downtime; rollback is a data restore from backup.

```yaml
id: "2026-06-01-nextcloud-volume-migration"
title: "Migrate Nextcloud data to named volume"
severity: breaking
authors: ["pazny"]
created_at: "2026-06-01"
downtime:
  estimated_sec: 600
  services_affected: [nextcloud]

applies_if:
  all_of:
    - { compose_image_tag_is: { service: "nextcloud", tag: "28-apache" } }
    - { fs_path_exists: "/Volumes/SSD1TB/nextcloud-data" }

preconditions:
  - { type: fs_free_space_gb, path: "/Volumes/SSD1TB", gb: 100 }

steps:
  - id: "stop_nextcloud"
    detect:
      compose_service_running: "nextcloud"
    action:
      type: exec.shell
      allow_shell: true
      command: "docker compose -f ~/stacks/iiab/docker-compose.yml stop nextcloud"
      justification: "No first-class compose stop action yet; see TODO.md."
    verify:
      - { compose_service_running: "nextcloud", negate: true }
    rollback:
      type: exec.shell
      allow_shell: true
      command: "docker compose -f ~/stacks/iiab/docker-compose.yml start nextcloud"

  - id: "clone_data_to_volume"
    detect:
      docker_volume_is_empty: "nextcloud-data"
    action:
      type: docker.volume_clone
      src: "/Volumes/SSD1TB/nextcloud-data"
      dst: "nextcloud-data"
      backup_label: "pre-{{ migration.id }}"
    verify:
      - { docker_volume_is_empty: "nextcloud-data", negate: true }
    rollback:
      type: docker.volume_clone
      src: "nextcloud-data"
      dst: "/Volumes/SSD1TB/nextcloud-data"

  - id: "update_compose_override"
    detect:
      compose_override_uses_bind_mount: { service: "nextcloud", path: "/Volumes/SSD1TB/nextcloud-data" }
    action:
      type: state.set
      path: "services.nextcloud.data_mode"
      value: "volume"
    verify:
      - { state_get: { path: "services.nextcloud.data_mode", value: "volume" } }
    rollback:
      type: state.set
      path: "services.nextcloud.data_mode"
      value: "bind"

  - id: "remove_old_bind_mount"
    description: "Remove the stale bind-mount directory"
    detect:
      fs_path_exists: "/Volumes/SSD1TB/nextcloud-data"
    action:
      type: fs.rm
      path: "/Volumes/SSD1TB/nextcloud-data"
      recursive: true
    verify:
      - { fs_path_exists: "/Volumes/SSD1TB/nextcloud-data", negate: true }
    rollback:
      type: noop
      reason: |
        The clone_data_to_volume step took a backup to ~/.nos/backups/{{ migration.id }}/.
        A full restore is a manual operator action documented in the migration reference.

post_verify:
  - { type: state_get, path: "services.nextcloud.data_mode", value: "volume" }
  - { type: docker_volume_is_empty, name: "nextcloud-data", negate: true }
```

Points of note:
- The migration requires changes to `roles/pazny.nextcloud` to switch between `volume` and
  `bind` modes based on `state.services.nextcloud.data_mode`. The migration is only safe
  to run *after* the role changes are merged.
- Three steps have symmetric rollbacks. The last step's rollback is `noop` with a reason
  pointing to operator-managed recovery — the forward step's backup is still on disk.
- `exec.shell` is used twice with `allow_shell: true` and `justification:`. This is a signal
  that first-class action types should be added in a follow-up PR. File an issue.

---

## Testing locally

Before shipping, validate your migration on a clean host.

```bash
# 1. Syntax + schema lint
ansible-playbook main.yml --syntax-check
python -c "import yaml, jsonschema, sys; \
  schema = yaml.safe_load(open('state/schema/migration.schema.json')); \
  mig = yaml.safe_load(open('migrations/$YOUR_FILE.yml')); \
  jsonschema.validate(mig, schema); print('OK')"

# 2. Dry run — show what would happen, change nothing
ansible-playbook main.yml -K --tags migrate -e migrate_dry_run=true

# 3. Preview a specific migration
ansible-playbook main.yml -K --tags migrate -e 'migration_id=<YOUR_ID> migrate_preview=true'

# 4. Apply for real
ansible-playbook main.yml -K --tags migrate -e 'migration_id=<YOUR_ID>'

# 5. Re-apply to prove idempotency — expect 0 changes
ansible-playbook main.yml -K --tags migrate -e 'migration_id=<YOUR_ID>'

# 6. Rollback
ansible-playbook main.yml -K --tags migrate-rollback -e 'migration_id=<YOUR_ID>'
```

Watch the `/timeline` view in Wing during the run to observe events landing in
real time. See [wing-integration.md](wing-integration.md#timeline).

### Unit tests

Each new action type you invoke should have at least one happy-path + one rollback test
under `tests/migrate/`. Tests run against an in-memory state model — no real Docker, no
real Authentik. See the test scaffolding shipped by Agent 2.

---

## Common mistakes

### 1. Non-idempotent detect (runs forever)

**Symptom:** migration applies on every playbook run, changes always `= 0`, but `changed=true`
is reported.

**Cause:** the step's `detect` is true *before and after* the action.

**Fix:** the detect should describe "remaining work". After the action flips the system to
the target state, detect must return false.

```yaml
# wrong
detect: { fs_path_exists: "~/.devboxnos" }      # still true after an incomplete mv

# right
detect:
  all_of:
    - { fs_path_exists: "~/.devboxnos" }
    - { fs_path_exists: "~/.nos", negate: true }
```

### 2. Missing verify (silent success)

**Symptom:** the action "succeeds" but the system is still broken. Subsequent steps
cascade-fail with confusing errors.

**Cause:** `verify:` was omitted or only checks trivial things.

**Fix:** `verify` should be the positive assertion that the target state is achieved.
It's not optional — the engine treats a missing `verify` as a lint error.

```yaml
# wrong — no verify
action: { type: fs.mv, src: "~/.devboxnos", dst: "~/.nos" }

# right
action: { type: fs.mv, src: "~/.devboxnos", dst: "~/.nos" }
verify:
  - { fs_path_exists: "~/.nos" }
  - { fs_path_exists: "~/.devboxnos", negate: true }
```

### 3. Forgotten rollback (unsafe in prod)

**Symptom:** step N fails mid-migration, engine tries to roll back steps 1..N-1, and step
3's rollback is missing or `type: noop` without justification. The system is left
half-applied.

**Fix:** every step needs a `rollback:` block. If truly irreversible, declare
`type: noop` *with a `reason:`* and accept that the migration is forward-only. The reason
should explain why the forward-only state is safe (typically: "the playbook replaces the
removed artifact on every run").

### 4. Raw shell in action.type (requires allow_shell, justify)

**Symptom:** reviewer rejects the PR because a step uses `type: exec.shell` without a
clear justification.

**Fix:** before reaching for shell, check the action type table. If the operation isn't
covered:

1. Prefer adding a new first-class action type to `library/nos_migrate.py`. Cheap, reusable.
2. If time-boxed, use `exec.shell` with `allow_shell: true` **and** a `justification:`
   field. The justification should say *why* shell is necessary and link to a TODO for
   replacing it with a first-class action.

```yaml
# wrong
action:
  type: exec.shell
  command: "rm -rf ~/.cache/grafana"

# right
action:
  type: exec.shell
  allow_shell: true
  command: "rm -rf ~/.cache/grafana"
  justification: |
    No first-class action for pruning application-specific cache dirs.
    TODO: add fs.rm_glob action type (see issue #NNN).
```

The engine refuses to execute `exec.shell` without `allow_shell: true`. CI lint refuses
to merge a migration with `exec.shell` but no `justification:`.

### 5. Ordering dependencies between steps

**Symptom:** step 2 fails because it reads state that step 1 writes, but step 1's state
isn't visible to step 2's detect.

**Fix:** use `state.set` + `state_get` predicates to thread values between steps, or
restructure so each step is fully self-contained.

```yaml
- id: "step1"
  action: { type: state.set, path: "migration_marker.example", value: "done" }

- id: "step2"
  detect:
    state_get: { path: "migration_marker.example", value: "done" }
  action: { ... }
```

### 6. Hardcoding paths or hostnames

**Symptom:** migration works on dev box, breaks on a host where `external_storage_root`
is different.

**Fix:** use Jinja expressions. The engine renders migration records with the full
playbook variable scope. Prefer `{{ external_storage_root }}/ollama` over
`/Volumes/SSD1TB/ollama`.

---

## See also

- [framework-overview.md](framework-overview.md) — what the framework is and why
- [framework-plan.md](framework-plan.md) — authoritative spec, action registry
- [upgrade-recipes.md](upgrade-recipes.md) — version upgrades (sibling concept)
- [coexistence-playbook.md](coexistence-playbook.md) — dual-version during migrations
- [wing-integration.md](wing-integration.md) — observe migrations live
- `migrations/_template.yml` — copy-paste starting point
- `state/schema/migration.schema.json` — authoritative JSON Schema for lint
