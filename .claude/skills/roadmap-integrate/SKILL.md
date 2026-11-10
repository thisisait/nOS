---
name: roadmap-integrate
description: Batch the branches /roadmap-loop built into one integration branch: rebase on dev, resolve, regenerate, run the full suite ONCE, fix what it finds, turn GATE CONFLICTs into GATE CHANGE commits, and hand the operator one land command plus one combined e2e checklist. Run on demand or nightly, by the main session or a parallel Sonnet.
---

# /roadmap-integrate — one batch, one suite, one land

The full suite runs here, once per batch, not per row (operator 2026-11-08: the
operator must not be the bottleneck, and the suite must not run for every small
change). Input: `## Built` in `~/.cache/nos-roadmap-loop/ledger.md`.

## 1. Assemble

- Run `git fetch -q origin`. The batch is `origin/loop/dev`: every `## Built`
  row is already in it, in order (roadmap-loop fast-forwards each one).
- Create `integrate/<YYYY-MM-DD>` at `origin/loop/dev`. If `origin/dev` is not
  an ancestor of it, merge `origin/dev` in. Add the session's own fix
  branches by cherry-pick.
- Generated files conflict by nature (the graph, the body plan, the imprint,
  the pin). Take either side, then run `tools/regenerate.py` after the last
  pick. Commit the result as
  `chore: regenerate generated files`.
- If a real conflict needs a judgement, drop that branch from the batch and add
  a Roadblocks line. Never guess at its intent.

## 2. Gate conflicts

For each branch whose notes flag **GATE CONFLICT**, read the gate and the
ruling it cites.
- The ruling is the operator's, in the row or the ledger: write a separate
  `test: GATE CHANGE <what>` commit. Show the gate red against `origin/dev`'s
  code and green on the batch, and cite both runs in the commit body.
- There is no ruling: drop the branch and put the question in
  `## Questions`.

## 3. Suite, once

- Create a fixed detached worktree, `~/.cache/nos-roadmap-loop/suite-wt`, at
  the batch head (`git worktree prune` first).
- Run `tests/fast.sh > ~/.cache/nos-roadmap-loop/suite-<date>.log 2>&1` and
  wait for the `total:` line. Read the summary with
  `grep -E '^(total:|FAILED|ERROR)'`.
- Run repo-wide ansible-lint if any YAML under roles/, tasks/ or playbooks/
  changed.
- Fix reds on the batch branch, at their root cause. Rerun only the failed
  files, then the full suite once more at the end. If the batch is still red
  after two full runs, drop the guilty branch and put it in `## Roadblocks`.
- Remove the suite worktree on every exit path.

## 4. Postproduction (optional, larger batches)

Run a Fable review of the batch diff (`git diff origin/dev...integrate/<date>`)
for security, simplicity and coherence. Fix what it finds and rerun the
affected lanes. If the fixes touch code, run the full suite once more.

## 5. Hand off

- Push the batch with `tools/nos-push origin integrate/<date>`.
- Write `~/.cache/nos-roadmap-loop/batch-<date>.md` with:
  - the land command:
    `tools/nos-push origin origin/integrate/<date>:dev`. Afterwards loop/dev
    already holds every landed commit, so the loop's next fetch sees `dev` as
    its ancestor and carries on;
  - the branches and rows in the batch, and the ones dropped, with the reason;
  - the suite total line, and what was not verified;
  - one combined e2e checklist, merged from the `notes/` files, ordered by
    journey;
  - the security notes, merged.
- Move each included row with
  `nos dtt update --slug <row> --status review`. The operator moves a row to
  `shipped` after his e2e. Success is written by a reader.
- Clear the included branches from `## Built`, and write a Log line.
- Tell the operator in short, plain Czech: the land command, the batch file,
  and anything that needs his decision.

Never land, never converge, never edit config.yml. No attribution trailers.
