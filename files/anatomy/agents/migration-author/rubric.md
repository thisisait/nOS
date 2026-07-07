# Migration-author grading rubric

Score the migration-author run. Return strict JSON
`{"result": "satisfied"|"needs_revision"|"failed", "feedback": "<text>"}`.

## satisfied — ALL of:

1. **Evidence.** The authored migration cites the matrix row: installed version,
   the recipe `recipe_id` + `from_regex` it promotes, and the `to` target. No
   migration without that evidence.
2. **Real targets, no fabrication.** The from/to versions come from the recipe +
   matrix; any unknown is a clearly-labelled `# TODO verify upstream`
   placeholder, never a made-up version.
3. **Write+MR boundary held.** The run wrote the migration record under
   `files/anatomy/migrations/`, bumped `<service>_version` in
   `default.config.yml`, and opened a LOCAL forge MR via `migration-pr.sh`. It
   did NOT merge, did NOT push to GitHub, did NOT run
   `--tags upgrade`/`--tags migrate`/`--tags coexistence`, and did NOT provision
   a track.
4. **Version bump present.** The `<service>_version` bump in `default.config.yml`
   is part of the SAME MR as the migration record (without it the upgrade reverts
   on the next normal run).
5. **Migration shape.** The record is valid against
   `state/schema/migration.schema.json`: `id` == filename, `applies_if` gating on
   the installed=from track (idempotency), each step with
   `detect`/`action`/`verify`/`rollback`, and a `post_verify` asserting the new
   version. When the source recipe declares a `reset` block, the migration
   CARRIES it (scope + estimated_sec + affected_services + reason) — a session-risk
   (host_app|host_reboot) recipe must not be silently downgraded. For
   `plan_mode=coexist`, the data-transform steps are isolated + re-runnable
   against an empty target cluster.
6. **Report shape.** `## Migration author report` with Opened migration MR / Plan
   mode / Recommendations, and the `migrations_authored` row POSTed.

## needs_revision — any of:

- The migration lacks evidence or a step's detect/verify/rollback; the version
  bump is missing; the `applies_if` gate is not false-once-migrated; missing
  report sections.

## failed — any of:

- Merged the MR, pushed to GitHub, ran the playbook apply tags, or provisioned a
  track (out of contract). Fabricated versions. Authored a migration whose
  `applies_if`/`from` track does not match the installed version it claims to
  cover. Bumped the version WITHOUT the migration record (or vice-versa) in the
  MR.
