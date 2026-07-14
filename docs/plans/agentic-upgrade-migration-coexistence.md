# Agentic upgrade → migration → coexistence — architecture plan

Status: MID-BUILD — Phase B (as of 2026-07-14). B1-B6 + the A1-A5 adjustment round
landed; the **first agent-authored upgrade recipe (Gitea 1.26.4)** shipped through
the flow. OPEN: **B7 — the live PG 16→17 coexistence cutover** (the epic's own
acceptance criterion, operator-supervised) + the reset-scope blank wet-test. The
buildable spec is `agentic-upgrade-migration-coexistence-design.md`.

## The core principle (the "stop vibing on the OS, not nOS" correction)

The whole upgrade/migration/coexistence process MUST be **agent-driven** — the
nOS agents do the work, the operator (and Claude Code) only **supervise**. The
machinery propagates changes through the proper layers (recipe → migration →
coexistence) and surfaces in the **Wing UI**. It is NOT done by an operator
hand-poking the live host (manual `ansible-playbook` dry-runs, `POST`s to the
Wing API, `docker exec`, direct DB writes) — that is "vibing on the OS," the
anti-pattern this epic exists to replace. Anything an operator can do by hand,
an agent should do through the machinery, visibly, audit-logged.

## The layered model (operator's vision, verbatim intent)

```
RECIPE  (declarative plan, upgrades/<service>.yml)
   │   authored by the upgrade-architect agent; visible in Wing /upgrades
   │   "promote"
   ▼
MIGRATION  (the REAL codebase change that performs the upgrade)
   │   a NEW migration-author agent reads the recipe and writes the actual
   │   script / role / task update — imperative, committed code, not just YAML
   │   "if coexistence is wanted, it builds ON this procedure"
   ▼
COEXISTENCE  (a parallel track built ON the migration's procedure)
       activatable BEFORE the user clicks "plan" in Wing /upgrades
```

### Wing /upgrades UI flow

- Each service row shows installed version + the available recipe/migration.
- Clicking **"plan"** gives the user a CHOICE:
  - **(a) Migration** — in-place, follow the migration's procedure.
  - **(b) Coexisting new version** — provision the new version alongside, with a
    **copy of the data** (the coexistence track built on the migration).
- If a service is set to coexist, it appears in /upgrades **TWICE** (old + new),
  each with **"toggle as primary"** and **"deactivate secondary"** controls.

### Agent roles (who does what; Claude Code supervises)

- **upgrade-advisor** — queues upgrades from EXISTING recipes (today: live).
- **upgrade-architect** — drafts recipes for gaps (today: live, propose-only into
  a Wing event — NOT surfaced as a recipe/MR; that's part of the gap).
- **migration-author (NEW)** — promotes a recipe → writes the real codebase
  migration (script/role update), opens a review MR on the LOCAL forge via
  `recipe-pr.sh`. Has its own Authentik agent identity + audit lineage.
- **coexistence (orchestrator)** — provisions the parallel track built on the
  migration; drives provision → cutover → cleanup.

## Current state vs the gap (grounded in the codebase)

**Exists today:** recipes (`upgrades/*.yml`), the upgrade engine (`--tags upgrade`,
`nos_migrate.py`), the coexistence framework (`tasks/coexistence-apply.yml`,
`CoexistencePresenter` provision/cutover/cleanup, `nos_coexistence`), and the
advisor + architect agents (`tools/run-*.sh`, `pulse-run-agent.sh`).

**Missing (the build):**
1. **Wing UI surfacing.** `/upgrades` does not show recipes/migrations/coexistence
   as the operator expects — no "plan" choice, no 2×-with-toggle for coexisting
   versions. (This is why "I see nothing in the UI.") The advisor's queue
   (`planned:true`) and the architect's drafts (Wing events `type=conductor_report`)
   are not rendered as actionable recipes/migrations.
2. **recipe → migration promotion.** No agent turns a declarative recipe into a
   real, committed codebase migration. The architect only drafts YAML into an event.
3. **coexistence built ON migration.** Today coexistence is a separate track; it
   should be a layer that consumes the migration's procedure + adds the data-copy
   + the primary/secondary toggling.
4. **Lifecycle completeness.** The coexistence queue has no clean **cancel**
   (provision/queue/cutover/cleanup exist; a queued track can only be DB-deleted —
   found 2026-06-15). The plan-choice, primary/secondary state, and toggle
   transitions need a real state machine + API + UI.
5. **Agent-driven end-to-end.** The flow must run through the agents (advisor →
   architect → migration-author → coexistence), supervised — not operator-manual.

## Build approach

### Phase A — Design (do this FIRST)
Map the current Wing models + agent flow, then design:
- **Data model** — recipe ↔ migration ↔ coexistence-track relationships; the
  primary/secondary state + the plan-choice; the lifecycle (draft → recipe →
  migration → coexist-provisioned → primary | secondary → deactivated/cleaned).
- **Wing UI** — `/upgrades` plan-choice modal; the 2×-with-toggle coexistence rows;
  recipe/migration visibility; the architect/migration-author drafts surfaced as
  reviewable artifacts (+ the MR link).
- **Agent roles** — the new migration-author profile (`files/anatomy/agents/`),
  its Authentik identity + scopes + audit lineage; how supervision/approval gates
  in (manual-over-auto: a migration that writes code is review-gated on the forge).
- **Lifecycle API** — the missing cancel + the plan-choice + the primary/secondary
  toggle endpoints on `CoexistencePresenter` (+ the matching `/upgrades` engine).

Recommended: run Phase A as a **multi-agent design workflow** (parallel: map the
current state / design the data model / design the Wing UI / design the agent
roles → synthesis into one architecture spec), supervised.

### Phase B — Build (agent-driven, supervised)
Implement the design. The code that performs an upgrade is written by the
migration-author agent (review-gated MR on the local forge), never hand-applied to
the live host. Claude Code supervises + reviews; the operator approves the merge.

## Acceptance
- From the Wing `/upgrades` UI: click "plan" on a real service (e.g. Postgres
  16→17) → choose migration OR coexisting-with-data-copy → the chosen path runs
  via the agents → for coexistence, the service shows 2× with working
  toggle-as-primary / deactivate-secondary.
- No step required the operator to hand-poke the host; every step is an agent
  action visible in Wing with audit lineage.
- Postgres 16→17 is the first real end-to-end exercise (the queued upgrade that
  motivated this epic).

## Carry-over context (so the compact loses nothing)
- The upgrade-advisor already queued **postgresql 16→17** + **uptime_kuma 1→2**
  (both have existing recipes, both breaking) into the UPGRADE queue (`planned:true`)
  — legit agent output, left in place.
- The architect's round-1 drafts were only hollow forward-coverage re-pins
  (gitlab/grafana, `to=installed`) — NOT committed (no tested transition = no value).
- Webmail SSO is a separate deferred greenfield epic
  (`docs/plans/v07-webmail-stalwart-oidc-single-login.md`).
- My manual coexistence-queue + dry-run nginx-vhost artifacts were cleaned up
  2026-06-15 (queue empty, no stray pg17) — the proper flow starts from clean.
