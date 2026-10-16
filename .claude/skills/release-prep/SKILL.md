---
name: release-prep
description: Prepare a nOS release from dev to master - stoppers, roadmap revision, hidden fees paid or written, quick wins, RELEASE.md, devlog, generators and signatures, then the cut. Use when the operator says "prepare a release", "release checklist", "připrav release". Defaults to a read-only preflight; every write and the cut itself wait for the operator.
---

# /release-prep — from a green dev to a tagged master

One checklist instead of five places. It strings together what already exists
(`tools/devlog-release.sh`, the `/devlog` skill's `release` mode, `tools/ci-local.sh`,
the readers, [docs/git-and-release.md](../../../docs/git-and-release.md) §Cutting a
release) and adds the two steps nothing owned: the roadmap revision and the hidden
fees. The operator decides what ships (CLAUDE.md); this skill gathers the evidence
and prepares the changes, it never cuts on its own.

## Modes

- `/release-prep vX.Y-beta` or `--preflight` (default): **read only.** Run steps 1-9
  as checks, write nothing, end with the report (below).
- `/release-prep vX.Y-beta --prepare`: also prepare the changes of steps 2-6 on a
  branch `release/vX.Y-beta` off `dev` (roadmap rows via `nos dtt`, hidden-fee files,
  RELEASE.md, devlog), commit per step, show the diff. No push, no tag, no cut.
- The cut (step 10) is never a mode. The operator runs it, or says "cut" in the
  same conversation after reading the report.

The version: the release's own roadmap row decides it (`rel-NNN`, read it with
`tools/roadmap-status.py --all` - it may rule the name, e.g. dropping `-beta`); else
the newest `v*` tag + 1 minor (`git tag --sort=-creatordate | head -1`). A row and the
evidence that disagree (a row ruling "no -beta" whose exit criteria are not met) is a
decision for the operator, not a default.

## Steps (each ends with PASS, BLOCKER or DEBT, and the command that showed it)

1. **Stoppers — the estate is green where it counts.**
   - CI on dev: `gh run list --branch dev --limit 5` and `tools/ci-tier-status.py`.
     A red **blocking** lane (the main CI workflow, its pytest shards, the core
     install) is a BLOCKER until its job log names the cause (compare a passing run
     first, memory `ci-diagnose-by-comparison`). A red or stale **Bonus** lane
     (per-stack, all-on, macOS nightly: non-blocking by design) is DEBT: name it in
     RELEASE.md as unverified, never as working.
   - The full offline suite once, to a file, read the summary line (never
     `| tail`: memory `local-pytest-false-green`):
     `python3 -m pytest tests --ignore=tests/e2e -q -p no:cacheprovider > /tmp/rp-pytest.txt 2>&1`.
     Plus cargo (thalamus, contract), face and pupil vitest, `ansible-lint`.
   - `tools/ci-local.sh` (frozen toolchain, syntax-check).
   - **A blank is the gate** (memory `blank-is-the-gate`): the release names the
     newest blank converge (`nos --remove=data --confirm`, then `nos`) and its
     `nos-smoke --strict` result. None since the last release → BLOCKER; the
     operator runs it (destructive), the skill only asks and reads the result.
     No reader records blanks yet (roadmap row `blank-run-record`): name the source
     you used (a RELEASE.md line, the operator's word) and say it is not a reader.
   - `tools/red-status.py`: every red line is either fixed, owned by a roadmap row,
     or written as a hidden fee (step 3). UNKNOWN is not green.
2. **Roadmap revision.** `tools/roadmap-status.py --status active,next,blocked`
   and `--all` since the last tag. Each row touched in this release gets a verdict
   with `nos dtt verify` (what proves it), a stale `active` gets its real status
   with `nos dtt update`, rows captured but not yet seeded show in
   `nos dtt seed --dry-run`. Writes to the table are the operator's
   (`nos dtt seed`, `verify`, `update`): prepare the commands, do not run them.
3. **Hidden fees: make the deferred costs visible; actionable work goes to the roadmap.**
   A hidden fee is a cost we chose to carry and can see - a `ponytail:` comment's
   ceiling, a known limit, a workaround - not a task. Collect since the last tag:
   new `ponytail:` comments (`git log -p <last-tag>..dev -S'ponytail:'`), memory files
   modified since the tag date, `fix:` commits whose body says why it hid, workflow
   verify findings. Sort each one:
   - **actionable** (someone can do it) -> a roadmap row (`/dtt-capture`), never a fee;
   - **paid** -> cite the fix and the gate that pins it;
   - **carried** -> `docs/hidden_fees/NN-slug.md` in the shape of
     [docs/hidden_fees/README.md](../../../docs/hidden_fees/README.md) (the fee, when
     the bill comes due, how it was found, what closes it), the ponytail's upgrade
     path included.
4. **Quick wins.** From the roadmap, rows that fit before the cut: small, a gate
   included, no live-host step. Propose at most five, the operator picks.
5. **RELEASE.md.** A new `## vX.Y-beta` section above the previous one, in its
   voice: one-line thesis, commit count and diffstat measured with
   `git log <last-tag>..dev` / `git diff --shortstat`, the blank + smoke evidence
   from step 1, then sections by theme. Every claim names its evidence; nothing
   that did not ship.
6. **Devlog.** The `/devlog` skill, `release` mode. First check the PREVIOUS tag has
   its release entry (`rg -l 'release: <last-tag>' docs/devlog/nos-core/`); a missing
   one is caught up in this release, not skipped twice. Then
   `tools/devlog-release.sh vX.Y-beta` must exit 0.
7. **Generated files and signatures.** Regenerate in this order when one is stale -
   anatomy-graph, body-plan, imprint (each reads the one before) - then check each
   as its own command:
   `python3 tools/anatomy-graph-gen.py --check`, `python3 tools/imprint-gen.py --check`,
   `python3 tools/design-sync.py --check`, `python3 tools/body-plan-gen.py --check`;
   `tools/apex-sign.py` (a diff = the operator signs, `--confirm`, then commits the
   ruling - the digest counts only once committed; CI does not check it, roadmap row
   `apex-signature-in-ci`). Any commit that adds a graph node changes the ruling.
8. **Client hosts.** A client estate follows a release tag, not dev: list each
   known client host's branch and the tag it will move to (memory
   `first-client-deploy-and-contributors`; never name the client).
9. **The report.** One table: step | PASS/BLOCKER/DEBT | evidence (command +
   result). Then the blockers in the order they unblock, then what the operator
   must run (blank, `nos dtt …`, `apex-sign --confirm`, the cut). Say what was
   not checked.
10. **The cut (operator).** Only with no BLOCKER left, per docs/git-and-release.md:
    verify `git merge-base origin/master origin/dev` equals the master tip, open the
    PR dev → master, merge by rebase with admin bypass or `git push origin
    origin/dev:master` at release size (memory `nos-release-flow`), tag
    `vX.Y-beta` on master, publish the GitHub release from the RELEASE.md section,
    re-sync dev to master, `tools/nos-push` for the Gitea mirror.

## Never

- push, tag, merge to master, run a blank or any converge on the operator's behalf;
- weaken or skip a gate to turn a step green - a wrong gate is proposed on its own;
- call a step PASS without the command and its output;
- write a client name, a secret or a credential into RELEASE.md, the devlog or a fee.
