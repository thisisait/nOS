---
slug: my-row-slug
title: One line — what this row IS (git owns this)
parent: parent-slug
track: platform
task_type: code-fix
status: next
when: 2026-09-05
refs: "docs/plans/... · tools/... · a-related-slug"
release: ""
---
The body is prose — the measurement, the defect, the structural fix, the gate
that pins it. Written here and nowhere else; `roadmap-seed.py --sync` reconciles
it into the table. Keep it discriminable: what this row is and how it differs
from its siblings.

<!--
This is the CANONICAL FORMAT for a per-row roadmap seed file (dtt-seed-per-row-file).
It is the only file under state/roadmap/ that ships in the PUBLIC nOS repo — every
real row lives in your PRIVATE seed repo (NOS_SEED_DIR); see README.md here.

Frontmatter keys:
  slug       required — the row id (kebab, [A-Za-z0-9_-], the file name too).
  title      required — git-owned, the row's claim.
  parent     "" for a top-level row, else an existing slug.
  track      platform | security | agents | cortex | face | release | filesystem
  task_type  one of state/task-types.yml (authored now; not yet a table column).
  status     INSERT-time seed only — the TABLE owns it after (roadmap-update.py).
  when       a date (YYYY-MM-DD); STATUS decides target vs occurred_at.
  refs       "·"-separated pointers.
  release    "" unless this row IS a release.
body:        the prose, after the closing ---.
-->
