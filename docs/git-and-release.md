# Git workflow, branch protection and the release toolchain

Moved out of `CLAUDE.md` (2026-10-02), which keeps only the summary. Gates:
`tests/anatomy/test_git_workflow.py`, `tools/git-hooks/pre-push`.

## Branches

Three long-lived branches (`feat → dev → master`), revived 2026-05-17 after the
`master`-only flow proved hard to gate once contributors arrive. The 2026-04-16
"never resurrect dev" rule is **superseded** — the three-tier flow is load-bearing.

- **`master`** — release-ready trunk. PR-only, fast-forward only, branch lock on both
  GitHub and the local Gitea mirror. Release tags `v<semver>` live here.
- **`dev`** — integration branch. `feat/*` and `fix/*` merge here by fast-forward (CLI is
  fine, no PR). `dev → master` happens via PR.
- **`feat/<short-name>`, `fix/<short-name>`** — short-lived, off `dev`. Squash WIP before merge.
- **`pzny`** — the maintainer's local cross-feature workspace. Mirrors to local Gitea only
  (where Woodpecker runs the auto-deploy pipeline, [ci-pipeline.md](ci-pipeline.md));
  never pushed to GitHub — the pre-push hook refuses it.

Worktrees branch off `dev` by default.

## Branch protection — one-time operator setup

The `master` protection is **not** a workflow file — it is a GitHub repo-settings
operation a fresh operator (or anyone forking nOS) MUST configure once, or direct pushes
to `master` silently succeed and the PR gate is bypassed. `tools/git-hooks/pre-push` is a
client-side backstop, not a substitute for the server-side rule.

**GitHub — Repo Settings → Branches → add a rule for `master`:**

- **Require a pull request before merging** (the `dev → master` PR gate).
- **Require status checks to pass** + **Require branches to be up to date before merging**
  (the fast-forward-only guarantee — `master` can never diverge from a validated `dev`).
- **Do not allow bypassing the above settings** — even admins go through the PR. (A sole
  operator then self-merges with `gh pr merge --rebase --admin`.)
- **Allow force pushes: disabled** and **Allow deletions: disabled** — the "branch lock".

**Gitea mirror (local):** Repo → Settings → Branches → Branch Protection → `master`:
enable "Block force push" + "Require pull requests" so the mirror lock matches GitHub.

**Verify with the RULESETS endpoint, not the branch-protection one.** This repo's `master`
is guarded by a **repository ruleset** (`Master protection`: `deletion`,
`non_fast_forward`, `required_linear_history`, `pull_request` ≥1 approval,
`required_signatures`; bypass `OrganizationAdmin: always`). Classic branch protection is
not configured, so `gh api repos/:owner/:repo/branches/master/protection` returns **404
while the branch is fully protected** — do not read that 404 as "unprotected". Use:

```bash
gh api repos/:owner/:repo/rulesets                 # expect an active ruleset targeting ~DEFAULT_BRANCH
gh api repos/:owner/:repo/rulesets/<id>            # expect the five rules above
```

`git push origin master` from a non-fast-forward state must still be refused.

## Cutting a release

1. **`gh pr merge --rebase` fails on a release-sized PR.** At ~190 commits / ~600 files
   GitHub reports `rebaseable: false` with `mergeable: true` ("This branch can't be
   rebased"). `squash` is disabled and `required_linear_history` forbids a merge commit,
   so no PR merge method works at that size. When `merge-base(master, dev) == master
   tip` — always true in this flow — a rebase-merge IS a fast-forward, so
   `git push origin origin/dev:master` produces identical history. Verify the merge-base
   equality first.
2. **Commits are unsigned while the ruleset requires signatures.** The admin bypass logs
   the violations and lets them through, so the signature rule has never been met.
   Either turn on commit signing (`commit.gpgsign`) or drop the rule.
3. After the merge, re-sync `dev` to `master`, tag, and publish the GitHub release.

## Frozen integration toolchain (`tools/ci-local.sh`)

`tools/ci-freeze.env` (Python + ansible-core pins, with the reasoning in its header) and
`requirements.lock.yml` (exact collection/role pins) are the single source of truth for
both `tools/ci-local.sh` and the CI integration jobs (`.github/workflows/ci.yml`). Run
`tools/ci-local.sh` before a release push; refresh both files together with
`tools/ci-local.sh --refresh-lock`.

- The daily driver stays **ansible-core 2.20.5** (`.python-version` pins Python 3.13.13).
  The frozen venv is the **2.21.0** mirror: the GitHub runner's filter-load path imports
  `VaultDecryptionContext`, a 2.21 symbol, and a 2.20 controller there skips every core
  filter ("No filter named 'bool'/'default'…"). The fix was a NEWER ansible, not an
  older one. When CI is red and local is green, compare exact versions between the
  passing and failing jobs first — this saga cost ~21 cycles of guessing.
- This freezes the **toolchain**, not the **environment**. GitHub's hosted macOS runner
  is not the operator's Mac: its custom-module interpreter path ignores every
  `ansible_python_interpreter` pin, so the macOS Integration job is
  `continue-on-error: true`. The Linux `integration-linux` job is the gating wet-test
  (first proved green with the estate serving 2026-09-03; the road there is
  `docs/hidden_fees/08-empty-stack-reads-as-success.md` §Closed).
  Revert the macOS `continue-on-error` once the runner/ansible ships a fix.
- **ansible-core 2.24 (future):** removes the deprecated `{{ vars }}` the playbook still
  passes; everything else is pinned to 2.20 and forward-verified on 2.21. The jump is a
  `requirements.yml` floor bump + collection review + one blank, not a track.
