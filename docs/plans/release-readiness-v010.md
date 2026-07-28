# nOS v0.10 — release readiness review

**Date:** 2026-07-27 · **Reviewer:** read-only audit (no writes outside this file, no deploy)
**Target, as stated by the operator and not re-negotiated here:**

- **v0.10, no beta suffix**, cut from `master` after the full `dev → master` merge passes.
- The release **waits until the cortex organ is genuinely finished, including cortex-lang**.
- **KEAP v2 = data-only, explicitly NOT urgent.** Interim KEAP tags are welcome to prove interop.
- A **separate docs review** runs before the release (~the next day). It is not done here; §6 tells it where to start.

Every number below is followed by the command that produced it. Where something could not be
measured under the read-only constraint, it says so. The standard applied is the estate's own
(`docs/doctrine/gates.md`): *a check that cannot fail is not a check.*

---

## 1. VERDICT

**v0.10 is not days away; it is roughly three to four weeks away, and the constraint is the cortex
organ, not the merge.** The merge everyone is worried about is small and healthy — `origin/master`
is at **v0.9-beta, four days old**, `dev` is **117 commits ahead** and a **strict fast-forward
descendant** (`git rev-list --count dev..origin/master` → `0`), and the executing subset of that
diff is **49 files**, not 514. That is an afternoon of review plus a CI cycle. The single thing most
likely to slip v0.10 is the operator's own release condition: *"the cortex organ is genuinely
finished."* Measured against the organ's own roadmap in `docs/plans/cortex-self-core.md`, **S0 is
done, S1 and S2 are built and merged into `dev`, S2's exit criterion is not met, and S3–S6 are not
started — S4, S5 and S6 do not even have workflow definitions written**, deliberately, because their
shape depends on S3's findings. S5 is "KEAP's server and UI are deleted and nOS serves the explorer
natively." S6 is a training pipeline over an embedding space whose corpus is documented as too
skewed to fit yet. Those are not release-week tasks.

There is also a **hard calendar floor nobody can compress**. S2's exit criterion is that the organ
and KEAP corpora agree **for three consecutive nights**. The job that accumulates those nights was
created today and has **never fired**:

```
$ sqlite3 -header -column /tmp/wing-ro.db \
    "SELECT id, created_at, next_fire_at, (SELECT COUNT(*) FROM pulse_runs r WHERE r.job_id=j.id) AS runs
     FROM pulse_jobs j WHERE id LIKE '%cortex%';"
id                         created_at                 next_fire_at               runs
cortex:cortex-fs-sync      2026-07-27T08:39:43+00:00  2026-07-28T04:31:37+00:00  0
cortex:cortex-corpus-diff  2026-07-27T08:39:43+00:00  2026-07-28T05:31:18+00:00  0
```

*(read from a copy: `cp ~/wing/app/data/wing.db /tmp/wing-ro.db` — the live Wing DB was not opened.)*

First fire is **2026-07-28 05:31 UTC**. Three consecutive clean nights therefore complete **no earlier
than the morning of 2026-07-30**, and only if all three pass first time. S3 cannot honestly start
before that, because S3's whole premise is "one corpus, two indexes, one recall gate" — and S2's own
report records that **corpus parity is currently broken** (organ `knowledge/canonical` 1750 nodes vs
KEAP v1.35.0 working tree 2403), which would make a recall comparison *measure the taxonomy delta and
blame the index*.

**Where this review disagrees with the survey it was given, it says so.** The survey led with a
791-commit release debt and framed the merge as the dominant risk. That number is an artifact of a
stale local ref and does not exist; §3.0 records it as closed with evidence, because a v0.10 plan
built on it would budget a week for something that takes an afternoon and would leave the actual
constraint — the organ — unbudgeted. The survey's other blocker (the empty-stack health probe) is
confirmed verbatim and is carried here as a blocker.

**Do not round this up.** If the release condition is relaxed to "cortex-lang is finished and the
organ's parallel-corpus stage has closed," v0.10 is reachable in about **one week**. If it is held
literally — S5 deletes KEAP's server, S6 ships weights — it is **a month or more**, and S6's
precondition is a data problem (corpus skew) that no amount of engineering effort compresses.
That choice is the release date, and it is the operator's to make. §2 sequences it so the choice can
be deferred to the last responsible moment.

---

## 2. THE ORDERED PATH

Each step states **what must be TRUE at its end**, not what to do. Steps 1–3 and steps 4–6 are two
independent lanes and run **in parallel**; they rejoin at step 7.

### Lane A — the merge (afternoon + one CI cycle; can start now)

**Step 1 — the local refs tell the truth.**
TRUE at end: `git merge-base --is-ancestor origin/master master` succeeds; `master` and `pzny` are no
longer 676 and 794 commits behind `origin/master`. The phantom 791-commit figure appears in no
planning document.
*Why first: every subsequent size estimate is wrong until this is true, and this is the second time
it has misled a plan (`docs/roadmap.md:250-258` records the first, closed 2026-07-20).*

**Step 2 — `dev` is green and fully exposed to CI.**
TRUE at end: `ansible-lint roles/pazny.cortex/tasks/main.yml` reports 0 violations; all 54 unpushed
commits are on `origin/dev`; the light lane is green on the resulting head SHA. Note that the
Integration wet-tests are **structurally excluded from every `dev` push**
(`.github/workflows/ci.yml:340`), so "green on dev" means the light lane only — the wet-test's first
exposure to this line is the PR in step 3, by design.

**Step 3 — the merge is in `master` and the wet-test has actually run on it.**
TRUE at end: a `dev → master` PR exists, the Integration jobs have **executed** (not skipped) against
this line, their result is known and recorded, and the ~49-file executing subset has been
hand-reviewed. The merge command is `gh pr merge <n> --rebase --admin` — admin is required because
`required_approving_review_count: 1` and a sole operator cannot self-approve.
*Note: `master`'s ruleset contains **no** `required_status_checks` rule, so a red Integration will not
stop this merge on its own. That is exactly how v0.9-beta shipped red. For a non-beta, the gate must
be the reviewer's judgement, since the machine will not supply it — see §3.2.*

### Lane B — the cortex organ (the real critical path; starts now, ends last)

**Step 4 — S2's exit criterion is met, or is consciously waived in writing.**
TRUE at end: `cortex-corpus-diff` has fired and agreed on **three consecutive nights**
(earliest possible: 2026-07-30), OR the plan records a signed decision that one manual run of
167-vs-167 exact id agreement substitutes for it, and says why. The current state is unambiguous and
the plan already says so: *"Nights of evidence: ZERO. That was one manual run, not a night."*
*Also TRUE at end: the fan-out gap is either closed or documented — organ captures 1 vs KEAP 128.*

**Step 5 — corpus parity holds, so S3 can draw a valid conclusion.**
TRUE at end: organ and KEAP node counts agree at a single pinned `keap_repo_ref`. Today
`roles/pazny.keap/defaults/main.yml:45` pins `v1.35.0` while the organ carries 1750 canonical nodes
against KEAP's 2403 — S3's gate would measure the taxonomy delta and attribute it to the index.
*This is the step that makes interim KEAP tags valuable rather than noise (§5).*

**Step 6 — the organ is "finished" under an explicitly written definition.**
TRUE at end: `docs/plans/cortex-self-core.md` states which of S3/S4/S5/S6 v0.10 requires and which
ship as debt, and the stated scope is met. **This is the release-date decision.** Cheapest honest
line: v0.10 requires S3 (index decided on the gate) and S4 (readers/writers repoint at the organ),
and discloses S5/S6 as the named forward arc. S5 deletes a running service's server and UI; S6 needs
a corpus whose skew is documented as a *precondition, not a detail* (67% of 1750 nodes in 2 of 12
domains). Neither is a release-week task, and pretending otherwise is what slips the date.

**On cortex-lang specifically** — the operator named it as in-scope, so its state must be explicit.
The language itself is **built and tested**: `files/anatomy/cortex/server/cortex-lang.ts` is 1379
lines with 855 lines of tests and **84 test cases**
(`grep -c "it(\|test(" server/cortex-lang.test.ts` → `84`), zero TODO/FIXME/stub markers
(awk scan, binary-safe per the documented `grep` trap → `count=0`), and the ledger records it as
*"landed through KEAP v1.27.0."* **Its dispatch half is not built.** `docs/plans/cortex-specs-ledger.md`
marks `nos-cortex-lang-wing-executor.md` as **"forward design, not built"**, and the Wing tree
confirms it: `grep -rl cortex files/anatomy/wing/app/` returns exactly one file,
`app/AgentKit/Tools/McpKeapTool.php` — no executor, no `Cortex*` class. So "cortex-lang is finished"
is true of the language and false of the executor, and step 6 must say which one v0.10 means.

### Rejoin

**Step 7 — the tag is cut from the right ref, and the ceremony completes.**
TRUE at end: `v0.10` points at an explicit `origin/master` SHA (**not** the local `master` ref —
`tools/devlog-release.sh:69` prints `git tag $VERSION master`, which with a stale local ref would tag
2026-05-30 code as v0.10 and publish a non-beta tarball of v0.3-beta); `gh release view v0.10`
resolves; RELEASE.md carries the §4 disclosure block. **And the v0.9-beta miss is repaired:**
`gh release view v0.9-beta` → `release not found` — the tag and RELEASE.md section exist, but
`gh release create` was never run, so the public release page currently shows nOS two versions
behind its own trunk.

---

## 3. BLOCKERS

Each carries evidence, cost, and **the test that will prove it closed** — where "test" means a check
that can actually go red, per `docs/doctrine/gates.md`.

### 3.0 — Not a blocker: the 791-commit release debt does not exist

Recorded first because it was the survey's lead finding and would otherwise mis-size everything.

```
$ git log -1 --format='%H %ci %d' origin/master
d3db87d51f5a62b5c6bd9aafe888bad253a1b959 2026-07-23 07:58:45 +0200  (tag: v0.9-beta, origin/master, origin/HEAD)
$ git log -1 --format='%H %ci %d' master
c790cc5273182390879dfd460eca5611ba30d9b8 2026-05-30 18:51:45 +0200  (tag: v0.3-beta, master)
$ git rev-list --left-right --count origin/master...master
676	0
$ git rev-list --count origin/master..dev
117
$ git rev-list --count dev..origin/master
0
```

The 791 was `master..dev` measured off a **local** `master` that is 676 commits stale. `dev` is a
strict fast-forward descendant of v0.9-beta; nothing is stranded. `docs/roadmap.md:250-258` records
this same false alarm being raised and closed on 2026-07-20 — it has now recurred within a week.

**Real scope of the merge**, since the commit count overstates it by an order of magnitude:

```
$ git diff --shortstat origin/master..dev
 514 files changed, 118902 insertions(+), 1824 deletions(-)
$ git diff --name-only origin/master..dev -- main.yml tasks/ roles/ default.config.yml \
    default.credentials.yml state/manifest.yml callback_plugins/ .github/ | wc -l
49
```

**49 executing files.** The remaining 465 are docs, plans and cortex knowledge JSON.

**Test that proves it closed:** `git merge-base --is-ancestor origin/master master` exits 0 after a
fetch. Worth adding to `tools/devlog-release.sh` as a pre-flight — it runs six checks today and
**not one can go red on the single ref error the ceremony it prints can make**
(`grep -rniE "origin/master|is-ancestor|behind" tests/ tools/*.sh hooks/` finds no freshness
assertion anywhere).

---

### 3.1 — BLOCKER: the STRICT health probe passes a zero-container stack as ALL_READY

**Evidence — reproduced verbatim, read-only:**

```
$ python3 files/anatomy/scripts/stack-health-probe.py nonexistent-stack-xyz
nonexistent-stack-xyz: 0/0 ready (no containers — stack empty)
ALL_READY
exit=0
$ git log --format='%h %ad %s' --date=short -- files/anatomy/scripts/stack-health-probe.py
c4a5b9e9 2026-05-23 feat(stacks): in-stream health-wait heartbeat
```

Single commit, **untouched since the fee was found on 2026-07-22**
(`docs/hidden_fees/08-empty-stack-reads-as-success.md`, **Status: OPEN**). The ledger quotes real CI
output: `infra: rc=1 open /home/runner/stacks/infra/docker-compose.yml: no such file or directory`
followed by `infra: 0/0 ready (no containers — stack empty)` — the STRICT gate passed a stack that
never came up, and had been doing so for weeks.

**Why this blocks a non-beta specifically.** Three callers, three different rc disciplines:
`stack-up.yml:337` asserts `rc == 0` before its health-wait; `apps-up.yml:87` gates the wait on
`rc == 0`; **`core-up.yml` does neither** — the layer the architecture calls *"always required,
always first."* The observability variant then fails silently end-to-end: `install_observability`
defaults **true**, observability is 4 of 63 manifest services —

```
$ python3 -c "import yaml,collections;s=yaml.safe_load(open('state/manifest.yml'))['services'];\
c=collections.Counter(x.get('stack') for x in s);print(c['observability'],'/',len(s))"
4 / 63
```

— so 4/63 = 0.063 against the smoke gate's `nos_smoke_max_fail_ratio: 0.5`. An observability stack
that never came up yields: no rc assert → `0/0 ready` → ALL_READY on tick 0 → four
`failed_when: false` post-roles → the literal banner `CORE STACKS UP — infra + observability are
online` → smoke 6.3% → rc 0 → `PLAY RECAP failed=0` on an estate with no metrics, no logs and no
traces. Green install, broken estate, default profile.

**Stated gap:** the "compose aborts with zero containers on a pull failure" step is reasoning from
compose's pull-before-create ordering, **not a measurement** — reproducing it would mutate the host,
which this review forbids. The *class* is independently observed: `hidden_fees/08` records a real
`rc=1` / `0/0 ready` pair from CI on 2026-07-22.

**Cost:** 4–8 hours. The probe must take the bring-up rc as an input and distinguish *"empty by
configuration"* from *"bring-up failed"*; the two `core-up.yml` health-waits gain the `rc == 0` gate
that `apps-up.yml:87` already has.

**Test that proves it closed:** a unit test asserting `stack-health-probe.py` returns non-zero (or
emits a non-`ALL_READY` verdict) for a stack whose bring-up rc was non-zero. Today **no test
references the probe at all** — `grep -rln stack-health-probe tests/` matches only a prose comment in
`tests/anatomy/test_healthcheck_coverage.py:4`. Until such a test exists, neither a fix nor a
regression is detectable.

---

### 3.2 — BLOCKER (for a non-beta): the release gate is decorative, and v0.9-beta proved it

```
$ gh api repos/:owner/:repo/rules/branches/master   # rule types returned:
deletion, non_fast_forward, required_linear_history, pull_request,
required_signatures, copilot_code_review
```

**No `required_status_checks` rule**, though `CLAUDE.md` §Branch protection claims *"Require status
checks to pass + Require branches to be up to date before merging."* Measured consequence on the
v0.9-beta release commit:

```
$ gh run view 29988227515 --json jobs   # sha d3db87d, master, schedule
failure  Integration (ubuntu-24.04)
failure  Integration (macos-15)
failure  Integration (macos-14)
```

…and the merge landed anyway (`gh pr view 20` → `mergedAt 2026-07-23T06:10:11Z`). The release commit
is literally titled *"docs(release): name the red we are shipping with."*

Two supporting facts. The operator is an `OrganizationAdmin` with `bypass_mode: always` on every
rule (`gh api repos/:owner/:repo/rulesets/16506677`), and the ruleset includes `required_signatures`
while the last five master commits are unsigned (`git log origin/master -5 --format='%h %G?'` → all
`N`) — proof the bypass is the routine path. And `CLAUDE.md`'s own verification command
`gh api repos/:owner/:repo/branches/master/protection` returns **404 "Branch not protected"** while
protection is active, because protection moved to the rulesets API — a documented check that can
only go red.

**Why beta→non-beta changes the severity.** v0.9-beta could name its red and ship; that is what the
beta suffix buys. v0.10 has no suffix. Shipping it through a gate that structurally cannot stop a red
merge means the release claim rests on nobody's judgement in particular.

**Cost:** 10 minutes to add the rule; **days** if the intent is to first make Integration genuinely
green (see 3.3). The honest minimum for v0.10 is: add the rule, and if Integration is still red,
disclose it in RELEASE.md per §4 rather than routing around it silently.

**Test that proves it closed:** `gh api repos/:owner/:repo/rules/branches/master` includes
`required_status_checks`; and `CLAUDE.md`'s verify line is corrected to the `rules/branches/master`
endpoint so the documented probe can distinguish protected from unprotected.

---

### 3.3 — BLOCKER: the gating wet-test is red now, and its known cause is misdiagnosed in the ledger

The last run that actually **executed** the integration lane is `29988227515` (master, schedule,
2026-07-23) — all three Integration jobs failed. Everything since is a `dev` push, which by design
runs the light lane only (`Integration (ubuntu-24.04): skipped` on run `30206991764`). Next scheduled
execution is the Thursday cron.

`hidden_fees/08` item 3 says the missing `stacks/infra/docker-compose.yml` on Linux is *"undiagnosed
— do not guess."* **It is diagnosable and it is not a Linux defect.** `tasks/stacks/core-up.yml`
carries the "is infra enabled" list twice, and the two copies have diverged by exactly one token:

```
$ sed -n '178,184p' tasks/stacks/core-up.yml   # render gate — 9 flags
    install_portainer … install_traefik … install_mariadb … install_postgresql …
    redis_docker … install_bluesky_pds … install_authentik … install_infisical …
    install_spacetimedb
$ sed -n '334,340p' tasks/stacks/core-up.yml   # _core_infra_enabled — the same 9 PLUS:
         … or (install_spacetimedb | default(false)) or (install_bone | default(false))
```

And the CI condition reproduces it exactly:

```
$ grep -n "^install_bone" default.config.yml
208:install_bone: true
$ grep -nE "^install_(portainer|traefik|mariadb|postgresql|bluesky_pds|authentik|infisical)|^redis_docker" tests/config.yml
37,42,53,54,59,60,69,71,72  → all false
```

`install_bone: true` with every other infra flag false ⇒ **render gate False, bring-up gate True** ⇒
`docker compose up infra` against a file that was deliberately never written ⇒ `rc=1` ⇒ and then
3.1 swallows the rc and reports `0/0 ready`. The two blockers compound: one creates the failure, the
other hides it.

**Cost:** the divergence itself is ~30 minutes (make one list the source of truth). Whether that
alone turns the Linux job green is unproven — it could not be tested here without a deploy.

**Test that proves it closed:** a unit test asserting the render `when:` and `_core_infra_enabled`
resolve identically across the flag matrix — i.e. that the list exists **once**. Plus the 3.1 rc gate,
without which the next divergence is equally invisible.

---

### 3.4 — BLOCKER (scope, not defect): the organ's finish line is undefined

S0 is done. S1 and S2 are **built and merged into `dev`** (`git merge-base --is-ancestor 3aa6c7d3 dev`
→ ancestor; same for `9160d1ae`). S2's exit is **not met** — zero of three nights, first fire
2026-07-28 05:31 UTC (§1). S3 is not started. **S4, S5 and S6 have no workflow definitions**, and
`cortex-self-core.md:199-201` says that is deliberate: *"a workflow written now would be a guess
wearing the costume of a plan."*

Because "genuinely finished" is a release condition and S4–S6 are undefined, **the release has no
computable date.** This is the single most likely cause of slip, and it is a decision, not a defect.

**Cost:** an hour to write the scope line; weeks-to-months of engineering depending on what it says.

**Test that proves it closed:** `cortex-self-core.md` names the S-stage v0.10 requires, and each
stage's own stated exit criterion is measurable (they already are — that is the plan's strength).

---

### 3.5 — SHOULD-FIX: `dev` CI red for 10 consecutive pushes on one lint rule

```
$ gh run list --branch dev --workflow CI --limit 8
completed  failure  … 30206991764  2026-07-26T14:52:19Z   (× 10 consecutive)
$ ansible-lint roles/pazny.cortex/tasks/main.yml
2 risky-shell-pipe profile:safety
roles/pazny.cortex/tasks/main.yml:63   [pazny.cortex] npm ci (when package-lock.json changed)
roles/pazny.cortex/tasks/main.yml:137  [pazny.cortex] Read the data root's volume UUID
```

Only `Lint` fails; the other 8 jobs are green. Line 137 is new in the unpushed 54 — the count grew
from 1 to 2 while the branch was already red, which is what a persistently-red gate teaches.

**Cost:** 15 minutes (`set -o pipefail` in both `shell` blocks). **Test:** the existing Lint job, once
it can go green again.

**Also unmeasured:** 54 commits (`git rev-list --count origin/dev..dev`) have never run CI in any
form. Their first exposure will be the release PR.

---

### 3.6 — SHOULD-FIX: `keap-features-sync` fired and failed differently — S0's open item is not closed

S0's report recorded this job as *"fixed (`f5addeb7`, exec bit `100755`) but **unproven** — both
recorded runs failed exit 255 … success pending the next daily fire (~2026-07-27 05:04 UTC)."*
That fire has now happened:

```
$ sqlite3 -header -column /tmp/wing-ro.db \
    "SELECT job_id, fired_at, exit_code FROM pulse_runs WHERE job_id LIKE 'keap%' ORDER BY fired_at DESC LIMIT 6;"
keap:keap-lint           2026-07-27T05:16:01+00:00  0
keap:keap-features-sync  2026-07-27T05:04:57+00:00  3      ← the awaited fire
keap:keap-embed-sync     2026-07-27T04:47:21+00:00  0
keap:keap-consolidate    2026-07-27T04:17:39+00:00  0
keap:keap-lint           2026-07-26T05:17:24+00:00  0
keap:keap-features-sync  2026-07-26T05:02:49+00:00  255
$ sqlite3 /tmp/wing-ro.db "SELECT stderr_tail FROM pulse_runs WHERE job_id='keap:keap-features-sync' AND fired_at LIKE '2026-07-27%';"
keap-features-sync: numpy not available on the host python
```

The exec-bit fix worked — the job now **runs**. It fails for a new reason: **exit 3, numpy missing
on the host python.** Three of four KEAP nightly jobs are green; this one has never succeeded.
Small and concrete; it matters because it is a live input to the corpus pipeline S2/S3 depend on,
and because S0's report will otherwise be read as "closed on the next fire."

**Cost:** ~1 hour. **Test:** `keap:keap-features-sync` records `exit_code = 0` on a subsequent fire —
a check that can go red, unlike the prose status it currently has.

---

## 4. SHIPS AS DEBT

What a non-beta can honestly carry, with the one line each owes RELEASE.md. **v0.9-beta named its red
(`RELEASE.md:57` — "Known red at cut time — the Linux wet-test"); v0.10 must too, and a non-beta owes
a plainer statement than a beta does.** Suggested section: `### What v0.10 does not yet do`.

| # | Debt | The line RELEASE.md owes |
|---|---|---|
| 1 | **Cortex S3–S6 unstarted** | *"The cortex organ ships at S2: its corpus is built in parallel with KEAP's and diffed nightly. The tuned index (S3), consumer cutover (S4), KEAP's reduction to data (S5) and trained weights (S6) are the named forward arc, tracked in `docs/plans/cortex-self-core.md`."* |
| 2 | **cortex-lang has no executor** | *"The cortex language is implemented and tested (84 cases); its Wing dispatch half is forward design, not built — `docs/plans/nos-cortex-lang-wing-executor.md`."* |
| 3 | **S2 exit not met at cut** | *"The organ/KEAP corpus diff agreed exactly on its first run (167 ids, 0 symmetric difference); the three-consecutive-night criterion had accumulated N of 3 nights at cut time."* — fill N honestly; if it is 3, say so and delete the caveat. |
| 4 | **Empty stack reads as ready** (§3.1, if unfixed) | *"A stack whose bring-up fails with zero containers is still reported ready by the STRICT health probe (`docs/hidden_fees/08`). A failed observability bring-up can therefore complete a run with `failed=0`."* — **this one is a poor fit for a non-beta.** Prefer fixing it. |
| 5 | **Integration wet-test red / non-proving** | *"`Integration (ubuntu-24.04)` was RED at cut; its infra stack does not render on Linux (cause identified: duplicated enable-gates in `core-up.yml`). The Linux job does not currently prove a deploy."* |
| 6 | **`keap-features-sync` never succeeded** | *"One of four KEAP nightly jobs (`keap-features-sync`) fails on a missing host-python numpy; the other three are green."* |
| 7 | **Copilot review never runs on release PRs** | Optional. `gh pr view 20 --json reviews` → *"Copilot wasn't able to review … exceeds the maximum number of files (300)"*; the v0.10 PR is 514 files. Either scope the ruleset off release PRs or note that it never fires. |

**Debt that should NOT ship silently:** #4. Everything else is a bounded, disclosed forward arc.
#4 is a check that cannot fail, on the mandatory layer, and a non-beta that carries it is claiming a
green install it cannot detect the falsity of.

---

## 5. KEAP

**Interim tags — keep the cadence, it is doing real work.** The pin is currently
`roles/pazny.keap/defaults/main.yml:45 → keap_repo_ref: "v1.35.0"`, and there is **no shadowing
assignment in `default.config.yml`** (`grep -n "^keap_repo_ref" default.config.yml config.yml` →
nothing), so the role default genuinely wins — the `version-pins-default-config-shadow` trap does not
apply here. Good.

The recent cadence (v1.31.0 → v1.31.1 → v1.32.1 → v1.33.0 → v1.35.0 across two days, per
`git log --oneline` on `dev`) is exactly what step 5 of §2 needs: each pin is a cheap, revertible
interop probe against a moving taxonomy. Two constraints on it:

1. **Pin bumps must not outrun the parity measurement.** S2's report already flags the gap: organ
   1750 canonical nodes vs KEAP working tree 2403 vs live 1841 taxonomy embeddings. Every bump that
   lands without a re-measure widens the delta S3 will have to attribute. Bump, then measure, then
   record the number in the S2/S3 report.
2. **`hidden_fees/12` — "keap image tag is not a version" — is open** and is about exactly this
   surface. Worth reading before the next bump rather than after.

**What v2 means later — and it is explicitly not urgent.** Per `docs/plans/cortex-specs-ledger.md`,
KEAP v2 is the **S5** end-state: *"KEAP repo contains no runnable server; nOS serves the explorer
natively; one implementation of onto1 remains."* KEAP's release train becomes **dataset versioning**,
and its documentation becomes documentation *about the dataset* — taxonomy coverage, ontology
structure, weight versioning and training provenance — **none of which is written yet; it is S6's
deliverable.** Ten specs currently in KEAP's `docs/specs/` migrate to nOS at their named stages
(eight are already vendored, which is `hidden_fees/11`, and that duplication ends when the original is
deleted rather than copied).

**Recommendation:** keep tagging interim KEAP releases through v0.10 and beyond; do not attempt v2
before S5; and treat "KEAP v2" and "cortex S5" as **the same event with two names**, so neither
schedule can drift from the other.

---

## 6. WHAT THE DOCS REVIEW WILL NEED

Starting points, so tomorrow's review starts warm. This review did **not** perform it.

1. **`CLAUDE.md` §Branch protection is factually wrong in two places** — it claims a
   `required_status_checks` rule that does not exist, and its verify command
   (`gh api …/branches/master/protection`) returns 404 on a *protected* branch. Both measured in §3.2.
2. **`CLAUDE.md`'s claim that the Linux Integration job is the gating wet-test** is contradicted
   in-repo by `docs/hidden_fees/08`. CLAUDE.md was partially qualified already (fee item 4 is the one
   paid item); check the qualification is complete and current.
3. **`docs/hidden_fees/08` item 3 says "undiagnosed — do not guess."** It is diagnosed (§3.3). The
   ledger entry needs updating, and the fee's paydown items 1, 2 and 5 are verifiably unimplemented —
   check whether the entry still describes reality.
4. **`docs/plans/cortex-s0-report.md`'s pending item resolved the wrong way** — `keap-features-sync`
   fired and returned exit 3 (§3.6). The report's "success pending the next daily fire" line is now
   answerable and the answer is no.
5. **`docs/plans/cortex-self-core.md` S2** records "Nights of evidence: ZERO" — that number will have
   moved by the review. Re-measure it from `pulse_runs`, do not trust the prose.
6. **`docs/active-work.md` is exactly at its 150-line ceiling** (`wc -l` → `150`), enforced by
   `test_active_work_slim.py`. Any v0.10 addition needs a corresponding removal.
7. **`RELEASE.md`** needs the §4 disclosure block, and the v0.9-beta entry should note that the GitHub
   Release was never published (`gh release view v0.9-beta` → `release not found`; newest published is
   `v0.8-beta`).
8. **`tools/devlog-release.sh:69`** tags the local `master` ref, contradicting the authoritative flow
   in memory `nos-release-flow` (explicit SHA). Latent — all 8 tags to date are correct — but it is a
   documentation-vs-tooling divergence in the release ceremony itself.
9. **The 791-commit figure** may have propagated into other planning docs. Grep for it and for
   `master..dev` phrasing; replace with `origin/master..dev` = 117.
10. **The specs ledger's vendoring rules** (`cortex-specs-ledger.md` §Vendoring rules) state that a
    KEAP-side spec edit owes a re-vendor and that **nothing enforces this across repos**. Worth
    checking whether the eight vendored copies have drifted — that is `hidden_fees/11` and it is a
    docs-integrity question, which makes it squarely the docs review's.

---

### Appendix — measurement notes

- Wing DB was read from a copy (`cp ~/wing/app/data/wing.db /tmp/wing-ro.db`); the live DB was never
  opened. The live KEAP libSQL store was **not** probed at all — nothing in this review required it.
- `files/anatomy/cortex/server/cortex-lang.ts` was scanned with `awk`, not `grep`, per the documented
  binary-detection trap. The trap is documented for `server/agent.ts` and `server/intake.ts`; awk was
  used regardless, so a zero count here is real.
- Full local suite: `python3 -m pytest tests/ -q` → **2804 passed, 2 failed, 12 skipped** in 193s.
  Both failures (`tests/e2e/journeys/test_halt_resume.py`, `test_smoke.py`) are the documented
  missing-env false negatives (memory `e2e-journey-env-recipe`: bare pytest gives false 401/403).
  **CI does not run them** — `.github/workflows/ci.yml:154` passes `--ignore=tests/e2e` — so they are
  outside the gate either way, which is itself worth a thought: two journeys that can only fail
  locally, and only when misconfigured, are close to checks that cannot fail.
- No playbook was run; no container, launchd job, or store was mutated. `ansible-lint` and
  `stack-health-probe.py` were invoked read-only against repo files.
