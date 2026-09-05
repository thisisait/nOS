---
name: dtt-capture
description: Capture an idea, plan, or spec into the nOS roadmap DataTable as a per-row seed file — the ONLY sanctioned way to write down new work (operator directive: track/ideate/spec via skill + dtt, never a hand-authored docs/plans/*.md). Writes through tools/dtt-capture.py into the private seed repo.
---

# /dtt-capture — file an idea/plan/spec into dtt

The operator directive (memory `track-via-skill-and-dtt`): new ideas, plans, and
specs are DEFINED in dtt, not in ad-hoc `docs/*.md`. This skill captures one as a
per-row seed file. Use it instead of writing a new planning document.

## The one rule

**Every write goes through `nos dtt capture`** (the installed CLI; it runs
`tools/dtt-capture.py` from `$NOS_SRC`) — never hand-write the file, never POST
the live table directly, never call the `tools/*.py` path (it only exists inside
a pulled checkout; `nos dtt` reaches it from any shell/branch/cwd). The tool
validates the slug (KEAP assertRowId), the `task_type` (against
`state/task-types.yml`), and the `status` (against
`state/keap-tables/roadmap.table.yml`), then writes the canonical per-row format
into `NOS_SEED_DIR` (the PRIVATE seed repo). A row that would fail the seeder is
refused before it is written.

## Steps

1. **Gather the fields:**
   - `--slug` — kebab id, `[A-Za-z0-9_-]`, unique. It is the filename.
   - `--title` — one line: what the row IS (git-owned, a claim).
   - `--track` — `platform | security | agents | cortex | face | release | filesystem`.
   - `--parent` — an existing roadmap slug, or omit for a top-level row.
   - `--task-type` — one of `state/task-types.yml` (`investigate` for research,
     `design` for a spec, `code-fix`, `seed-edit`, `review`, `doc`,
     `security-remediation`, `converge`). Adding a NEW type is a proposal, not a
     free value.
   - `--status` — a fresh idea is usually `next` or `queued`; only a value the
     table declares.
   - `--when` (optional `YYYY-MM-DD`), `--refs` (`·`-separated pointers),
     `--release` (only if the row IS a release).
2. **Write the body** (`--body`, `--body-file`, or stdin): the prose. For a plan
   or spec — the measurement, the defect/gap, the structural approach, the gate
   that will pin it, concrete enough that another agent can build from it. For an
   idea — what it is and why, in a few honest lines. This is the git-owned body;
   keep it discriminable from sibling rows.
3. **Run it:**
   ```
   nos dtt capture --slug <slug> --title "<title>" --track <track> \
       --task-type <type> --status <status> [--parent <slug>] [--when <date>] \
       [--refs "..."] --body "<prose>"
   ```
   Add `--update` to revise an existing row's git-owned half; `--dry-run` to
   preview. (`NOS_SEED_DIR` must point at your private seed repo — export it in
   your shell profile once.)
4. **Commit it in the PRIVATE seed repo** (`NOS_SEED_DIR`) — never in nOS. Then
   `nos dtt seed --dry-run` shows it as a pending insert; `nos dtt seed` files
   it into the table.

## The split (do not fight it)

- The FILE owns `title/parent/track/refs/body` (git, reviewable, synced by
  `roadmap-seed.py --sync`).
- The TABLE owns `status/target/occurred_at/verified*`. **Move status with
  `nos dtt update`, a verdict with `nos dtt verify` — never by rewriting the
  file.** Re-running capture with a new status does not move a filed row; it
  only rewrites the git-owned half.

## When NOT to use

- To change a row's STATUS or record a VERDICT → `nos dtt update` /
  `nos dtt verify`, not this.
- To read the board → `nos dtt status`.
