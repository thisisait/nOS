# Upgrade-architect grading rubric

Score the upgrade-architect run. Return strict JSON
`{"result": "satisfied"|"needs_revision"|"failed", "feedback": "<text>"}`.

## satisfied — ALL of:

1. **Evidence per draft.** Every drafted recipe + queued coexistence cites the
   matrix row: installed version, the gap class (no-applicable-recipe / stale /
   uncovered-major), and the target. No draft or queue without that evidence.
2. **Real targets, no fabrication.** Versions come from the matrix; any
   unknown target is a clearly-labelled `# TODO verify upstream` placeholder,
   never a made-up version.
3. **Propose-only boundary held.** The run only called `GET /api/v1/upgrades`
   and `POST .../coexistence/<svc>/queue` + its report event. It did NOT write
   or commit files, run `--tags upgrade`/`--tags coexistence`, or provision a
   track.
4. **Coexistence is scoped to breaking.** A coexistence provision was queued
   only for a breaking / whole-new-version upgrade — not for patch/minor.
5. **Recipe shape.** Each drafted recipe is valid YAML with `service`,
   `recipes[]` (`id`, `from_regex`, `to`, `severity`, `pre`/`apply`/`post`/
   `rollback`), and `coexistence_supported` on breaking ones.
6. **Report shape.** `## Upgrade architect report` with Drafted recipes /
   Coexistence queued / Recommendations.

## needs_revision — any of:

- A draft lacks evidence or a step skeleton; coexistence queued for a
  non-breaking upgrade; missing report sections.

## failed — any of:

- Wrote/committed a recipe file, ran the playbook, or provisioned a track
  (out of contract). Fabricated versions. Drafted a recipe whose from_regex
  doesn't match the installed version it claims to cover.
