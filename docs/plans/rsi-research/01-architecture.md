# The shared abstraction — one runtime, two planes

Status: DECIDED where the two judges agree and the evidence is verified; QUESTIONNAIRE-GATED
where they disagree or the corpus is silent. Vocabulary per `00-terminology.md`.

## 0. Doctrine constraints that bound everything below

1. Absence is never success; a missing source is UNKNOWN, not green.
2. The success marker is written by a READER, never by the code that attempted the work.
3. A detector reads the artifact, not the prose describing it.
4. A gate you can satisfy by editing the gate is not a gate.
5. The repo is not the running system — only an operator converge moves source into runtime.
6. Loop contract non-goals stand (`docs/idea/11-agentic-loop-contract.md:562-587`): no LLM
   judge (not even advisory), no auto-apply, no new daemon/port/organ.

## 1. What already exists vs what is new

The estate has been burned by plans that re-describe existing wiring as work. So, explicitly:

**Already built, keep untouched:** the agent-as-directory contract + schema gate; `Runner`'s
session lifecycle, ceilings, synthesis reserve, retry ladder (local research §1 — the bounds
work; the ceremonies don't finish, which is a different problem); the binding registry
(`state/llm-backends.yml` — the only concept already general enough for two planes); the loop
ledger with its WORM triggers and code-only verdict actor; the three-YES merge reader
(`tools/loop-review.py:188-246`); the Authentik client-credentials exchange on the CLI path;
`actor_action_id == agent_sessions.uuid` lineage; the A9 notification shape; the GDPR
Article-30 block per agent.

**Built and dead, delete:** `Memory/Dreamer.php` (526 lines, 0 rows, no caller, its only gate
pins an uncalled method's *position* — rule 3's own failure), `bin/dream-agent.php`,
`tests/anatomy/test_agentkit_dreams.py`; `Coordinator.php` + `ProcessPool.php` (~800 lines,
DI-wired, unreachable — all seven manifests `multiagent.type: solo`). Judge B's graveyard
verdict, adopted over Judge A's keep-the-table variant: the table's *rebuild* (verdict-reader
writer, ACE-style append-only deltas) is real design but it is a memory mechanism bolted onto
a loop that has never completed — the estate's own named failure mode (Batch 4, Batch 13,
independently derived). The `agent_memory_stores` table itself stays in the schema (dropping a
table is a migration for zero gain); it just loses its writer. Rebuild is questionnaire Q8.

**Half-built, FINISH (this is the work):** items 1–5 and 7–8 below.

**Genuinely new:** the ops plane (§4) — and it is questionnaire-gated, because fourteen reports
produced zero measurements of a sub-3B model doing tool use (Judge B §4a; the nearest, LLaMA-3
3B in Thought-ICS arXiv:2602.02416, holds only in the oracle arm and degrades in the
autonomous arm).

## 2. The changes, in order (truth before capability)

Amended from Judge A §2 by Judge B's audit. Every item names its gate; every gate reads an
artifact.

| # | Change | Host | Gate |
|---|---|---|---|
| 1 | **Split `mcp-wing`** into `mcp-wing-read` (GET) and `mcp-wing-write` (POST, scope `wing.write`, per-route allowlist). Six agents hold a POST-capable tool declared `wing.read` (`McpWingTool.php:45,76-87`); `AskOperatorTool.php:26-30` calls the consequence "not hypothetical". Start every manifest at zero write grants; add on refusal evidence (Q14). | `Tools/McpWingTool.php`, `common.neon`, 6× `agent.yml` | `test_a_tool_refuses_the_verb_its_scope_does_not_name.py` — behavioural: drive POST through the instantiated class under a read roster, assert `ToolResult::error` |
| 2 | **Per-agent Wing principal.** `McpWingTool` presents a token minted for the agent, not the daemon-wide `WING_API_TOKEN` (`McpWingTool.php:35`); `api_tokens` gains a `scopes` column enforced in `BaseApiPresenter::startup()`. The per-agent rows already in `api_tokens` finally get used. | `BaseApiPresenter.php:30-57`, `TokenRepository`, `tools/run-agent.sh` | `test_the_token_that_called_is_the_agent_that_ran.py` — reader over `events`: recorded token name == owning session's agent; plus read-scoped token → write route → 403 |
| 3 | **`outcome_satisfied` requires an oracle run.** `outcomes:` gains mandatory `gateset:` naming an entry in `state/judge-sets.yml`; `agent_iterations.gate_run_id` NOT NULL for satisfied rows (constraint in `schema-extensions.sql`, not in a test — rule 4). The grader LLM survives feedback-only (`needs_revision` text); it can no longer write satisfaction. Require `model.grader != model.backend` when a grader is declared at all — today no agent sets it and `Runner.php:853-855` falls back to the proposer's own client, the exact configuration arXiv:2510.16657 (Batch 10) formally shows plateaus and reverses. | `Runner.php:831-1001`, `Outcome/Grader.php`, `agent.schema.yaml`, `schema-extensions.sql` | schema constraint + `test_satisfaction_is_written_by_a_gate_run.py` attempting the bare insert |
| 4 | **Best-of, not last-of; external stop.** Session reports the highest oracle-scored iteration; continuation past a peak capped at one further iteration. Evidence: RSIBench-Data (arXiv:2607.25886, Batch 12) — 78.26% of self-continued searches ended below their own peak; Self-Debug (arXiv:2304.05128, Batch 7) — most convergence by turn 3. This *defends* the existing ceilings against the "just raise max_iterations" pressure the three live `max_iterations_reached` rows will create (Judge B §5.2). | `Runner.php:878-991` (~40 LOC) | `test_the_session_reports_its_best_iteration.py` — stubbed oracle `pass→fail→fail`, assert iteration 1 reported |
| 5 | **Join the ledgers.** `loop_proposals` gains `session_uuid`; `tools/loop-propose.py` stops spawning `claude --print --permission-mode bypassPermissions` (`loop-propose.py:222`) and runs the proposer through AgentKit's `anthropic` adapter — the only adapter that keeps tools (`llm-backends.yml:26-28`). The estate's only *running* ceremony is currently off-lineage: no session row, no scope gate, no ceiling, no `MigrationWriteTool` allowlist (local research §6a). Both judges converge here. Cost: model calls rise from 1 to 5–30/run (tools cost turns) — accepted pending Q13, capped by the session ceilings the proposer gains in the same move. | `loop-propose.py`, `ledger.py:236`, `bin/run-agent.php` | `test_every_proposal_names_a_session.py` — JOIN across two DBs written by two processes under two credentials |
| 6 | **Staged evaluation cascade** on the judge corpus: cheap gate first (ansible-lint, the schema tests), full corpus (pytest + smoke) only on a pass. The one thing both judges keep from DGM/AlphaEvolve (arXiv:2505.22954 Batch 7; arXiv:2506.13131 §2.2 Batch 9): cost control on gates that already run, a copy of nothing. | `state/judge-sets.yml` ordering + judge-runner | existing judge gates; add a timing assertion only if measured slow — Judge B could not judge whether the corpus fits an iteration loop; **measure `pytest tests/anatomy` + smoke wall time first** |
| 7 | **Render what is recorded** (see `02-visualisation.md`): `agent:` node kind + edges; a `/questions` surface for `agent_questions` (four gates, zero readers — the human-in-the-loop channel rule 8 assumes, and it has no UI; Judge B graveyard: FINISH, "smaller than any adopt in the corpus"). | `anatomy-graph-gen.py`, `graph.ts`, one Wing presenter | `test_every_agent_directory_has_a_node.py` — detector reads emitted `state/anatomy-graph.json` against the filesystem |
| 8 | **`runner_status` → schema enum** incl. `proven` (≥1 oracle-written satisfaction). Queryable, rendered, no longer prose. | `agent.schema.yaml`, graph attr | schema gate extension |

**Deferred, explicitly (the judges' real disagreement):** *harness proposals* — letting the
loop propose edits to `agent.yml`/`system.md`/tool rosters (Judge A item 6, guarded by a
no-self-widening judge; Judge B do-not-adopt #2: the gates on an agent ARE those files, and a
proposer that edits the file the scope check reads satisfies the gate by editing the gate —
rule 4). Judge A's guard is real (refuse diffs touching the proposer's own directory or adding
scopes/tools/backends), but the capability is not needed for anything above to work, and rule
7 compounds the risk (`agent.yml` is read at session open — an unconverged repo edit changes
the next run's roster without an operator flip; note `tools/run-agent.sh` runs from the repo).
Questionnaire Q6. Also deferred: the `GD_actions` drift probe (arXiv:2505.02709, Batch 11 —
the corpus's best-evidenced mechanism, reader-computed from logs the estate already writes)
— queued behind the first non-failing baseline run, per Judge B §1.5: today every reference
run is `failed`/`error`/`max_iterations_reached` (verified live: satisfied = 0), so a drift
score would measure the distance between two failures.

No new daemon, port, or organ anywhere above. Hosts: Wing (1,2,3,4,7,8), Bone (5), existing
Pulse commands (5,6).

## 3. The seams — shared code, configuration, per-tenant

| Axis | Shared code (one copy) | Configuration (per plane/agent) | Per-tenant (ops plane only) |
|---|---|---|---|
| Identity | Authentik exchange, token mint, scope enforcement (items 1–2) | client id, scope vocabulary — sere scopes are estate nouns (`wing.read`), ops scopes are client nouns (`orders.read`, `ledger.propose`) | Authentik tenant/realm per client |
| Runtime | `Runner`, ceilings, lineage, `mode: one_shot` branch (~60 LOC at `Runner.php:406`: bind → one call → validate chain against schema → record — Judge A §3; NOT a fork) | `agent.yml` per agent; sere agents keep the six tools, **ops agents get zero tools** — the ~1B model emits a nos-lang chain, the chain is the tool call, code validates it (memory `nos-cortex-lang-vision`) | — |
| Gates | judge-runner subprocess, `CHECK(actor=…)`, three-YES merge reader, cascade (item 6) | sere ladder = repo proofs; ops ladder = **labelled sample sets** — the deployable unit is not an agent but agent+samples; the oracle is "the emitted chain reproduces the labels" (SWE-Gym's contract as a deployment rule, arXiv:2412.21139, Batch 7). Parser refuses an agent without one, like GDPR blocks today | sample sets are the client's data |
| Weakness sources | `SOURCE_REQUIRED` discipline, UNKNOWN-not-green | sere: repo readers (`weaknesses.py:1404-1419`). ops: exception rows — a chain that failed its label, a document refused, a reconciliation that did not balance | per-client source config |
| Ledger | table shapes, WORM, hash chain | — | **one SQLite file per tenant, not a tenant column** (recommended, Q11): no cross-tenant query exists in the ambition; per-file makes isolation/backup/erasure free, a column makes every query a place to forget a WHERE (Judge A §3; Judge B §4d — client rows in the operator's table breaks the Art-30 story) |
| Scheduling | Pulse; `pulse:` blocks in agent.yml (compiler already reads both manifest kinds) | cadence per agent | mutex: sere keeps the global N=1 lock (`~/.nos/agent-run.lock` — agents contend on one repo checkout anyway); ops needs per-(tenant,agent) locks *when it exists* (Judge B §4c: "many small overnight agents" and "one lock" are the same sentence) |

## 4. The two planes

**nos-sere** is §2. It is finishing, not building: the runtime's bounds, audit and cost
accounting all work (local research §6j); what is missing is enforced identity, an oracle-
written success marker, and one provenance system instead of two. When items 1–5 land, the
sentence "AgentKit-driven nos-loop" becomes true rather than aspirational.

**nos-ops** (name pending Q1) is conditional, and the condition is a measurement, not a
feeling. The corpus's honest answer at the ~1B one-shot design point is "no evidence exists"
(Judge B §4a; nine of fourteen reports' nos-bi sections empty or "none survive"). What IS
buildable without betting on the model: the `one_shot` mode branch, the sample-set parser
refusal, the per-tenant DB selection, and a **measurement harness** — one client-shaped task
family, one labelled sample set, N local models from the binding registry, oracle-scored.
That harness is the first ops-plane deliverable; the plane's go/no-go is its output (Q3).
The literature's one transferable principle for the small model is SWE-Gym's: never let the
model's own explanation be the pass/fail signal — which fits a 1B model precisely because it
removes any need for the model to self-assess (Batch 7).

**Embryos** are frozen ops-plane configurations (see `00-terminology.md` §12) and inherit both
conditions: no embryo before the ops plane is measured, and no embryo without an operator-
equivalent converge path at the destination (Judge B §4f: shipping pre-armed configurations to
sites with no one who can read the ledger is rule 7 at shipping scale).

## 5. Literature mechanisms adopted (citations)

1. **External-verifier requirement** — arXiv:2510.16657 (Batch 10): imperfect verifier sharing
   the generator's identity converges on "the verifier's knowledge center", plateaus,
   reverses. → item 3 (oracle-gated satisfaction, `model.grader` must differ). Zero new
   mechanism; it closes a field that exists and nothing sets.
2. **Post-peak degradation / external stop** — arXiv:2607.25886 (Batch 12): 78.26% of
   self-continued searches ended below their peak. → item 4, and a standing defense of the
   existing ceilings.
3. **Staged evaluation cascade** — DGM's 10→50→200 staging (arXiv:2505.22954, Batch 7) and
   AlphaEvolve's cheap-check-first (arXiv:2506.13131, Batch 9). → item 6. The archive/
   auto-apply halves of both papers stay refused (rules 5, 7, 8).
4. **Misevolution taxonomy** — arXiv:2509.26354 (Batch 10): four pathways (model, memory,
   tool, workflow) as the checklist every new capability must name its code gate on. It is
   also the argument that the estate's refusals (Dreams unwired, no tool creation) are design,
   not timidity.
5. **Sample-set-as-oracle** — SWE-Gym, arXiv:2412.21139 (Batch 7): a fixed corpus of
   verifiable tasks as the contract. → the ops plane's gate ladder and parser refusal.
6. *(queued)* **GD_actions drift probe** — arXiv:2505.02709 (Batch 11): reader-computed
   action-delta metric, 4 models × 4 settings × 20 seeds. Unblocks on the first completed run.
