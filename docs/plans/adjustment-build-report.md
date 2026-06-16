# Adjustment-round build report — `feat/migration-author-agentkit`

> **Honest, read-only verification report (2026-06-16).** Verifies the adjustment-round work
> (A1–A5) on `feat/migration-author-agentkit` (off `dev`) against the spec
> `docs/plans/agentic-upgrade-adjustments-design.md`. No live apply was performed: only
> `--syntax-check`, the offline pytest suites, and the frozen-venv `tools/ci-local.sh`
> read-only gate. The entire deliverable is code on this branch + a review-gated MR to the
> local GitLab forge. Nothing deploys.

## Per-step verdict

| Step | Deviation (§7-RESOLVED) | Status | Reality |
|---|---|---|---|
| **A1** | Q8 — AgentKit gated file-write tool **+ security gate** | **GREEN** | Built + fully gated. |
| **A2** | Q8 — migration-author runs natively in AgentKit | **GREEN** | Built + gated; CLI fallback retained. |
| **A3** | Q5 — Wing "Promote to migration" Tier-1 button → AgentKit | **NEEDS-REVIEW (visual)** | Built; backend gated; the rendered button + window.confirm needs a human look. |
| **A4** | Q3 — manual re-runnable "Copy data" + UNDO the B5 auto-at-cutover hook | **NEEDS-REVIEW — NOT BUILT** | The B5 auto-at-cutover hook is **still intact**; no `copy_data` verb / route / task / Bone / UI was added. This is a decision point, not a visual one. |
| **A5** | Q4 — TTL `[3,60]` default 7 + one-click rollback / forward typed-confirm | **GREEN** | Built + gated end-to-end. |

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

## A3 — Wing "Promote to migration" button → AgentKit — BUILT; needs VISUAL review

Backend is built and gated; the rendered UI needs a human look (the part that can't be pinned
offline).

- **Shared spawn service** `files/anatomy/wing/app/AgentKit/OperatorTrigger.php` extracted from
  `Api\AgentsPresenter::spawnRunner` — array-form `proc_open` (execve direct, never `/bin/sh`),
  server-side session UUID, detached stdio, env-name charset validation, typed
  `OperatorTriggerException`. Both the bearer API and the button call the one audited path.
- **Presenter** `UpgradesPresenter::actionPromoteToMigration($service, $recipe)` — Tier-1 inherited
  (`$minAccessTier = 1`), `requirePostMethod()` (CSRF), operator read from `X-Authentik-Username`
  (never body), `migrationGap()` guard against an empty session, spawns the agent **as itself**
  (`actorId = nos-migration-author`) with the operator captured as `NOS_TRIGGERED_BY` +
  `migration_promote_requested` audit `actor_id` (operator-as-supervisor / agent-as-its-scope split
  honored).
- **Route** `upgrades/<service>/<recipe>/promote-to-migration` registered **before** the
  `upgrades/<service>` catch-all (Nette first-match-wins). No new API route — the session is
  observed via the existing `/api/v1/agent-sessions/<uuid>` poll.
- **Event twin** `migration_promote_requested` added to both `files/anatomy/bone/events.py` and
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

## A4 — manual "Copy data" + UNDO the B5 auto hook — NOT BUILT (decision needed)

**This is the honest gap.** The design's §5 called for a full reversal: rip the B5 auto-at-cutover
data-transform out of `action_cutover` / `action_promote_track`, and add a new first-class
`copy_data` verb (module action + `tasks/coexistence-copy-data.yml` + `main.yml` import + Bone
`copy_data()` + `POST /api/coexistence/<svc>/copy-data/<tag>` + Wing `copyData` repo /
presenters / routes + a "Copy data" UI button). **None of that was implemented on this branch.**

Evidence (verified against the working tree, 2026-06-16):

- `files/anatomy/library/nos_coexistence.py` — the **only** change is the A5 TTL fallback constant +
  the demotion stamp. There is **no `action_copy_data`**, and the B5 blocks in `action_cutover` /
  `action_promote_track` are **untouched**.
- `tasks/coexistence-cutover.yml` — still runs the migration auto-at-cutover (the B5 pre-run task
  "Run the source migration against the new track" + `migration_applied:` arg are intact;
  header still reads "the migration already ran above").
- `tasks/coexistence-copy-data.yml` — **does not exist**.
- `RouterFactory.php` — **no** `copy-data` route (API or browser).
- No `bone/coexistence.py` / `bone/main.py` copy-data change; no Wing `copyData` /
  `actionCopyData`; no "Copy data" button in `Coexistence/default.latte`.
- `tests/anatomy/test_coexistence_state_machine.py` — **still carries the 6 B5 auto-apply tests**
  (`test_cutover_runs_migration_before_pointer_flip`, `…_fails_closed_on_migration_error`,
  `…_refuses_when_no_migration_engine_reachable`, `…_migration_applied_flag_skips_inmodule_apply`,
  `test_promote_runs_migration_before_pointer_flip`, `…_fails_closed_on_migration_error`) that §5.5
  said to delete; there are **no `copy_data` tests**.

**Net:** the as-built coexistence flow is the **overnight-build default** — the migration
data-transform runs **implicitly at cutover/promote** (B5), fail-closed before the pointer flip.
The §7-RESOLVED Q3 deviation (explicit `provision → [Copy data] → [Promote primary]`, promote =
pointer-flip-only) is **not in this branch**.

> **A4 is a DECISION, not a visual review.** Two honest paths for the operator/reviewer:
> 1. **Build A4 as specified** (a follow-up commit set on this branch) — full `copy_data` verb +
>    B5 undo + the state-machine test surgery in §5.5.
> 2. **Accept the as-built implicit-at-cutover behavior** and amend the §7-RESOLVED Q3 decision (the
>    overnight default is safe and fail-closed; the trade is implicit coupling vs explicit operator
>    control of freshness).
> Either way, the report must not claim A4 shipped — **it did not**.

---

## A5 — TTL `[3,60]` default 7 + one-click rollback / forward typed-confirm — GREEN

Built end-to-end and gated:

- **Config var** `coexistence_secondary_ttl_days: 7` in `default.config.yml` — a **bare literal**
  (no filter, no expression), so it passes both `test_config_stock_jinja_only.py` gates (the
  `{{ vars }}` eager-resolve trap).
- **Validate + derive** `tasks/coexistence-ttl-validate.yml` — asserts integer in `[3, 60]`
  (`(x|int) == x` integer-ness check, stock Jinja only) and derives
  `coexist_secondary_ttl_seconds`; imported in `main.yml` with `tags: ['always', 'coexistence',
  'coexist-promote', 'coexist-cutover']` so it fires on a Bone-spawned `--tags coexist-promote` run.
- **Task fallback swap** in `coexistence-promote.yml` (L51) and `coexistence-cutover.yml` (L111):
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
confirm logic), but a human must eyeball the render:

1. **A3 "Promote to migration" button** on `/upgrades/<service>` recipe cards — renders for
   unapplied recipes, `window.confirm` copy, success flash deep-link to the agent session.
2. **A5 rollback vs forward controls** on `/coexistence` — the one-click `↩ Roll back to <tag>`
   button on the just-demoted prior primary vs the typed-`PRIMARY` modal on every other secondary;
   `data_*` recency / sub-header copy.
3. **(If A4 is later built)** the "Copy data" button + `data_copied_at` recency — **does not exist
   today**.

---

## The flow change (as-built vs as-designed)

- **As designed (§7-RESOLVED Q3):** `provision(empty) → [operator: Copy data] → [operator: Promote
  primary]`, with promote a pointer-flip-only operation.
- **As built on this branch:** `provision → cutover/promote`, where the migration data-transform
  runs **implicitly at cutover/promote** (the overnight B5 hook), fail-closed before the flip. The
  explicit manual Copy-data verb is **not present** (A4 not built). A5's one-click rollback +
  `[3,60]` TTL **is** present and wired through the existing promote path.

---

## Suite result (offline gates — all GREEN, read-only)

| Gate | Result |
|---|---|
| `python3 -m pytest -q tests/anatomy` | **1610 passed, 3 skipped** |
| `python3 -m pytest -q tests/upgrades tests/migrations` | **178 passed, 6 skipped** |
| `ansible-playbook main.yml --syntax-check` | **clean** (`playbook: main.yml`) |
| `tools/ci-local.sh` (frozen venv: ansible-core 2.21.0 + Python 3.13.13, lockfile collections) | **OK** — core filters load; `main.yml` syntax clean |
| Design-referenced gate subset (A1–A5 + security + schema + stock-jinja + event twins) | **138 passed** |

No live apply was performed: no `--tags` run, no docker, no `blank`, no write to the live
`~/wing/app/data/wing.db`, no Postgres cutover, no agent run against the host. The frozen-venv gate
is read-only (filter-load probe + syntax-check).

---

## Bottom line

- **A1 GREEN** — gated write tool + a comprehensive security gate; every path-escape refusal
  (traversal / absolute / symlink / allowlist) is pinned and passing.
- **A2 GREEN** — native AgentKit run is the default, CLI fallback retained.
- **A3 BUILT** — backend gated; the rendered button + confirm need a visual look.
- **A4 NOT BUILT** — the B5 auto-at-cutover hook is intact; the manual Copy-data verb + B5 undo are
  absent. A decision is required: build it, or amend the Q3 decision to accept the as-built
  implicit-at-cutover behavior.
- **A5 GREEN** — `[3,60]`-clamped configurable TTL + one-click rollback / typed-forward, wired
  through the existing promote path; the rendered asymmetry needs a visual look.
- **Full offline suite GREEN.** Delivery is the review-gated MR to the local GitLab forge; nothing
  deploys.
</content>
</invoke>
