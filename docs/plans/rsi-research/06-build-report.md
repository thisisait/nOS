# Build report — the planes work on `feat/planes-build`

Read-only review, 2026-08-29. The reviewer wrote nothing in this workflow but this
file. No converge was run, nothing was pushed, no remote was touched.

Range: `dev..feat/planes-build`, merge-base `bc688824`.
31 commits · 126 files · +10 526 / −3 204 · 16 new gate files, 19 modified.

---

## 1. Gates

```
python3 -m pytest tests/anatomy -q
4250 passed, 46 skipped, 4 warnings in 312.19s (0:05:12)
```

**Failures: 0.** No red gate anywhere, so no STOP condition.

The 46 skips are the standing absence report, unchanged in shape by this branch:
39 × "no `Usage:` flags documented", 2 × "a test may import anything it likes",
2 × `NOS_TOFU_PLAN_JSON` unset, 1 × no plugin declares
`autologin.local_login_fallback`, 2 × migrations that completed. `NOS_TEST_PROVIDES`
is unset locally, so the tool-gated gates announce that they did not run rather
than passing quietly — the doctrine working as intended. CI declares it
(`ci.yml:135`, now including `files/anatomy/wing/vendor/autoload.php`, added by
`59f04cf0`), which is the fix that makes the PHP gates actually run there instead of
skipping into a green.

The face suite, which the pytest job does not cover:

```
cd files/anatomy/face && npm test
28 test files, 323 tests passed (1.19s)
```

---

## 2. Every commit, and the gate it ships

Oldest first. "standing" = the machinery is covered by a gate that already existed
and still passes against the change.

| # | Commit | Gate(s) shipped in the same commit |
|---|--------|-----------------------------------|
| 1 | `3298ba04` feat(ops-plane): per-agent Wing principal | **new** `test_the_token_that_called_is_the_agent_that_ran.py` (523 ln; exec + sqlite + json) |
| 2 | `8e77cc4a` feat(agentkit): split mcp-wing into read and write | **new** `test_a_tool_refuses_the_verb_its_scope_does_not_name.py` (548 ln); + `test_bound_agent_can_file_its_report.py`, `test_every_registered_tool_actually_loads.py`, `test_inspektor_librarian.py`, `test_migration_author_agentkit.py` |
| 3 | `8adcf053` merge ops-plane-agent-principal | conflict resolution in `McpWingTool.php`; covered by the gate merged in with it (#1) |
| 4 | `77d33e15` fix(workflow): a phase that did not run must stop the run | **new** `test_workflow_scripts_are_valid.py`; + `test_no_master_in_rendered_artifacts.py` |
| 5 | `6df3416c` refactor(workflow): serial, managed, three holes folded in | standing — `test_workflow_scripts_are_valid.py` (#4) runs `tools/workflow-lint.py` over the script |
| 6 | `63036e6d` feat(tools): draw a workflow definition as a tree | **NONE — see §3** |
| 7 | `63eba4a2` fix(nos-cc): mouse on | standing — `test_the_control_centre_shows_state.py` (nos-cc.sh) + vitest `view.test.ts` (face); neither extended — see §3 |
| 8 | `d7f27225` docs(roadmap): Tauri elevated; command centre filed | **new** `test_view_block_travels_and_is_narrowed.py` + `lens.test.ts` |
| 9 | `f4992c3d` fix(workflow): Grant verifies what landed | standing (#4) |
| 10 | `7ec9d758` fix(workflow-lint): drop a check that reds valid scripts | standing (#4) |
| 11 | `7ae7858a` fix(workflow): backticks in a prompt end its template | standing (#4) |
| 12 | `1e552a8e` fix(workflow): the body may declare meta, never read it | standing (#4) |
| 13 | `ef2ae628` fix(workflow): helpers must precede the phase that calls them | standing (#4) |
| 14 | `b1716c90` refactor(agentkit): delete memory and coordinator | **new** `test_agent_memory_does_not_return.py`; deletes `test_agentkit_dreams.py` + `test_agentkit_multiagent_pool.py` in the same commit |
| 15 | `df0f7772` feat(lock): agent-run lock becomes 3 slots | **new** `test_cli_lock_excludes_agentkit_slots.py`; + `test_agent_run_lock.py`, `test_one_agent_lock_for_every_claude.py` |
| 16 | `3aea362d` docs: gen-ui note | docs only |
| 17 | `2be66e46` docs: gen-ui note correction | docs only |
| 18 | `6643f902` feat(ops-plane): a principal Bone accepts | `test_the_token_that_called_is_the_agent_that_ran.py` extended |
| 19 | `9ced0c9c` fix(ops-plane): keap.read served a POST | `test_a_tool_refuses_the_verb_its_scope_does_not_name.py`, `test_agentkit_keap_tool.py` |
| 20 | `1515b116` fix(ops-plane): pin who holds the write plane | `test_a_tool_refuses_the_verb_its_scope_does_not_name.py` |
| 21 | `59f04cf0` fix(ci): bind the vendor tree the PHP gates need | `_environment_contract.py`, `test_absence_is_counted.py` |
| 22 | `d184579e` docs(roadmap): a dependency contract is one-sided | standing — `tools/roadmap-seed.py` is pinned by 7 gates incl. `test_keap_table_concepts.py`, `test_the_roadmap_declares_the_table_it_fills.py`. Mis-typed as `docs(` — see §3 |
| 23 | `8f56fd94` feat(agentkit): a gate run decides satisfaction | **new** `test_satisfaction_is_written_by_a_gate_run.py`, `test_a_repaired_output_says_so.py`, `test_the_session_reports_its_best_iteration.py`; + `test_a_revision_sees_its_own_attempt.py`, `test_grader_sees_the_work.py`, `test_the_grader_retry_says_what_was_wrong.py` |
| 24 | `3be31f26` fix(agentkit): TRIM takes a charset | `test_satisfaction_is_written_by_a_gate_run.py`, `test_the_session_reports_its_best_iteration.py` |
| 25 | `82786437` feat(loop): declare 'harness', refuse it by name | **new** `test_a_disabled_intent_is_refused_by_name.py` |
| 26 | `d1ecfad2` feat(loop): a proposal names the session that wrote it | **new** `test_every_proposal_names_a_session.py` (348 ln) |
| 27 | `130a8a33` feat(graph): an agent is an address, not a job | **new** `test_every_agent_directory_has_a_node.py`; + `test_a_claim_is_drawn_as_a_claim.py`, `test_apex_public_projection.py` |
| 28 | `7bb32ac1` feat(wing): /questions accounts for what expired | **new** `test_the_questions_ledger_counts_the_unswept.py`; + `test_security_presenter_gates.py` |
| 29 | `930d431e` feat(loop): show the harness before the switch | **new** `test_the_harness_toggle_defaults_off.py`; + `test_keap_table_concepts.py`, `test_security_presenter_gates.py` |
| 30 | `8610862f` feat(agentkit): one_shot mode | **new** `test_one_shot_mode_makes_one_call.py` |
| 31 | `f1f4ca46` feat(ops): a harness that answers where, not whether | **new** `test_the_ops_harness_reports_a_boundary.py` |

---

## 3. Machinery commits flagged

**One real gap.**

- **`63036e6d` — `tools/workflow-tree.py` (new) + `tools/wf-panel.sh` (new), no gate
  anywhere.** `test_the_control_centre_shows_state.py` covers `nos-cc.sh` and does not
  mention either file; grep across `tests/` returns nothing for `workflow-tree` or
  `wf-panel`. A renderer that silently draws a stale or truncated tree looks exactly
  like one that works — the same failure shape the control-centre doctrine was written
  for. The cheapest close: run `tools/workflow-tree.py` against
  `docs/plans/rsi-research/04-implementation-workflow.js` and assert every phase name
  the linter finds appears in the output.

**Two soft flags, neither blocking.**

- **`63eba4a2`** changed `files/anatomy/face/src/lib/tables/view.ts` and
  `contracts/index.ts` without touching `view.test.ts`. The standing vitest passes
  (323/323), so the change is covered, but nothing new pins the specific behaviour the
  commit claims. `tools/nos-cc.sh` in the same commit is covered by the standing
  control-centre gate.
- **`d184579e`** is typed `docs(roadmap)` while editing `tools/roadmap-seed.py`, a
  generator. It is gated (7 standing gates), so the risk is archaeological, not
  structural: a future `git log --grep` for tool changes will miss it.

Everything else that touched machinery without a new gate (`6df3416c`, `f4992c3d`,
`7ec9d758`, `7ae7858a`, `1e552a8e`, `ef2ae628`) touched only the workflow script or
`workflow-lint.py`, both executed by `test_workflow_scripts_are_valid.py`, which
shipped in this range.

---

## 4. The forbidden list, swept

| Looked for | Found |
|---|---|
| converge commands in new code | **none.** `ansible-playbook` / `docker compose` / `launchctl` appear only in `.github/workflows/ci.yml`, `.woodpecker/tests.yml`, `CLAUDE.md` and `docs/idea/11-*.md` — all pre-existing, none added by a new tool |
| prose-reading gates | **none as the load-bearing assertion.** Only one `.md` read exists across the 16 new gates: `test_the_harness_toggle_defaults_off.py::test_the_contract_records_the_addendum`, which asserts the doctrine list and `budget.ALWAYS_FORBIDDEN` *agree* — a sync check, not prose-as-fact. Its five sibling tests import `budget`, hand `check_paths` a proposal editing the toggle fixture, and require a Violation back. Three gates (`test_a_revision_sees_its_own_attempt`, `test_the_grader_retry_says_what_was_wrong`, `test_grader_sees_the_work`) read PHP **source**, not prose, and each says so in its docstring and names the behavioural gate that exercises the same code for real (`test_a_repaired_output_says_so.py`, which shells out to php) |
| satisfaction written by non-readers | **none.** `Runner.php:940` takes the verdict from `GateOracle::judge` — an exit code from a `nos-loop` gate run — and the grader is called *only when the verdict is already unsatisfied* (`:947`), able to add notes and nothing else. Enforced below the code by two SQLite triggers (`init-db.php:744-755`) that `RAISE(ABORT)` on a `satisfied` row whose `gate_run_id` is NULL or whitespace, and `test_satisfaction_is_written_by_a_gate_run.py` **attempts the forbidden INSERT** rather than grepping for the trigger. `markOutputRepaired` is called by the reader of the repair, not by `OutputRepair` |
| surviving `bypassPermissions` | **removed from the loop's entry.** `tools/loop-propose.py` now spawns `tools/run-agent.sh`; the only occurrences in that file are the docstring explaining the replacement, and `test_every_proposal_names_a_session.py:235` asserts neither `bypassPermissions` nor `--print` survives in the argv. It **remains, by design and out of scope**, in the claude-CLI runtime: `files/anatomy/scripts/pulse-run-agent.sh:323` and `ClaudeCliAdapter.php:111`. Both are pre-existing and pinned by `test_runner_child_env_and_attribution.py` |
| agent memory | **gone.** `app/AgentKit/Memory/` does not exist; `Dreamer`, `MemoryStore`, `AgentMemoryStoreRepository`, `bin/dream-agent.php` deleted; `loadMemoryContext` has zero hits in live code; `agent_memory_stores` absent from `schema-extensions.sql`. Every surviving mention is in the gate that forbids the return, the roadmap row recording the deletion, or archived docs. `test_agent_memory_does_not_return.py` opens the SQL and stats each deleted path |
| a second agent-run lock | **none.** One implementation, `files/anatomy/scripts/agent-run-lock.sh`, sourced by `tools/run-agent.sh`, `pulse-run-agent.sh` and `files/vuln-scan/scan-runner.sh`. The other `mkdir`/`flock` mutexes in the repo (`deploy-from-ci.sh`, `worktree-lease.py`, pulse `daemon.py`'s PID file) guard unrelated resources and predate this branch. `test_cli_lock_excludes_agentkit_slots.py` and `test_one_agent_lock_for_every_claude.py` pin the slot split |
| embryo machinery | **none built.** Every hit is a Q5 deferral note in the research docs, the workflow script's own out-of-scope header, or a roadmap row recording the deferral |
| tenant-DB machinery | **none.** One `CREATE DATABASE` hit, a pre-existing comment in `anatomy-graph-gen.py` describing `roles/pazny.postgresql/tasks/post.yml` |
| `nos-bi` | **not in code.** Eleven hits, all in `docs/plans/rsi-research/` recording the decision to retire it (`03-questionnaire.md:307`: "`nos-bi` is retired as a name; `nos-ops` is the client plane"). Zero hits in `tools/`, `files/`, `tests/`, `state/`, `roles/` |
| `tier` used for the plane split | **none.** The split is spelled *plane* throughout: `ops plane`, `sere plane`, `nos-ops`, `ops_plane_tool_surface`, `ops-plane`. Surviving `tier` uses are the three legitimate axes — RBAC (`authentik.tier`), face-app complexity (F-tier), and model cost band (`# haiku is the right (cheapest) tier`). One near-miss worth a future rename: `tools/nos-ops-harness.py:42` names a **model-size** band `TIER_B` / `tier_measured`. It is not the plane split and not RBAC, but it is a fourth meaning for the reserved word in brand-new code — `SIZE_BAND_B` would cost one sed |

---

## 5. What landed

**Ops plane — identity.** Each agent presents its own Wing principal
(`NOS_AGENT_WING_TOKEN`, resolved in `run-agent.sh` from `~/.nos/secrets.yml`), so
`events.actor_id` names the agent rather than `ansible-provisioned`. `api_tokens`
gained a `scopes` column; `TokenRepository::permits()` decides route class;
`BaseApiPresenter` refuses with "Token scope does not permit &lt;VERB&gt; on the ops
plane". `mcp-wing` split into `McpWingReadTool` / `McpWingWriteTool`; the KEAP tool's
`keap.read` no longer serves POST. Bone got the matching half: `mint_agent_token()`
performs the client-credentials exchange the bound path had been skipping entirely,
which is why every scoped Bone endpoint answered 401 on the first bound night.

**Satisfaction.** Moved from a model's opinion to a gate run's exit code.
`GateOracle` shells to `nos-loop` (Decision 6: Bone's HTTP is the only judge),
reports the **best** iteration rather than the last, stops one iteration past an
unbeaten peak, and ranks `indeterminate < fail < pass` so absence never outranks a
clean failure. Two DB triggers make `satisfied` unwritable without a `gate_run_id`.
The grader survives as a writer of revision *notes* only, with a three-stage output
contract: deterministic parse → one format-only re-ask → UNPARSEABLE, and a bad enum
value is a content fault that is never re-asked.

**Loop.** `harness` is declared in `INTENT_CLASSES` and refused by name in
`DISABLED_INTENTS`, with the toggle (`harness_proposals_enabled`) shipping `false`
as a YAML boolean and both its files on `budget.ALWAYS_FORBIDDEN` with reason
`operator-consent` — the loop cannot propose enabling its own harness editing.
`LoopEditorPresenter` renders the committed fixture and `ledger.py`'s enum rather
than a second copy. `loop_proposals` gained `session_uuid`, and the proposer runs
through AgentKit instead of an unattended `claude --print`.

**Deletions.** `Dreamer`, `MemoryStore`, `dream-agent`, `AgentMemoryStoreRepository`,
`Coordinator`, `ProcessPool` and the `agent_memory_stores` table — with their gates
deleted in the same commit and one new gate forbidding the return.

**Lock.** One global N=1 mutex became three `agentkit` slots plus a distinct `cli`
slot, so an AgentKit run and a claude-CLI run no longer contend.

**Measurement.** `tools/nos-ops-harness.py` scores small local models on a labelled
task family by exact match — a code oracle, never self-assessment — and reports
`UNKNOWN` for any size nobody ran, with `ops_plane_tool_surface: CLOSED` and a
`closed_because` that names the missing number. `one_shot` mode gives it one call
and one verdict.

---

## 6. What was skipped, and under which answer

| Skipped | Answer |
|---|---|
| Embryo machinery — no packaging, no destination-site contract, no frozen configuration | **Q5 (c)** — defer until an ops-plane agent is `proven`. Nothing in these 31 commits creates it |
| Per-tenant databases | **Q11** — out of scope |
| Agent memory of any kind (Dreams, cross-session stores, `loadMemoryContext`) | **Q8** — no agent memory, ever. Deleted rather than parked, with a gate against the return |
| A `harness` **proposal kind** that can be acted on | **Q6** — surface first, kind later. The intent class is declared and refused; the toggle is built, visible, and OFF |
| OPRO-shaped prompt optimisation | `05-sources.md` — queued, not adopted; the "fits nos-bi" claim was extrapolation. Revisit after the ops harness produces a number |

---

## 7. Operator next — commands printed, never run

Nothing below was executed. The repo is not the running system; none of this is live
until a converge moves it.

### a. Review and land the branch

```bash
cd /Users/pazny/projects/nOS
git log --oneline dev..feat/planes-build          # 31 commits
git diff --stat dev...feat/planes-build           # 126 files
python3 -m pytest tests/anatomy -q                # expect 4250 passed, 46 skipped
(cd files/anatomy/face && npm test)               # expect 323 passed

# fast-forward into dev (CLI is fine for feat/* → dev; no PR required)
git switch dev && git merge --ff-only feat/planes-build
git push origin dev
```

`dev → master` stays a PR, per CLAUDE.md. Do not push `feat/planes-build` to
`master`.

### b. Converge — the only thing that makes any of this live

The Wing post tasks mint the scoped agent tokens **and** run `init-db.php`, which
adds `api_tokens.scopes` and the two `agent_iterations_satisfied_*` triggers. Note
the condition on `tasks/stacks/stack-up.yml:415` — the wing **post** role is gated on
`'iiab' in _remaining_stacks`, so a bare `--tags wing` renders without provisioning.
Run the full layer:

```bash
# host organs: bone (ledger/budget/looproutes), pulse (secrets.py, agent-run-lock),
# agent manifests, skills contracts
ansible-playbook main.yml --tags bone,pulse,anatomy,skills

# wing: AgentKit classes, GateOracle, LoopEditor + Questions routes,
# init-db.php (scopes column + satisfaction triggers), scoped token mint
ansible-playbook main.yml --tags wing,security

# keap + face: loop-config table seed, roadmap table, the tables view change
ansible-playbook main.yml --tags keap,face
```

If you prefer one pass, a plain `ansible-playbook main.yml` covers all of it.

### c. Verify the mint rather than assume it

The tokens are provisioned by the playbook; check that they landed and carry the
scopes the commits claim, before trusting a bound run:

```bash
sqlite3 ~/wing/app/data/wing.db \
  "SELECT name, scopes FROM api_tokens ORDER BY name;"
# expect: conductor|wing.read,wing.write   librarian|wing.read,wing.write
#         openclaw|wing.read,wing.write    surveyor|wing.read
#         upgrade-architect|wing.read,wing.write

sqlite3 ~/wing/app/data/wing.db \
  "SELECT name FROM sqlite_master WHERE type='trigger'
    AND name LIKE 'agent_iterations_satisfied%';"
# expect both: _insert and _update

grep -c '_wing_api_token' ~/.nos/secrets.yml    # the per-agent principals
```

### d. Then, and only then, a bound run

```bash
tools/run-agent.sh --agent=surveyor              # takes one agentkit lock slot
tools/agent-status.py                            # how the run ended
tools/red-status.py                              # what is red now
```

### e. The ops-plane measurement, when a local binding is armed

The harness reports `UNKNOWN` for every size until something actually runs, which is
correct and is also why it currently answers nothing:

```bash
NOS_ARMED_BACKENDS="<backend>" tools/nos-ops-harness.py \
  --family state/ops-task-families/invoice-extract \
  --agent <one_shot-agent-name>
```

Until the 3–7B band produces a number, `ops_plane_tool_surface` stays `CLOSED` and
Q5 (embryos) stays deferred by its own condition.

### f. One optional close, at your discretion

`tools/workflow-tree.py` and `tools/wf-panel.sh` ship ungated (§3). If they are
going to be relied on, the gate is small — render the tree for
`docs/plans/rsi-research/04-implementation-workflow.js` and assert every phase the
linter parses appears in the output.
