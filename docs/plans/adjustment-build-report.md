# Adjustment-round build report — `feat/migration-author-agentkit`

> **Honest, read-only verification report (2026-06-16, refreshed).** Verifies the adjustment-round
> work (A1–A5) on `feat/migration-author-agentkit` (off `dev`) against the spec
> `docs/plans/agentic-upgrade-migration-coexistence-design.md` (§7-RESOLVED). No live apply was
> performed: only `--syntax-check`, the offline pytest suites, and the frozen-venv
> `tools/ci-local.sh` read-only gate. The entire deliverable is code on this branch + the existing
> review-gated MR #3 to the local GitLab forge (`root/nOS → dev`). Nothing deploys.
>
> **Refresh note:** the prior revision of this report (commit `f323492f`) recorded A3 as
> *NEEDS-REVIEW (visual)* and **A4 as NOT BUILT** — that was honest at the time it was written. Two
> commits landed **after** that report: `e36a6abe` (A3 event-twin completion) and `647c4086`
> (the full A4 Copy-data verb + B5 undo). **A3 and A4 are now built and gated GREEN.** This revision
> reflects the NOW-complete state and was re-verified against the working tree.

## Per-step verdict

| Step | Deviation (§7-RESOLVED) | Status | Reality |
|---|---|---|---|
| **A1** | Q8 — AgentKit gated file-write tool **+ security gate** | **GREEN** | Built + fully gated (16 path-escape refusal tests). |
| **A2** | Q8 — migration-author runs natively in AgentKit | **GREEN** | Built + gated; CLI fallback retained. |
| **A3** | Q5 — Wing "Promote to migration" Tier-1 button → AgentKit | **GREEN (1 visual check)** | Built + gated end-to-end; rendered button + `window.confirm` is the only human-eyeball item. |
| **A4** | Q3 — manual re-runnable "Copy data" + UNDO the B5 auto-at-cutover hook | **GREEN (1 visual check)** | **Now built.** Explicit `copy_data` verb across module/task/Bone/Wing/UI; B5 auto-hook removed from cutover+promote; state-machine tests re-pointed. |
| **A5** | Q4 — TTL `[3,60]` default 7 + one-click rollback / forward typed-confirm | **GREEN (1 visual check)** | Built + gated end-to-end. |

---

## A1 — AgentKit gated file-write tool (the security-critical step) — GREEN

**Implementation:** `files/anatomy/wing/app/AgentKit/Tools/MigrationWriteTool.php`
(`final class MigrationWriteTool implements ToolInterface`).

- Tool id `migration-file-write` (never `bash-write` — keeps clear of the `test_agentkit_dreams.py`
  forbidden token).
- `requiredScopes()` → `['nos.migration.write']` (the registry scope-gate is the structural
  admission control; the migration-author profile already carries the scope).
- Allowlist is **exactly two targets**: a migration YAML under `files/anatomy/migrations/<YYYY-MM-DD>-<slug>.yml`
  and `default.config.yml`.
- **No shell** anywhere — no `proc_open` / `exec(` / `shell_exec` / `system(` / `passthru` / `popen` /
  backtick. Pure file write.
- Atomic write: temp sibling (`random_bytes(6)` suffix) → `rename()` into place.
- Repo root injected via `%nosRepoRoot%` (`::getenv(NOS_REPO_ROOT)`); empty/missing → fail-soft
  refusal (`reason: repo_root`), never a silent wrong-place write.

### The A1 security gate — path-escape refusal (the load-bearing result)

The security gate is `tests/anatomy/test_agentkit_write_tool_scope.py` (the design proposed the
name `test_security_agentkit_filewrite.py`; the implementer chose a different filename — the
**coverage is equivalent** and a superset of the design's enumerated assertions). **16 tests, all
passing.** It is static source inspection (regex), no PHP interpreter, runs in CI without PHP.

Refusal invariants pinned and GREEN:

- **traversal** — a `..` (or `.`) path segment is refused (`refused_reason: traversal`).
- **absolute** — `str_starts_with($path, '/')` refused (`refused_reason: absolute`).
- **symlink escape** — `realpath()` of the **parent dir** (the file may not exist yet) +
  containment check against the repo root / migrations dir, plus a re-check of a pre-existing
  symlink target (`refused_reason: symlink_escape`).
- **allowlist** — anything outside the two targets refused; the gate additionally asserts no
  dangerous sibling (`/etc/`, `roles/`, `templates/`, `credentials.yml`,
  `default.credentials.yml`, `files/anatomy/plugins`) is named as writable.
- **filename shape** — the `\d{4}-\d{2}-\d{2}-<slug>.yml` regex is enforced.
- **size cap** — `MAX_CONTENT_BYTES` (256 KiB).
- **fail-soft** — every refusal returns `ToolResult::error` so the LLM self-corrects.
- **audit-leak guard** — `$content` is never placed in result metadata; `path_written` +
  `refused_reason` are.

**The security invariant holds structurally:** the tool writes only the working tree, commits
nothing, makes nothing live; the review-MR-then-operator-merge boundary (GATE 2) is unchanged from
the CLI path. AgentKit gains visibility, not reach.

**Registration triangle verified:** schema enum (`state/schema/agent.schema.yaml`,
`migration-file-write` added; `bash-write` kept as a reserved placeholder) ↔ impl class ↔ DI
(`files/anatomy/wing/app/config/common.neon`: `register(@…MigrationWriteTool)` +
`…MigrationWriteTool(%nosRepoRoot%)` + `nosRepoRoot: ::getenv(NOS_REPO_ROOT)`). Env wiring real in
both `roles/pazny.wing/templates/wing.plist.j2` (`NOS_REPO_ROOT`) and the flat
`files/anatomy/agents/migration-author.yml` pulse env.

---

## A2 — migration-author runs natively in AgentKit — GREEN

- `files/anatomy/agents/migration-author/agent.yml` roster adds `migration-file-write` alongside
  `bash-read-only` + `mcp-wing` (added, not swapped); scope `nos.migration.write` present; **no
  forge/git/`bash-write`/`mcp-bone` tool** — the MR-open stays a deterministic trigger-layer
  post-step, not an LLM tool.
- `tools/run-migration-author.sh` defaults `RUNTIME=agentkit` (native `run-agent.php
  --agent=migration-author --trigger=operator`), with the legacy pulse-CLI retained as a
  selectable fallback (`--cli` / `NOS_MIGRATION_AUTHOR_RUNTIME`), branch-on-runtime, and a Wing-bin
  preflight that points the operator at `--cli` if Wing is not deployed.
- The flat CLI profile (`files/anatomy/agents/migration-author.yml`) survives — both runtimes
  coexist by design.
- `system.md` narrative updated: author via `migration_file_write`, validation moves to the MR-open
  post-step, MR opened by the trigger layer (agent has "no forge/git" tool).

Gate `tests/anatomy/test_migration_author_agentkit.py` — all assertions pass. Lineage is automatic
through `Runner::run` (sessions/threads/iterations + OTel → `/agents` + Grafana `22-ai-agents` +
Tempo); no dashboard edit.

---

## A3 — Wing "Promote to migration" button → AgentKit — GREEN (1 visual check)

Built and gated end-to-end. The only item a human must eyeball is the rendered surface (which the
offline gates cannot pin).

- **Shared spawn service** `files/anatomy/wing/app/AgentKit/OperatorTrigger.php` extracted from
  `Api\AgentsPresenter::spawnRunner` — array-form `proc_open` (execve direct, never `/bin/sh`),
  server-side session UUID, detached stdio, env-name charset validation, typed
  `OperatorTriggerException`. Both the bearer API and the button call the one audited path. Gate
  `tests/anatomy/test_agentkit_operator_trigger.py`.
- **Presenter** `UpgradesPresenter::actionPromoteToMigration($service, $recipe)` — Tier-1 inherited
  (`$minAccessTier = 1`), `requirePostMethod()` (CSRF), operator read from `X-Authentik-Username`
  (never body), `migrationGap()` guard against an empty session, spawns the agent **as itself**
  (`actorId = nos-migration-author`) with the operator captured as `NOS_TRIGGERED_BY` +
  `migration_promote_requested` audit `actor_id` (operator-as-supervisor / agent-as-its-scope split
  honored).
- **Route** `upgrades/<service>/<recipe>/promote-to-migration` registered **before** the
  `upgrades/<service>` catch-all (Nette first-match-wins). No new API route — the session is
  observed via the existing `/api/v1/agent-sessions/<uuid>` poll.
- **Event twin** `migration_promote_requested` added to **both** `files/anatomy/bone/events.py` and
  `files/anatomy/wing/app/Model/EventRepository.php` `VALID_TYPES`; pinned by
  `test_devlog_event_types.py`.
- **Button** in `files/anatomy/wing/app/Templates/Upgrades/service.latte`: a self-contained hidden
  CSRF `<form>` (`_csrf` as the first child — SEC-14 placement), `data-action="promote-to-migration"`,
  rendered only for unapplied recipes; the JS-delegated `window.confirm`
  (`upgrades-plan-choice.js`, case `promote-to-migration`) is the lightweight supervision gate
  (non-destructive → not a typed-`PRIMARY` modal).

> **NEEDS VISUAL REVIEW (A3):** that the "Promote to migration" button renders on the recipe card,
> that the `window.confirm` copy reads correctly, and that the success flash deep-links
> `/agents/migration-author/sessions/<uuid>`. Backend gates (`test_security_presenter_gates.py`
> Tier-1, `test_devlog_event_types.py`, `test_agentkit_operator_trigger.py`) are GREEN; the
> rendered surface is what a human must confirm. Implementation note: the design (§4.4) sketched an
> inline `onclick="return confirm(...)"`; the implementer used JS-delegation in
> `upgrades-plan-choice.js` instead — functionally equivalent, but worth eyeballing.

---

## A4 — manual "Copy data" + UNDO the B5 auto hook — GREEN (1 visual check)

**Now built.** Commit `647c4086` reverses the overnight B5 default exactly as §5 specified: the
auto-at-cutover/promote data-transform is **removed**, and the data move becomes a first-class,
operator-fired, re-runnable `copy_data` verb. The flow is now
`provision(empty) → [Copy data] → [Promote primary]`, where promote is a pure pointer-flip.

**The verb, end-to-end (verified against the working tree, 2026-06-16):**

- **Module** `files/anatomy/library/nos_coexistence.py` — new `action_copy_data(params, state, ctx)`
  registered in the dispatch table (`if action == "copy_data": return action_copy_data(...)`). It
  runs the track's recorded `source_migration_id` data move into the **secondary's empty cluster**,
  then stamps `data_copied_at`. Three guards, all gated:
  - **G-COPY-HAS-MIGRATION** — refuse a track with no `source_migration_id` (an empty provision has
    nothing to copy).
  - **G-COPY-NOT-PRIMARY** — refuse copying INTO the active primary (never dump into the cluster
    serving live traffic).
  - **G-COPY-ENGINE** — fail closed if no migration engine is reachable.
- **Task** `tasks/coexistence-copy-data.yml` — reads tracks (`list_tracks`, pure read), resolves the
  target + its `source_migration_id`, runs `nos_migrate action=apply` against the secondary's
  cluster (port/data_path/version threaded as `coexist_*` tokens), then stamps `data_copied_at`.
  **`dry_run` defaults TRUE** (mutating verb — first call plans, `dry_run=false` commits). Tagged
  `['coexist-copy-data', 'never']` so a normal pass never auto-fires it; imported in `main.yml`
  with the same tags.
- **Bone** `POST /api/coexistence/{service}/copy-data/{tag}` (`files/anatomy/bone/main.py`) →
  `files/anatomy/bone/coexistence.py::copy_data()` → drives the `coexist-copy-data` task.
  `dry_run` defaults TRUE.
- **Wing** — `CoexistenceRepository::copyData`, `Api\CoexistencePresenter` +
  `CoexistencePresenter::actionCopyData`, and routes
  `api/v1/coexistence/<service>/copy-data` + `coexistence/<service>/copy-data` in `RouterFactory`.
- **UI** — `Coexistence/default.latte` renders a `data-action="copy-data"` "↓ Copy data" button per
  track with a `data_copied_at` recency tooltip (and a `(no data yet)` affordance when never
  copied); `widget-cutover-confirm.js` adds the `copy-data` delegation case. The sub-header was
  rewritten to the new explicit lifecycle: **provision (empty) → Copy data → Toggle as primary**.
- **Event twin** `coexistence_copy_data` in **both** `files/anatomy/bone/events.py` and
  `files/anatomy/wing/app/Model/EventRepository.php` `VALID_TYPES`; pinned by
  `test_devlog_event_types.py`.

**B5 undo, verified:**

- `tasks/coexistence-cutover.yml` — the B5 pre-run ("Run the source migration against the new track"
  + `migration_applied:` arg) is **gone** (no `migration_already ran` / `Run the source migration` /
  `migration_applied` strings remain). `tasks/coexistence-promote.yml` likewise no longer runs the
  data-transform — promote is pointer-flip-only.
- `nos_coexistence.action_cutover` / `action_promote_track` — the in-line B5 data move is removed;
  comments point the reader at the new `copy_data` verb. Result-shape stability preserved.

**State-machine test surgery (§5.5), verified:** the 6 B5 auto-apply tests are **gone**; in their
place `tests/anatomy/test_coexistence_state_machine.py` carries 7 new `copy_data` tests —
`test_copy_data_runs_migration_into_secondary`, `…_is_rerunnable`,
`…_refuses_without_source_migration`, `…_refuses_copy_into_primary`, `…_fails_closed_on_migration_error`,
`…_refuses_when_no_engine_reachable`, `…_migration_applied_flag_just_stamps` — all passing.

> **NEEDS VISUAL REVIEW (A4):** that the "↓ Copy data" button renders per track on `/coexistence`,
> that the `data_copied_at` recency tooltip / `(no data yet)` affordance reads correctly, and that
> the rewritten sub-header lifecycle copy (provision → Copy data → Toggle as primary) is clear.
> The backend + state machine are pinned offline; the rendered surface is the human check.

---

## A5 — TTL `[3,60]` default 7 + one-click rollback / forward typed-confirm — GREEN (1 visual check)

Built end-to-end and gated:

- **Config var** `coexistence_secondary_ttl_days: 7` in `default.config.yml` — a **bare literal**
  (no filter, no expression), so it passes both `test_config_stock_jinja_only.py` gates (the
  `{{ vars }}` eager-resolve trap).
- **Validate + derive** `tasks/coexistence-ttl-validate.yml` — asserts integer in `[3, 60]`
  (`(x|int) == x` integer-ness check, stock Jinja only) and derives
  `coexist_secondary_ttl_seconds`; imported in `main.yml` with `tags: ['always', 'coexistence',
  'coexist-promote', 'coexist-cutover']` so it fires on a Bone-spawned `--tags coexist-promote` run.
- **Task fallback swap** in `coexistence-promote.yml` and `coexistence-cutover.yml`:
  `coexist_ttl_seconds | default(coexist_secondary_ttl_seconds | default(7 * 24 * 3600))` — explicit
  override → config-derived → last-ditch literal. Wing keeps passing `ttlSeconds=null`, so the
  configured value flows with zero Wing change.
- **Rollback signal** in `nos_coexistence.action_promote_track`: stamps `demoted_from_primary_at`
  on the just-demoted prior primary (the demotion branch matches exactly one track) and **clears**
  it on the new-primary branch — guaranteeing "exactly one rollback target".
- **Wing UI** — `CoexistencePresenter::renderDefault` derives `is_rollback_target` from
  `demoted_from_primary_at`; `Coexistence/default.latte` branches: a one-click `rollback-primary`
  button for the rollback target, the typed-`PRIMARY` `toggle-primary` button for every other
  secondary; both POST the **same** `coex-toggle-form` to the **same** toggle endpoint (the
  asymmetry is purely client-side confirm friction). `widget-cutover-confirm.js` adds `onRollback`
  (single `window.confirm`, no `TOGGLE_PHRASE`) and the `rollback-primary` delegation case; the
  forward path keeps `const TOGGLE_PHRASE = 'PRIMARY'`.

Gates GREEN: `test_coexistence_state_machine.py` (`test_ttl_validate_task_pins_3_to_60_inclusive`,
`test_ttl_default_is_seven_and_a_bare_literal`, `test_promote_stamps_demoted_prior_primary`,
`test_rollback_clears_stamp_on_re_promote`, `test_configured_ttl_applied_on_demotion`) +
`test_coexistence_presenter_tier1.py` (`test_presenter_flags_rollback_target`,
`test_template_splits_forward_and_rollback_controls`, `test_rollback_is_one_click_forward_is_typed`).

> **NEEDS VISUAL REVIEW (A5):** that the rollback target renders a one-click `↩ Roll back to <tag>`
> button while other secondaries keep the typed-`PRIMARY` modal, and that the sub-header copy reads
> correctly. The behavior is pinned offline; the rendered asymmetry is what a human confirms.

---

## What needs VISUAL review (rendered Wing UI — not pinnable offline)

These are deployed-Wing surfaces; the offline gates pin structure (data-actions, routes, CSRF,
confirm logic), but a human must eyeball the render. All three are the **only** open items — every
backend, state-machine, and security invariant is GREEN.

1. **A3 "Promote to migration" button** on `/upgrades/<service>` recipe cards — renders for
   unapplied recipes, `window.confirm` copy, success flash deep-link to the agent session.
2. **A4 "↓ Copy data" button** on `/coexistence` — renders per track, the `data_copied_at` recency
   tooltip / `(no data yet)` affordance, and the rewritten lifecycle sub-header copy.
3. **A5 rollback vs forward controls** on `/coexistence` — the one-click `↩ Roll back to <tag>`
   button on the just-demoted prior primary vs the typed-`PRIMARY` modal on every other secondary.

---

## The flow change (now matches as-designed)

- **As designed (§7-RESOLVED Q3):** `provision(empty) → [operator: Copy data] → [operator: Promote
  primary]`, with promote a pointer-flip-only operation.
- **As built on this branch (now):** **the same.** A4 removed the implicit B5 data-transform from
  cutover/promote and added the explicit, re-runnable `copy_data` verb (dry-run-default, fail-closed
  guards). Promote is now pointer-flip-only. A5's one-click rollback + `[3,60]`-clamped configurable
  TTL is wired through the existing promote path. The implicit-at-cutover coupling the prior report
  flagged is **gone** — freshness is the operator's explicit call (re-run Copy data right before
  Promote).

---

## A1 security gate (restated — the load-bearing safety boundary)

The whole adjustment round hangs on A1's gate because it is what lets the migration-author agent
**author files** without ever reaching the live system:

- The tool writes **only** the working tree (two allow-listed targets), commits nothing, makes
  nothing live. The review-MR-then-operator-merge boundary (GATE 2) is unchanged.
- 16 static-source refusal tests (`test_agentkit_write_tool_scope.py`) pin traversal / absolute /
  symlink-escape / allowlist / filename-shape / size-cap / fail-soft / audit-leak.
- The A4 `copy_data` verb and the A3 promote spawn both inherit the same dry-run-default +
  fail-closed + operator-as-supervisor safety model — destructive moves plan first, commit only on
  an explicit `dry_run=false`.

---

## Suite result (offline gates — all GREEN, read-only)

| Gate | Result |
|---|---|
| `python3 -m pytest -q tests/anatomy` | **1617 passed, 3 skipped** |
| `python3 -m pytest -q tests/upgrades tests/migrations` | **178 passed, 6 skipped** |
| `ansible-playbook main.yml --syntax-check` | **clean** (`playbook: main.yml`) |
| `tools/ci-local.sh` (frozen venv: ansible-core 2.21.0 + Python 3.13.13, lockfile collections) | **OK** — core filters load; `main.yml` syntax clean |
| A1 security gate (`test_agentkit_write_tool_scope.py`) | **16 passed** |
| Design-referenced gate subset (A1–A5 + security + schema + stock-jinja + event twins) | **135 passed** |

The anatomy count rose **1610 → 1617** (+7) since the prior report: the new A3 event-twin assertions
and the A4 `copy_data` state-machine + event-twin tests, minus the deleted B5 auto-apply tests.

No live apply was performed: no `--tags` run, no docker, no `blank`, no write to the live
`~/wing/app/data/wing.db`, no Postgres cutover, no agent run against the host. The frozen-venv gate
is read-only (filter-load probe + syntax-check).

---

## Bottom line

- **A1 GREEN** — gated write tool + a comprehensive security gate; every path-escape refusal
  (traversal / absolute / symlink / allowlist) is pinned and passing. This is the safety boundary
  that lets the agent author without reaching live.
- **A2 GREEN** — native AgentKit run is the default, CLI fallback retained.
- **A3 GREEN** — backend + event twin + gates complete; the rendered button + confirm is the one
  visual check.
- **A4 GREEN** — the Copy-data verb is **now built** end-to-end (module/task/Bone/Wing/UI + event
  twin), the B5 auto-at-cutover hook is removed from cutover **and** promote, and the state-machine
  tests were re-pointed (6 B5 tests deleted → 7 `copy_data` tests added). The "↓ Copy data" button
  is the one visual check.
- **A5 GREEN** — `[3,60]`-clamped configurable TTL + one-click rollback / typed-forward, wired
  through the existing promote path; the rendered asymmetry is the one visual check.
- **Full offline suite GREEN.** Delivery is the existing review-gated MR #3 to the local GitLab
  forge; nothing deploys.
