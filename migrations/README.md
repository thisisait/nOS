# nOS Migrations

Declarative, replayable, idempotent, rollback-first migration records. Executed by
`library/nos_migrate.py`. Full authoring guide lives in `docs/migration-authoring.md`
(agent 9) — this file is the quick-start.

## File layout

```
migrations/
├── README.md                               # you are here
├── _template.yml                           # annotated template — copy, rename, edit
├── 2026-04-22-devboxnos-to-nos.yml         # retroactive rebrand (reference example)
└── YYYY-MM-DD-<slug>.yml                   # your next migration
```

**Naming:** `YYYY-MM-DD-<kebab-case-slug>.yml`. The `id:` field inside the file
**must** match the filename without the `.yml` suffix. `nos_migrate list` rejects
files that violate this.

## Authoring checklist

1. Copy `_template.yml` → `YYYY-MM-DD-your-slug.yml`.
2. Fill in `id`, `title`, `summary`, `severity`, `created_at`.
3. Write an `applies_if` gate that is **false** once the migration has been applied.
   This is the idempotency hinge — `nos_migrate` re-runs every playbook invocation.
4. For each step, provide:
   - `detect` — so the step is a no-op if already applied
   - `action` — the forward operation
   - `verify` — assertions that must hold after the action
   - `rollback` — inverse action (or `type: noop` with a `reason:` if irreversible)
5. Add a `post_verify` block for cross-step assertions.
6. Validate: `python -c "import json, yaml; json.loads(yaml.safe_dump(yaml.safe_load(open('migrations/your.yml'))))"`.
7. Dry-run: `ansible-playbook main.yml --tags migrate -e migrate_dry_run=true`.

## Severities

| level      | meaning                                                    | prompt? |
|------------|------------------------------------------------------------|---------|
| `patch`    | cosmetic rename, doc fix, metadata tweak                   | no      |
| `minor`    | non-destructive structural change, backwards compatible    | no      |
| `breaking` | schema change, rename, data path move, downtime expected   | **yes** |
| `security` | urgent — e.g. rotate leaked credential                     | **yes** |

`tasks/pre-migrate.yml` pauses for operator confirmation on `breaking` / `security`
unless `auto_migrate=true` is set.

## Action & detect types

See `state/schema/migration.schema.json` for the full enum. Quick list:

- **filesystem:** `fs.mv`, `fs.cp`, `fs.rm`, `fs.ensure_dir`
- **launchd:** `launchd.bootout_and_delete`, `launchd.kickstart`
- **Authentik:** `authentik.rename_group_prefix`, `authentik.rename_oidc_client_prefix`, `authentik.migrate_members`
- **Docker:** `docker.compose_override_rename`, `docker.volume_clone`
- **state:** `state.set`, `state.unset`, `state.bump_schema_version`
- **escape hatch:** `exec.shell` (requires `allow_shell: true` at the top of the migration)
- **no-op:** `noop` — document irreversible steps with a `reason:`

Detect predicates:
`fs_path_exists`, `launchagent_matches`, `authentik_group_exists`,
`authentik_oidc_client_exists`, `state_schema_version_lt`, `compose_image_tag_is`,
plus boolean combinators `all_of`, `any_of`, `not`, and `negate: true` on any predicate.

## How `nos_migrate` selects migrations

1. On every playbook run, `tasks/pre-migrate.yml` calls `nos_migrate list_pending`.
2. A migration is **pending** when:
   - it does **not** appear in `~/.nos/state.yml .migrations_applied[*].id`
   - AND its `applies_if` predicate evaluates `true` on this host
3. Preconditions run before any step.
4. Steps execute in declared order. `detect: false` skips a step.
5. On success, `migrations_applied` gets a new entry and state is persisted.
6. On failure, the engine attempts per-step `rollback` in reverse order unless
   `on_failure: continue` is set.

## Testing

- Standalone: `pytest tests/state_manager/` for manifest + state-library tests.
- Runtime: `ansible-playbook main.yml --tags migrate -e migrate_dry_run=true`.
- Rollback smoke: `ansible-playbook main.yml --tags migrate-rollback -e migration_id=<id>` (once agent 2 wires the rollback task).
