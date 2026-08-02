# Phase B build report — agent-driven upgrade→migration→coexistence framework

**Run:** overnight agent-driven build (watcher `bd2d6b80`, authorized 2026-06-15).
**Branch:** `feat/agentic-upgrade-coexistence` (off the spec-carrying HEAD on `dev`).
**Scope built:** B1→B6 from §6 of the design doc. **B7 (live pg16→17 acceptance) is EXCLUDED** — it stays operator-supervised, by safety-rail.
**Design doc:** [`docs/archive/agentic-upgrade-migration-coexistence-design.md`](../archive/agentic-upgrade-migration-coexistence-design.md) (§6 build order, §7 open questions, §8 pg16→17 walkthrough, §9 overnight-run charter).
**Epic plan:** [`docs/plans/agentic-upgrade-migration-coexistence.md`](../plans/agentic-upgrade-migration-coexistence.md).

Nothing in this run touched the live host, ran a live apply/cutover, wrote `wing.db`, ran any Postgres cutover, merged, or pushed to GitHub/master. The only ansible run was `--syntax-check`.

---

## 1. Suite result (the offline gate)

| Gate | Command | Result |
|---|---|---|
| Anatomy pytest | `python3 -m pytest -q tests/anatomy` | **PASS** — 1574 passed, 3 skipped, 25s |
| Upgrades pytest | `python3 -m pytest -q tests/upgrades` | **PASS** — 175 passed, 1.3s |
| Migrations pytest | `python3 -m pytest -q tests/migrations` | **PASS** — 3 passed, 6 skipped (see note) |
| Playbook syntax | `ansible-playbook main.yml --syntax-check` | **PASS** — clean `playbook: main.yml` |
| CI 1:1 mirror | `tools/ci-local.sh` (frozen venv) | **PASS** — ansible-core 2.21.0 / Python 3.13.13; filter-load probe SUCCESS; syntax-check clean |

**Overall: GREEN.** The frozen-venv `tools/ci-local.sh` is the strongest signal here — it reproduces the CI Integration toolchain 1:1 (ansible-core 2.21.0, lockfile-pinned collections, Python 3.13.13), runs the filter-load probe that the 2026-06-08 saga turned into a release gate, and syntax-checks `main.yml`. It returned `OK — frozen toolchain loads core filters and main.yml syntax is clean` (exit 0).

**Migrations-suite skip note (honest, not a failure):** the 6 skips are `got empty parameter set for (path)` — the parametrized tests over `files/anatomy/migrations/*.yml` for this new framework find **no migration artifact yet**, because the first real migration (`2026-06-15-postgresql-16-to-17.yml`) is **authored by the `migration-author` agent during the operator-supervised B7 run**, not the overnight build (§8 step 3). The 3 passing tests are the structural/non-parametrized checks. This is expected and by design — the parametrized coverage activates the moment the operator drives the first authoring run.

---

## 2. Per-step status

All 8 steps verified GREEN against their pinning gate(s) + the offline anatomy suite for regressions. "NEEDS-REVIEW" below flags **operator review surface**, not a build failure.

| Step | Title | Status | Files | Commit | Review surface |
|---|---|---|---|---|---|
| **B1** | Schema + event twins | **GREEN** | 7 | `0562e2ea` | code review only |
| **B2** | Lifecycle module + Bone routes | **GREEN** | 8 | `28771b87` | code review only |
| **B3** | Repos + API tier | **GREEN** | 10 | `96c6145c` | code review only |
| **B4a** | migration-author agent + forge plumbing + identity | **GREEN** | 15 | `422afd71` | code review + §7 Q5/Q8 |
| **B4b** | Plan-choice modal UI | **GREEN / NEEDS-VISUAL-REVIEW** | 8 | `f8d2651a` | **UI must be eyeballed in Wing** |
| **B4c** | 2×-toggle + drafts UI + RBAC gate | **GREEN / NEEDS-VISUAL-REVIEW** | 13 | `e8f1a427` | **UI must be eyeballed in Wing** + §7 Q4/Q6 |
| **B5** | Coexistence-consumes-migration cutover hook + G-PROVISION-MIGRATED | **GREEN** | 6 | `e164aac4` | code review + §7 Q3 |
| **B6** | Forge merge → review_status flip | **GREEN** | 4 | `75fa6a7e` | code review + §7 Q1 |

**Phase-B totals:** 59 files changed, +6435 / −105 (commits `0562e2ea^..75fa6a7e`). Per-step file counts match the design's planned scope exactly. Key deliverable artifacts confirmed present on disk:

- Agent: `files/anatomy/agents/migration-author/agent.yml`, `files/anatomy/agents/migration-author.yml`, `tools/migration-pr.sh`, `tools/run-migration-author.sh`
- Repos/UI: `files/anatomy/wing/app/Model/MigrationAuthoredRepository.php`, `.../Templates/Upgrades/@plan-choice-modal.latte`, `.../www/assets/upgrades-plan-choice.js`
- Lifecycle tasks: `tasks/coexistence-promote.yml`, `tasks/coexistence-deactivate.yml`, `tasks/coexistence-cutover.yml`
- Gates: `tests/anatomy/test_coexistence_presenter_tier1.py`, `tests/anatomy/test_coexistence_state_machine.py`, `tests/anatomy/test_plan_choice_persistence.py`

---

## 3. What needs VISUAL review (the UI surfaces — no automated gate can catch this)

These two surfaces have **no presenter gate beyond inherited Tier-1** (B4b) / are UI-heavy (B4c). The offline suite proves the routes/RBAC/persistence wiring, but **the rendered UX must be eyeballed in a live Wing** before this ships. The Wing live-verify recipe (render deployed pages without a playbook run; port 9000 + edge token + forward-auth headers; clear the Latte cache) is the read-only way to do this.

1. **B4b — Plan-choice modal** (`@plan-choice-modal.latte`, `upgrades-plan-choice.js`, Plan→`open-plan-choice` in both `Upgrades/{default,service}.latte`). Verify: clicking **Plan** on a planned upgrade opens the modal; the **(a) in-place** vs **(b) coexisting, port +offset, with data copy** choice renders; confirm posts to `actionPlanChoice` with the right CSRF; the modal closes cleanly. **Decision dependency: §7 Q3** (data-copy timing — the modal copy must say the copy lands at *cutover*, not provision).
2. **B4c — 2×-with-toggle coexistence rows + drafts strip** (`Coexistence/default.latte` primary/secondary pair + queued rows; `matrix()` 2× rows + deep-link; Proposals strip on `/upgrades/<svc>`; `/migrations` Proposed column; `widget-cutover-confirm.js`). Verify: a service with a primary + secondary track renders **twice** with the toggle reflecting the active primary; the typed-confirm cutover widget fires; the drafts/Proposals strip shows the MR-link + Lineage deep-links. **Decision dependencies: §7 Q4** (TTL + one-click reverse-toggle vs typed confirm) and **§7 Q6** (Tier-1 vs Tier-2 for the non-destructive toggle).

---

## 4. Blockers

**None blocking the MR.** The build is GREEN and the forge is reachable (MR opened — see §6). The only "not-done" items are deliberate, by safety-rail:

- **B7 (live pg16→17 acceptance, §8) is intentionally NOT run** — it requires a live apply/cutover, which the overnight charter excludes. It is the operator's supervised morning step after merge.
- **The first real migration artifact does not exist yet** — by design it is authored by the agent during B7 (hence the 6 migrations-suite skips). Not a blocker; it's the next supervised step.

---

## 5. §7 open questions — still gate the FINAL shape (operator decisions)

These are the supervision points the build deliberately left as operator calls. They do **not** block reviewing/merging the framework, but they shape the final behavior. Answers should be recorded on the MR.

1. **B6 forge-merge→`merged` flip mechanism** — GitLab **webhook into Bone** (auto-flip, more agent-driven, adds an inbound Bone route) vs a **pull model** (`migration-pr.sh --mark-merged` / next-deploy ingest, smaller Bone surface). B6 ships the pull-model-compatible path; webhook is the open call.
2. **`nos:migration:write` enforcement** — ships **declarative** (the forge MR is the real gate; no Bone route enforces the scope). Design recommends keeping it declarative for Phase B. Confirm, or request a Bone enforcement surface now.
3. **Plan-choice (b) data-copy timing** — per the stateful-env lesson, a MAJOR upgrade boots a **fresh empty cluster** and moves data via logical dump/restore **at cutover**, not a raw clone at provision. Confirm this is the intended "coexisting WITH a copy of the data" semantics (copy lands at toggle-time). *This also gates the B4b modal copy wording.*
4. **Toggle reversibility window / TTL** — secondary gets `read_only=1` + `ttl_until` (default `coexistence_secondary_ttl_days: 7`). Is 7 days the right cooling window, and should re-promoting the old primary (rollback) be a **one-click reverse-toggle** or require a typed confirm like the forward promote? *Gates B4c.*
5. **Who fires migration-author** — Wing **"Promote to migration"** Tier-1 button (Bone→Pulse) vs `tools/run-migration-author.sh` (CLI, operator/CI). Is the CLI fire sufficient for the first acceptance run (button deferred)?
6. **RBAC tier for the toggle** — currently Tier-1 (parity with `/upgrades`). Confirm, or make the reversible (non-destructive) toggle Tier-2 while only cleanup stays Tier-1. *Gates B4c.*
7. **`uptime_kuma 1→2`** — queued but forward-only (`coexistence_supported=false`); plan-choice (b) disabled for it. Confirm it stays **migration-only**, and whether migration-author authors it alongside pg16→17 in the first run or pg-only first.
8. **AgentKit vs `pulse-run-agent.sh` runtime for migration-author** — kept on the `pulse-run-agent.sh` claude-CLI `bypassPermissions` runtime (the writing agent needs file-write; AgentKit has no `bash-write` impl). Confirm the CLI runtime for the writing agent vs waiting on AgentKit `bash-write`.

---

## 6. MR status

- **Forge:** local GitLab (`nos_agent_forge: gitlab`), tenant `pazny.eu`, project `root/nOS`, base `dev`.
- **Preflight (authenticated, local `127.0.0.1` API port — the `%2F`-dodge):** project `200`, base branch `dev` `200`, feat branch absent (`404`, clean push). Token present in the discovery chain.
- **MR:** opened on `feat/agentic-upgrade-coexistence` → `dev`, title *"feat: agent-driven upgrade→migration→coexistence framework (Phase B)"*.

*(The exact MR URL and pushed/opened status are recorded in the run's structured output and in the MR itself; if the forge had been unreachable, the branch would have stayed committed locally with mr_opened=false and this section would say so.)*

---

## 7. Morning supervision checklist (for the operator)

1. Review the MR diff on the local GitLab forge (the 8 build commits, base `dev`).
2. **Eyeball B4b + B4c in a live Wing** (§3) — the two UI surfaces with no automated visual gate.
3. **Answer the 8 §7 open questions** (§5) on the MR — they gate the final shape (esp. Q3 data-copy timing, Q4 TTL/reverse-toggle, Q6 toggle RBAC tier, which feed the UI copy + behavior).
4. Once satisfied: merge the MR, re-sync `dev`, then run a **supervised** playbook.
5. **Only then** drive pg16→17 (§8) through the live Wing UI — that is B7, the live acceptance walkthrough, which this run deliberately did not touch.
