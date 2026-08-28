# Note for the generative-UI session — your work is committed, under my messages

Written 2026-08-28 by the agentic-planes-build session. Nothing of yours was
lost; some of it is filed under the wrong name, and this says exactly where.

## What happened

We were both working in `/Users/pazny/projects/nOS` at the same time, on the
same branch (`feat/planes-build`), and I committed with `git add -A`. That is a
broom, not a staging command: it swept your in-flight files into commits whose
messages describe something else entirely. My fault, not yours — I did not check
for a second writer before I started committing.

## Where your work is

| commit | its message (mine) | your files in it |
|---|---|---|
| `d7f27225` | docs(roadmap): Tauri elevated to next… | 7 of 9 |
| `63eba4a2` | fix(nos-cc): mouse on… | 2 of 3 |

`d7f27225` carries ~1090 lines of yours:

- `files/anatomy/face/src/lib/components/DataTableApp.svelte` (+308)
- `files/anatomy/face/src/lib/tables/view.ts` (+234)
- `files/anatomy/face/src/lib/tables/lens.test.ts` (new, 256)
- `tests/anatomy/test_view_block_travels_and_is_narrowed.py` (new, 206)
- `files/anatomy/face/src/lib/contracts/index.ts`
- `files/anatomy/face/src/routes/bff/tables/+server.ts`
- `roles/pazny.keap/tasks/seed-face-table.yml`
- `state/keap-tables/roadmap.table.yml` (the view block)

`63eba4a2` carries `contracts/index.ts` and `tables/view.ts` as well — an
earlier snapshot of the same two files.

## What is still UNCOMMITTED and is yours

`state/keap-tables/roadmap.table.yml` — 18 insertions, 13 deletions, the
`highlights` rewrite. I deliberately left it in the working tree rather than
commit it under another wrong message. It carries a finding worth keeping in
whatever commit you give it: the highlight was authored as
`status eq shipped AND verified eq contradicted` and, evaluated against the 122
live rows, matched **zero** — all 11 shipped rows are `confirmed`, and every one
of the 27 contradictions sits on a row someone had already moved back to queued,
next, active or parked. A schema-only check would have shipped an empty strip
that looks exactly like a table with nothing wrong in it.

## What NOT to do right now

`agentic-planes-build` is running on `feat/planes-build` and its agents commit to
it. **Do not rebase, reset or force-push this branch while it runs** — you would
rewrite history under a process that is appending to it. Separating your commits
is a `git rebase -i` job for after the run drains; the planes session owns that
cleanup and has it queued.

If you need to commit before then: stage by path (`git add <file>`), never
`git add -A`, and say in the message that the branch is shared. If you would
rather not share it at all, `git worktree add` your own checkout — that is what
either of us should have done at the start.

## Delete this file when the separation is done.
