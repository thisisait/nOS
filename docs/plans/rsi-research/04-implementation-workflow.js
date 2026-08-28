// agentic-planes-build — the SECOND ultracode workflow.
//
// DEPENDS ON ANSWERED QUESTIONNAIRE (undefined/03-questionnaire.md), passed as
//   args.answers (path to the answered file). It refuses to run unanswered.
// Answers consumed:  Q1/Q2 (names → all prose and identifiers),
//   Q3 (ops-plane go/measure/park → whether the 'Ops harness' phase runs),
//   Q6 (harness proposals → NOT built here regardless; recorded in the denylist judge),
//   Q7 (denylist contents), Q8 (memory: this workflow only DELETES; rebuild is out of scope),
//   Q9/Q10 (oracle + grader rules), Q13 (ledger join yes/no + ceiling),
//   Q14 (per-agent write-route grants), Q15 (/questions channels + expiry policy).
//
// RULES the phases below enforce:
//  - every writer phase is followed by a verifier phase, and the verifier is a DIFFERENT
//    agent that did not write the code (it reads the diff + runs the gates);
//  - new machinery ships WITH the gate that pins it, and the gate reads the artifact
//    (a class instance, an emitted JSON, a DB constraint) — never the prose;
//  - NOTHING here converges the estate. Deliverable is commits on a feat/ branch off dev.
//    The operator converges. tools/nos-stacks.sh, ansible-playbook, docker: all forbidden;
//  - agent budget: 17 agents total (counted per phase comment).

export const meta = {
  name: 'agentic-planes-build',
  description:
    'Build nos-sere finishing work (identity, oracle satisfaction, ledger join, surfaces) ' +
    'and the questionnaire-gated ops-plane groundwork. Writers and verifiers are disjoint. ' +
    'No converge — commits only.',
  phases: [
    { title: 'Answers', detail: 'parse the questionnaire; refuse unanswered' },
    { title: 'Prune', detail: 'delete dead machinery (Dreamer, Coordinator/ProcessPool)' },
    { title: 'Grant', detail: 'mcp-wing split + per-agent principals' },
    { title: 'Oracle', detail: 'gateset-written satisfaction, grader demotion, best-of' },
    { title: 'Ledger', detail: 'proposer onto AgentKit; proposals name sessions' },
    { title: 'Surface', detail: 'agent node kind + /questions presenter' },
    { title: 'Ops harness', detail: 'one_shot mode + measurement harness (Q3-gated)' },
    { title: 'Review', detail: 'independent gate sweep + report; no writes' },
  ],
}

const NOS = '/Users/pazny/projects/nOS'

const RULES = `
HARD CONSTRAINTS
- Work on a feat/ branch off dev. Commit per completed unit, Conventional Commits, surgeon
  tone, subject <= 50 chars. NO push to any remote. NO converge: never run ansible-playbook,
  tools/nos-stacks.sh, docker compose, launchctl. The repo is not the running system.
- A gate ships in the same commit as the machinery it pins, and it must read the ARTIFACT
  (instantiate the class, open the emitted JSON, attempt the forbidden insert) — a gate that
  greps prose or that the change itself can edit into passing is not a gate.
- Run 'python3 -m pytest tests/anatomy -q' before declaring any unit done; a red gate you did
  not touch is a STOP, not a workaround.
- Doctrine: success markers are written by readers; absence is UNKNOWN, not green.
`

phase('Answers')

// 1 agent. Why: every later phase branches on operator decisions; running on defaults would
// hardcode decisions the operator has not made — the exact thing this workflow must not do.
const answers = await agent(
  `Read the answered questionnaire at ${args.answers} (and ${NOS}/undefined/00-terminology.md,
   01-architecture.md for context). Extract every chosen option. If ANY of Q1-Q16 is
   unanswered or ambiguous, set blocked=true and list the unanswered ids — do not infer.`,
  {
    label: 'answers:parse', phase: 'Answers', effort: 'medium',
    schema: {
      type: 'object', additionalProperties: false,
      required: ['blocked', 'q'],
      properties: {
        blocked: { type: 'boolean' },
        unanswered: { type: 'array', items: { type: 'string' } },
        q: { type: 'object' }, // { Q1: 'a', Q3: 'a', Q13: 'a', ... } plus free-text values
      },
    },
  })

if (answers.blocked) {
  log(`REFUSED: questionnaire unanswered: ${(answers.unanswered || []).join(', ')}`)
  throw new Error('questionnaire incomplete — answer 03-questionnaire.md first')
}
const Q = answers.q
const opsName = Q.Q1_name || 'nos-ops'
log(`answers ok — client plane: ${opsName}, ops-plane mode: Q3=${Q.Q3}`)

phase('Prune')

// 2 agents (writer + verifier). Why first: deletions cannot break a runtime path that was
// never reachable, and removing the gravity well (three corpus reports recommended building
// ON Dreams) before any build phase prevents the workflow's own agents rediscovering it.
await pipeline(
  () => agent(
    `${RULES}
     DELETE dead AgentKit machinery, verified-dead by two judges:
     - files/anatomy/wing/app/AgentKit/Memory/Dreamer.php and MemoryStore facade usage,
       bin/dream-agent.php, tests/anatomy/test_agentkit_dreams.py
     - Coordinator.php + ProcessPool.php and their DI wiring in app/config/common.neon
       (all seven manifests are multiagent.type: solo — verify that first; if any is not,
       STOP and report instead of deleting).
     KEEP: the agent_memory_stores table in schema-extensions.sql (Q8=${Q.Q8}: rebuild is a
     separate decision), Runner::loadMemoryContext() may be deleted with its docblock.
     Update composer autoload if needed; run the wing lockfile-sync gate.`,
    { label: 'prune:write', phase: 'Prune', effort: 'high' }),
  () => agent(
    `${RULES}
     VERIFY the prune commit(s) you did NOT write: read the diff on the feat branch.
     - grep the whole repo for Dreamer, dream-agent, ProcessPool, Coordinator, isCoordinator,
       loadMemoryContext — remaining references must be schema/table only;
     - run pytest tests/anatomy and composer validate --strict in files/anatomy/wing;
     - confirm no file outside the named set changed. Report pass/fail per check.`,
    { label: 'prune:verify', phase: 'Prune', effort: 'medium' }),
)

phase('Grant')

// 3 agents (2 writers in parallel-safe files + 1 verifier). Why: identity is the ordering
// principle — every later capability presents a principal this phase creates. Items 1+2 of
// 01-architecture.md.
await parallel([
  () => agent(
    `${RULES}
     ITEM 1 — split mcp-wing (files/anatomy/wing/app/AgentKit/Tools/McpWingTool.php) into
     mcp-wing-read (GET only, scope wing.read) and mcp-wing-write (POST, scope wing.write,
     per-route allowlist). Register both in app/config/common.neon. Update the six agent
     manifests per Q14=${Q.Q14}: ${Q.Q14 === 'b'
       ? 'first run the SELECT over events (agent_tool_use, tool=mcp-wing, method=POST, last 90d) against a READ-ONLY copy of wing.db if present on this host, else fall back to zero grants and say so'
       : 'zero write grants for all six'}.
     SHIP THE GATE in the same commit: tests/anatomy/test_a_tool_refuses_the_verb_its_scope_does_not_name.py
     — instantiate every registered tool class, drive a POST payload under a read-only scope
     roster, assert ToolResult::error (via the php test bridge the suite already uses for
     presenter gates; find it, do not invent a new bridge).`,
    { label: 'grant:tool-split', phase: 'Grant', effort: 'high' }),
  () => agent(
    `${RULES}
     ITEM 2 — per-agent Wing principal. api_tokens gains a scopes column (idempotent ALTER in
     schema-extensions.sql, same sweep pattern as the P1 events ALTERs); BaseApiPresenter::
     startup() enforces route-class vs token scopes; McpWingTool subclasses read a per-agent
     token (env NOS_AGENT_WING_TOKEN minted by tools/run-agent.sh from ~/.nos/secrets.yml,
     falling back to WING_API_TOKEN with a logged WARN so nothing breaks pre-converge).
     SHIP THE GATE: tests/anatomy/test_the_token_that_called_is_the_agent_that_ran.py — a
     reader over a fixture events DB asserting recorded token name == owning session agent,
     plus the 403 negative (read-scoped token on a write presenter).`,
    { label: 'grant:principal', phase: 'Grant', effort: 'high' }),
])
await agent(
  `${RULES}
   VERIFY the Grant phase (you wrote none of it): read both diffs; run the two new gates plus
   the full tests/anatomy suite; then attempt the bypass BOTH gates must catch: (1) call the
   write tool with only wing.read in the roster, (2) hit a write presenter with a read-scoped
   token fixture. If either succeeds, the phase FAILED — report the hole, do not patch it.`,
  { label: 'grant:verify', phase: 'Grant', effort: 'high' })

phase('Oracle')

// 2 agents. Why: makes outcome_satisfied mean something a reader wrote (items 3+4) — the
// precondition for every success-rate surface and for Q6's revisit counter.
await pipeline(
  () => agent(
    `${RULES}
     ITEMS 3+4 — oracle-written satisfaction, per Q9=${Q.Q9}, Q10=${Q.Q10}:
     - agent.schema.yaml: outcomes: requires gateset: naming an entry in state/judge-sets.yml;
       ${Q.Q10 === 'a' ? 'model.grader required with outcomes:, must differ from model.backend'
                        : 'grader optional; oracle output is the revision feedback'}.
     - schema-extensions.sql: agent_iterations.gate_run_id, and the constraint that
       outcome_result='satisfied' requires it NOT NULL (trigger or CHECK — the constraint
       lives in the SCHEMA, not in a test).
     - Runner.php runOutcomeLoop: satisfaction = the gateset subprocess exit read by the
       runner's reader path, grader demoted to needs_revision feedback only; report the
       BEST oracle-scored iteration, cap continuation past a peak at one iteration
       (arXiv:2607.25886: 78.26% of self-continued searches end below peak).
     SHIP THE GATES: test_satisfaction_is_written_by_a_gate_run.py (attempt the bare insert,
     assert the DB refuses) and test_the_session_reports_its_best_iteration.py (stub oracle
     pass->fail->fail, assert iteration 1 reported).`,
    { label: 'oracle:write', phase: 'Oracle', effort: 'high' }),
  () => agent(
    `${RULES}
     VERIFY Oracle phase: run both new gates + full suite; try to write satisfied without a
     gate_run_id through every code path that touches outcome_result (grep them all); confirm
     the grader can no longer write satisfaction; confirm existing agents WITHOUT outcomes:
     blocks still schema-validate. Report per-path.`,
    { label: 'oracle:verify', phase: 'Oracle', effort: 'high' }),
)

phase('Ledger')

// 2 agents, Q13-gated. Why: joins the two provenance systems — until a proposal names a
// session, "AgentKit-driven nos-loop" is two systems sharing a string.
if (Q.Q13 !== 'c') {
  await pipeline(
    () => agent(
      `${RULES}
       ITEM 5 — join the ledgers, per Q13=${Q.Q13}${Q.Q13 === 'b' ? ` (proposer token ceiling: ${Q.Q13_tokens})` : ''}:
       - files/anatomy/bone/ledger.py: loop_proposals gains session_uuid (idempotent ALTER);
         looproutes.py propose accepts + stores it.
       - tools/loop-propose.py: replace the claude --print bypassPermissions spawn with an
         AgentKit run via bin/run-agent.php (anthropic adapter — the only adapter that keeps
         tools, state/llm-backends.yml:26-28), passing the session uuid into the proposal
         POST. Keep the mkdir mutex and the weakness-id plumbing unchanged.
       SHIP THE GATE: test_every_proposal_names_a_session.py — run the real proposer entry
       point against temp Bone+Wing DBs, assert the JOIN: every new loop_proposals row has a
       matching agent_sessions.uuid whose model_uri resolved through BindingResolver.`,
      { label: 'ledger:write', phase: 'Ledger', effort: 'high' }),
    () => agent(
      `${RULES}
       VERIFY Ledger phase: run the new gate + full suite; grep tools/loop-propose.py for any
       surviving 'bypassPermissions' or bare 'claude --print'; confirm loop-pr.py and
       loop-review.py still read proposals correctly (they must tolerate NULL session_uuid on
       historical rows). Report.`,
      { label: 'ledger:verify', phase: 'Ledger', effort: 'medium' }),
  )
} else {
  log('Q13=c: ledger join SKIPPED by operator decision — two provenance systems remain')
}

phase('Surface')

// 3 agents (2 writers, 1 verifier). Why: renders what is already recorded — the operator
// cannot supervise a loop they cannot see (02-visualisation.md).
await parallel([
  () => agent(
    `${RULES}
     Graph model: tools/anatomy-graph-gen.py emits agent:<name> as a 14th node kind from
     files/anatomy/agents/*/agent.yml (charter/runner_status/mode attrs; edges: agent->tool,
     agent->authentik client from default.config.yml authentik_agent_clients, agent->backend
     from model.backend + state/llm-backends.yml as a NEW source, pulse-job->agent trigger
     edges). Add 'agent' to NodeKind in files/anatomy/face/src/lib/anatomy/graph.ts.
     runner_status becomes an enum in agent.schema.yaml (unproven|scheduled|parked|deferred|
     proven). Regenerate state/anatomy-graph.json.
     SHIP THE GATE: test_every_agent_directory_has_a_node.py — reads the EMITTED json against
     the filesystem.`,
    { label: 'surface:graph', phase: 'Surface', effort: 'high' }),
  () => agent(
    `${RULES}
     /questions surface, per Q15 (channels=${Q.Q15_channels}, expiry=${Q.Q15_expiry}):
     Wing QuestionsPresenter + route + latte view over agent_questions (open queue, answered
     by/via, expired-into-default count — the number that says the loop outran the operator).
     Tier-gate with the existing $minAccessTier pattern (BasePresenter). Respect the four
     existing agent_questions gates — read them BEFORE writing; the answering path
     (reconcile-inbox.php) is not yours to touch.
     SHIP THE GATE: extend the presenter-gate contract test to cover QuestionsPresenter.`,
    { label: 'surface:questions', phase: 'Surface', effort: 'high' }),
])
await agent(
  `${RULES}
   VERIFY Surface phase: run the new gates + suite; open the regenerated anatomy-graph.json
   and hand-check surveyor's node (charter attr present? tools edges = its manifest roster?
   authentik edge present?); render the questions view via the wing live-verify recipe
   (memory: port 9000 + edge token headers) ONLY if a deployed Wing exists on this host,
   else latte-lint the template. Report.`,
  { label: 'surface:verify', phase: 'Surface', effort: 'medium' })

phase('Ops harness')

// 3 agents, Q3-gated. Why: the ops plane's go/no-go is a measurement, not a feeling — this
// phase builds the instrument, not the plane.
if (Q.Q3 === 'a' || Q.Q3 === 'b') {
  await pipeline(
    () => agent(
      `${RULES}
       one_shot mode + measurement harness (plane name: ${opsName}, model boundary Q4=${Q.Q4}):
       - agent.schema.yaml + Runner.php: mode: one_shot — bind, ONE call, validate the emitted
         chain against a schema, record. Branch at session open; no tool-use loop, no outcome
         loop. (~60 LOC; NOT a fork.)
       - tools/${opsName}-harness.py: given a task-family dir (labelled sample set: inputs +
         expected extractions), run each armed local binding from state/llm-backends.yml in
         one_shot mode, score by exact label reproduction (code oracle — the model NEVER
         self-assesses), write a per-model report artifact (json).
       - ship ONE example task family with >=20 labelled samples (synthetic invoices are fine;
         label them by hand in the fixture, not by a model).
       SHIP THE GATE: test_one_shot_mode_makes_one_call.py — stub client, assert exactly one
       send() and that a schema-invalid chain records failed, never satisfied.`,
      { label: 'ops:harness', phase: 'Ops harness', effort: 'high' }),
    () => agent(
      `${RULES}
       VERIFY Ops harness: run the gate + suite; run the harness against the fixture set with
       a STUB binding (no real model call needed to prove the plumbing); confirm the score is
       computed by the harness code from labels, and that no code path lets model output set
       its own score. Report — and state plainly that NO capability claim exists until the
       operator arms a real local binding and runs it.`,
      { label: 'ops:verify', phase: 'Ops harness', effort: 'medium' }),
  )
} else {
  log(`Q3=${Q.Q3}: ops plane parked — no ops-plane code written this run`)
}

phase('Review')

// 1 agent, read-only. Why: a final reader that wrote nothing — the workflow's own success
// marker is written by a non-writer, per doctrine.
const review = await agent(
  `${RULES}
   READ-ONLY final review. You wrote nothing in this workflow. On the feat branch:
   - run the FULL gate suite (pytest tests/anatomy -q) and report the exact counts;
   - list every commit with the gate(s) it ships; flag any machinery commit without one;
   - grep for the forbidden: converge commands in any new code, prose-reading gates,
     satisfaction written by non-readers, surviving bypassPermissions;
   - write ${NOS}/undefined/06-build-report.md (this ONE file write is permitted): what
     landed, what was skipped and under which questionnaire answer, the exact commands the
     OPERATOR must run next (converge, token mint, GitHub push) — commands printed, never run.`,
  { label: 'review:final', phase: 'Review', effort: 'high',
    schema: {
      type: 'object', additionalProperties: false,
      required: ['gatesPassed', 'gatesFailed', 'commitsWithoutGates', 'operatorNext'],
      properties: {
        gatesPassed: { type: 'number' },
        gatesFailed: { type: 'number' },
        commitsWithoutGates: { type: 'array', items: { type: 'string' } },
        operatorNext: { type: 'array', items: { type: 'string' } },
      },
    } })

log(`done: ${review.gatesPassed} gates green, ${review.gatesFailed} red, ` +
    `${review.commitsWithoutGates.length} unpinned commits — operator steps in 06-build-report.md`)
