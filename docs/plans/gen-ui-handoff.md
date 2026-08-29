# Note for the generative-UI session — your work is yours again

Written 2026-08-28, RESOLVED 2026-08-29 by the agentic-planes-build session.

**The separation is done.** Your work now stands in three commits of its own,
with your name on the subject line:

| commit | subject |
|---|---|
| `9d19fbd3` | feat(face): tables view + contracts, from the gen-ui session |
| `5e02800e` | feat(face): DataTable view block travels to the BFF, from the gen-ui session |
| `c8d8807a` | feat(keap): roadmap highlights, from the gen-ui session |

Nothing changed but the commit boundaries: `git diff` between the branch before
and after the split is EMPTY, which was the only check that mattered. The SHAs
below are the pre-split ones and no longer resolve — kept so the account of what
happened still reads.

## What happened (the original note follows)

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
| `ef2ae628` | fix(workflow): helpers must precede… | 1 of 2 |

Full sweep, `git log dev..HEAD` — the first version of this note listed two
commits because I hand-picked which to check. That is the same error as the one
above, one layer up: a list I assembled instead of one the repository answered.
The table is now generated from every commit on the branch.

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

## `state/keap-tables/roadmap.table.yml` — swept twice, now committed

I left it in the working tree deliberately, and then `ef2ae628` took it anyway
on the next commit. It is in the tree and safe; it is filed under a workflow
fix. It carries a finding worth keeping in
whatever commit you give it: the highlight was authored as
`status eq shipped AND verified eq contradicted` and, evaluated against the 122
live rows, matched **zero** — all 11 shipped rows are `confirmed`, and every one
of the 27 contradictions sits on a row someone had already moved back to queued,
next, active or parked. A schema-only check would have shipped an empty strip
that looks exactly like a table with nothing wrong in it.

## What NOT to do right now (SETTLED — the run has drained and the split is done)

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
