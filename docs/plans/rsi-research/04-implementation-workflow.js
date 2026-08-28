// agentic-planes-build — the SECOND ultracode workflow.
//
// BUILT AGAINST THE ANSWERED QUESTIONNAIRE of 2026-08-28
// (docs/plans/rsi-research/03-questionnaire.md, passed as args.answers). It refuses to run
// against an unanswered questionnaire AND against one whose answers differ from the ones
// below — a workflow hardcodes its answers' consequences, so different answers need a
// different workflow, not a silent reinterpretation.
//
// MEASURED EVIDENCE, added 2026-08-28 after this script was written. Three ceremonies were
// fired through the Pulse daemon on the real estate; the record is
// docs/plans/rsi-research/07-first-bound-night.md and every phase below that it touches
// cites it. It changed nothing about WHAT to build and a great deal about WHY, because two
// of this script's phases were designed against inference and now stand on measurement:
//   * the HMAC fix works and the first AgentKit session ever reached outcome_satisfied
//     (df2a5477) — so Q8/Q10's unblocking condition is met;
//   * across the two runs with real intake the model made 40 tool calls, ALL READS, and
//     zero writes. It does not transition from reading to writing. That is the Oracle
//     phase's real target, and it is a harness problem, not a prompt typo;
//   * bound agents have NO principal: no Authentik exchange on this path at all, so
//     `actor_id` is an assertion. That is the Grant phase's target, now measured;
//   * `satisfied` on an EMPTY intake is today indistinguishable from satisfied after work.
//
// Answers consumed (see EXPECTED below for the exact set):
//   Q1/Q2/Q16 — names land NOW: the client plane is `nos-ops`, the split is a `plane`;
//   Q3/Q4 — measure first; the harness is parameterised over a model-size RANGE and
//     measures the boundary between the ~1B chain tier and the ~3-7B tool-use tier;
//   Q5 — embryos DEFERRED: nothing here builds embryo machinery;
//   Q6/Q7 — loop editor surface FIRST, operator toggle default OFF, the toggle itself on
//     the denylist. The `harness` proposal kind is NOT built this cycle, but its SEAMS ARE
//     CUT NOW (operator, 2026-08-28 follow-up: "think about it from the beginning") — a
//     later reader can check these three:
//       (1) `harness` enters the existing closed INTENT_CLASSES enum
//           (files/anatomy/bone/ledger.py) as declared-but-DISABLED: refused at propose
//           time this cycle, with the refusal message naming the toggle that will one day
//           govern it. The proposal-kind mechanism is already general (closed enum +
//           OPERATOR_REQUIRED_INTENTS); no special case is added later, only a set
//           membership changes.
//       (2) the toggle `harness_proposals_enabled` is a KEAP DataTable row — git-owned
//           definition + committed default-OFF fixture, the estate's config pattern — and
//           the denylist entry names that table path precisely, so "the loop may not
//           propose enabling its own harness editing" is checkable against a path, not a
//           sentiment. Wiring the ledger's refusal to READ the live toggle is the later
//           cycle's one change.
//       (3) the loop editor renders every intent class INCLUDING disabled ones beside the
//           toggle, so a harness proposal already has the place it will one day render.
//   Q8 — no agent memory, EVER: Dreamer + MemoryStore + dream-agent + the
//     agent_memory_stores TABLE are deleted, their gate deleted in the same commit, and a
//     new gate REFUSES their return;
//   Q9 — three-stage output contract: tool-produced artifacts, hardcoded parser, one
//     bounded format-only re-ask, else UNPARSEABLE; repairs are MARKED in the session row;
//   Q10 — no grader to start; if one is ever declared it must differ from model.backend;
//   Q11 — one-SQLite-per-tenant is a design assumption only: no tenant DBs this cycle;
//   Q12 — the mutex widens NOW: 3 slots for AgentKit, claude-CLI takes all three, ONE lock;
//   Q13 — proposer onto AgentKit at existing ceilings; Q14 — grandfather write routes from
//     measured use, query output ATTACHED to the commit; Q15 — /questions is Wing UI only,
//     expiry always `refuse`.
//
// RULES the phases below enforce:
//  - every writer phase is followed by a verifier phase, and the verifier is a DIFFERENT
//    agent that did not write the code (it reads the diff + runs the gates);
//  - new machinery ships WITH the gate that pins it, and the gate reads the artifact
//    (a class instance, an emitted JSON, a DB constraint) — never the prose;
//  - NOTHING here converges the estate. Deliverable is commits on a feat/ branch off dev.
//    The operator converges. tools/nos-stacks.sh, ansible-playbook, docker: all forbidden;
//  - sequencing: truth before capability — identity, oracle satisfaction, the parser
//    contract and the ledger join land before any plane work; the ops harness measures,
//    it does not build the plane;
//  - agent budget: 19 agents total (counted per phase comment).

export const meta = {
  name: 'agentic-planes-build',
  description:
    'Build nos-sere finishing work (identity, oracle satisfaction, output contract, ' +
    'ledger join, surfaces incl. the loop editor) and the Q3-gated nos-ops measurement ' +
    'harness. Writers and verifiers are disjoint. No converge — commits only.',
  phases: [
    { title: 'Answers', detail: 'parse the questionnaire; refuse unanswered or changed' },
    { title: 'Prune', detail: 'delete agent memory entirely (Q8) + Coordinator/ProcessPool; gate the non-return' },
    { title: 'Mutex', detail: 'one lock, 3 slots: AgentKit N=3, claude-CLI exclusive (Q12)' },
    { title: 'Grant', detail: 'mcp-wing split + per-agent principals; grants grandfathered from measured use (Q14)' },
    { title: 'Oracle', detail: 'gateset-written satisfaction, no grader to start (Q10), three-stage output contract (Q9)' },
    { title: 'Ledger', detail: 'proposer onto AgentKit; proposals name sessions (Q13)' },
    { title: 'Surface', detail: 'agent node kind + /questions + the loop editor with its default-off toggle (Q6)' },
    { title: 'Ops harness', detail: 'one_shot mode + range-parameterised measurement harness (Q3/Q4)' },
    { title: 'Review', detail: 'independent gate sweep + report; no writes' },
  ],
}

const NOS = '/Users/pazny/projects/nOS'
const RSI = `${NOS}/docs/plans/rsi-research`

// The answers this workflow was built for. A differing answer is a REFUSAL, not a branch.
const EXPECTED = {
  Q1: 'a', // nos-ops
  Q2: 'a', // plane
  Q3: 'a', // measure first
  Q4: 'a', // ~1B chain tier now; two-tier target (~3-7B tool-use), harness measures both
  Q5: 'c', // embryos deferred entirely
  Q6: 'c', // loop editor surface + default-off toggle; harness proposal kind only after
  Q7: 'a', // denylist floor + the Q6 toggle itself
  Q8: 'c', // no agent memory ever — KEAP is the estate's memory
  Q9: 'a', // structured artifacts; hardcoded parser -> one re-ask -> UNPARSEABLE
  Q10: 'b', // no grader to start, per-agent, added on evidence
  Q11: 'a', // one SQLite per tenant — design assumption only this cycle
  Q12: 'b', // widen now: N=3 AgentKit, CLI exclusive, ONE lock
  Q13: 'a', // proposer onto AgentKit at existing ceilings
  Q14: 'b', // grandfather write routes from measured use, attach the query
  Q15: 'wing-refuse', // Wing UI only; default_on_expiry always refuse
  Q16: 'a', // rename lands now
}

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
- Vocabulary: the client plane is nos-ops; the split is a PLANE (sere plane / ops plane) —
  never "tier", which is RBAC-reserved. Use these words in code, tests and commit messages.
- OUT OF SCOPE by operator answer: embryo machinery (Q5), per-tenant DBs (Q11), agent
  memory of any kind (Q8), the 'harness' proposal kind (Q6 — surface first, kind later).
- Doctrine: success markers are written by readers; absence is UNKNOWN, not green.
`

phase('Answers')

// 1 agent. Why: every later phase encodes an operator decision; if the questionnaire the
// operator holds has changed since 2026-08-28, running this script would silently enact
// stale decisions — the exact thing this workflow must not do.
const answers = await agent(
  `Read the answered questionnaire at ${args.answers} (context: ${RSI}/00-terminology.md,
   ${RSI}/01-architecture.md). For each of Q1-Q16 extract the chosen option from its
   '> **ANSWER (operator...)**' block as a single letter (for Q15, which has two sub-answers,
   emit 'wing-refuse' iff channels are Wing-UI-only AND expiry is always refuse; anything
   else, emit what you read). If ANY question is unanswered or ambiguous, set blocked=true
   and list the ids — do not infer.`,
  {
    label: 'answers:parse', phase: 'Answers', effort: 'medium',
    schema: {
      type: 'object', additionalProperties: false,
      required: ['blocked', 'q'],
      properties: {
        blocked: { type: 'boolean' },
        unanswered: { type: 'array', items: { type: 'string' } },
        q: { type: 'object' }, // { Q1: 'a', ... Q15: 'wing-refuse', Q16: 'a' }
      },
    },
  })

if (answers.blocked) {
  log(`REFUSED: questionnaire unanswered: ${(answers.unanswered || []).join(', ')}`)
  throw new Error('questionnaire incomplete — answer 03-questionnaire.md first')
}
const drift = Object.keys(EXPECTED).filter((k) => answers.q[k] !== EXPECTED[k])
if (drift.length) {
  log(`REFUSED: answers differ from the set this workflow encodes: ` +
      drift.map((k) => `${k} read '${answers.q[k]}' expected '${EXPECTED[k]}'`).join('; '))
  throw new Error('questionnaire answers changed — revise 04-implementation-workflow.js first')
}
log('answers ok — client plane: nos-ops, ops plane: measure-first (Q3=a)')

phase('Prune')

// 2 agents (writer + verifier). Why first: deletions cannot break a runtime path that was
// never reachable, and removing the gravity well (three corpus reports recommended building
// ON Dreams) before any build phase prevents the workflow's own agents rediscovering it.
// Q8=c makes this TOTAL: no agent memory ever — table included, and a gate against return.
await pipeline(
  () => agent(
    `${RULES}
     DELETE agent memory ENTIRELY (Q8=c: no agent memory ever; KEAP is the estate's memory)
     plus the dead multi-agent machinery — ALL in coherent commits:
     - files/anatomy/wing/app/AgentKit/Memory/Dreamer.php, Memory/MemoryStore.php,
       bin/dream-agent.php, Runner::loadMemoryContext() and every call/DI wiring of them;
     - the agent_memory_stores table: remove its CREATE (and any ALTERs/indexes) from
       files/anatomy/wing/db/schema-extensions.sql;
     - tests/anatomy/test_agentkit_dreams.py — deleted in the SAME commit as the machinery
       it pins (a gate pinning deleted machinery is a red suite; a machinery deletion whose
       gate survives is a lie either way);
     - Coordinator.php + ProcessPool.php and their DI wiring in app/config/common.neon
       (all seven manifests are multiagent.type: solo — verify that first; if any is not,
       STOP and report instead of deleting).
     SHIP THE GATE in the same commit as the deletions:
     tests/anatomy/test_agent_memory_does_not_return.py — fails if 'agent_memory_stores'
     appears anywhere in schema-extensions.sql, or if 'loadMemoryContext' / 'Dreamer' /
     'MemoryStore' reappear under app/AgentKit/. A deletion with no gate against the return
     is a deletion that gets undone. (This gate reads files that ARE the artifact — the
     schema and the class tree — not prose; grep of identifiers in source is reading the
     artifact here.)
     Update composer autoload if needed; run the wing lockfile-sync gate.`,
    { label: 'prune:write', phase: 'Prune', effort: 'high' }),
  () => agent(
    `${RULES}
     VERIFY the prune commit(s) you did NOT write: read the diff on the feat branch.
     - grep the whole repo for Dreamer, MemoryStore, dream-agent, agent_memory_stores,
       loadMemoryContext, ProcessPool, Coordinator, isCoordinator — the ONLY permitted hits
       are the new non-return gate and historical docs/plans prose;
     - run the new gate, then pytest tests/anatomy and composer validate --strict in
       files/anatomy/wing; confirm test_agentkit_dreams.py is GONE in the same commit;
     - confirm no file outside the named set changed. Report pass/fail per check.`,
    { label: 'prune:verify', phase: 'Prune', effort: 'medium' }),
)

phase('Mutex')

// 2 agents (writer + verifier). Why now (Q12=b, operator overruled the recommendation):
// bound AgentKit runs are PHP in-process — a different failure mode from the claude-CLI
// crashes (2026-05-27) the lock exists for — and may run three abreast. ONE lock stays the
// law: two locks for one invariant is the estate's signature defect, and
// agent-run-lock.sh was written to end it.
// N=3 KEPT, with the reason measured rather than inherited (operator left the count to
// this revision): wing.db runs journal_mode=WAL (read live 2026-08-28), and multi-writer
// is ALREADY the estate's condition — Wing web requests and the Pulse daemon write it
// concurrently today. Under WAL, contention cannot corrupt; it surfaces as SQLITE_BUSY on
// a writer whose busy_timeout is 0 — which is what the writer below must close. What
// would CHANGE N: measured SQLITE_BUSY / lock-wait rates from three real concurrent runs,
// not a feeling.
await pipeline(
  () => agent(
    `${RULES}
     Q12 — widen files/anatomy/scripts/agent-run-lock.sh to a SLOT DIRECTORY of N=3:
     - AgentKit (in-process PHP) acquisition takes ONE slot; a claude-CLI spawn
       (pulse-run-agent.sh, scan-runner.sh callers) takes ALL THREE slots atomically and is
       therefore still exclusive — it meets nobody, which is the invariant that survives;
     - keep the per-slot stale-owner reclaim (PID-liveness on each slot's owner file), the
       mkdir atomicity (macOS has no flock), rmdir+rm -f release (never rm -rf), the EXIT
       trap, and exit 2 on refusal;
     - ONE lock path (~/.nos/agent-run.lock as the slot dir). Do NOT introduce a second
       lock for the CLI path — read the file's own header for why;
     - update both callers only as far as passing which acquisition kind they are; do not
       restructure them;
     - the contention half of N=3: find where AgentKit opens wing.db (the Nette DI dsn /
       PDO factory) and verify a busy_timeout is set; if it is not, set one (a single
       PRAGMA busy_timeout at connection open) so three concurrent slot-holders QUEUE at
       the WAL writer lock instead of erroring SQLITE_BUSY. That pragma is what makes
       three abreast safe, not the slot count.
     SHIP THE GATE: tests/anatomy/test_cli_lock_excludes_agentkit_slots.py — run the real
     script in a temp NOS_AGENT_LOCK_DIR: acquire CLI (all slots), assert a concurrent
     AgentKit acquire returns 2; acquire three AgentKit slots, assert a fourth returns 2 and
     a CLI acquire returns 2; kill an owner PID, assert its slot is reclaimed. The gate
     EXECUTES the shell script — it does not read its text.`,
    { label: 'mutex:write', phase: 'Mutex', effort: 'high' }),
  () => agent(
    `${RULES}
     VERIFY the Mutex commit you did not write: run the new gate + full suite; grep the repo
     for any second lock path serving agent runs (the defect the file exists to end);
     confirm both callers still source the ONE script and that a plain (non-slot-aware)
     historical caller fails loudly rather than silently acquiring. Report.`,
    { label: 'mutex:verify', phase: 'Mutex', effort: 'medium' }),
)

phase('Grant')

// 3 agents (2 writers in parallel-safe files + 1 verifier). Why: identity is the ordering
// principle — every later capability presents a principal this phase creates. Items 1+2 of
// 01-architecture.md; truth before capability.
//
// ALSO MEASURED (§6): an agent-filed report carries actor_action_id NULL — the librarian's
// 201 (event 373987) is the only conductor_report an AgentKit session ever wrote and the
// only one with no session id. The architecture promises one SELECT reconstructs a run; for
// agent-filed events it does not. Same provenance problem as loop_proposals.session_uuid,
// so the Ledger phase should close both.
//
// MEASURED (07-first-bound-night.md §4): the gap is wider than "the grants are implicit".
// `McpBoneTool` sends NO Authorization header at all (McpBoneTool.php:63-68), so every Bone
// endpoint behind require_scope() (bone/auth.py:180-205) answers 401 — session 505e0f11 got
// exactly that. And it is not one tool's bug: the CLI path does an Authentik
// client_credentials exchange requesting the agent's declared scopes
// (pulse-run-agent.sh:232-252) and the bound path does NONE — neither tools/run-agent.sh nor
// bin/run-agent.php contains the string. So a bound agent presents nothing to Bone and the
// DAEMON'S SHARED WING_API_TOKEN to Wing. The writer must close the exchange, not just split
// the tool; a scoped Wing token on a runtime that never authenticates to Bone is half a
// principal. Whatever this phase ships, a bound run must end able to reach a scoped Bone
// endpoint — verify that, do not infer it.
await parallel([
  () => agent(
    `${RULES}
     ITEM 1 — split mcp-wing (files/anatomy/wing/app/AgentKit/Tools/McpWingTool.php) into
     mcp-wing-read (GET only, scope wing.read) and mcp-wing-write (POST, scope wing.write,
     per-route allowlist). Register both in app/config/common.neon.
     Q14=b — GRANDFATHER the write grants from measured use. NO HARDCODED WINDOW
     (operator amendment 2026-08-28, recorded in the Q14 ANSWER block): run the SELECT over
     the FULL available agent_tool_use history (tool=mcp-wing, method=POST) against a
     READ-ONLY copy of wing.db if one exists on this host, and have the query output STATE
     THE SPAN it covered (MIN/MAX event timestamp + row count) — a grant justified by "the
     last 90 days" when the table is three weeks old is a measurement that reads bigger
     than it is. Grant each agent exactly the routes it called.
     ATTACH THE QUERY OUTPUT TO THE COMMIT: commit the result (routes per agent + the span
     block) as docs/plans/rsi-research/artifacts/wing-write-grants.json and cite it in the
     commit body — a grant must be traceable to a measurement whose extent is visible. A
     route nobody called is NOT granted; report that absence as a finding. If no wing.db is
     readable, fall back to zero grants and SAY SO in the commit body (absence is UNKNOWN,
     not a license to guess).
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
   token fixture. Also verify Q14's traceability: every granted route in the six manifests
   appears in the committed wing-write-grants.json, and the artifact carries its span block
   (MIN/MAX timestamp + row count — no fixed window anywhere in the query; or the commit
   says zero-grants fallback). If any check fails, the phase FAILED — report the hole, do not patch it.`,
  { label: 'grant:verify', phase: 'Grant', effort: 'high' })

phase('Oracle')

// 2 agents (writer + verifier). Why: makes outcome_satisfied mean something a reader wrote
// (items 3+4) and makes the output CONTRACT honest (Q9) — the precondition for every
// success-rate surface. Q10=b: no grader to start; the oracle's raw output is the revision
// signal.
//
// MEASURED (07-first-bound-night.md §2+§3), and it reframes this phase. Two findings:
//
//   (a) THE READ/WRITE TRANSITION IS THE DEFECT. In 40 tool calls across two runs with real
//       intake, every call was a read and every one returned 200; the model paged through
//       198 unpromoted captures and issued no POST. Token ratio ~40:1 in/out. The 2026-08-17
//       note called this "a preamble, a tool call, repeated until the budget ends"; it is
//       sharper than that — the loop does not fail to produce, it fails to ACT. Q9's
//       three-stage output contract only helps if a write is attempted at all, so this
//       phase must also make the absence of a write a FIRST-CLASS OUTCOME: a run that read
//       and wrote nothing is not `outcome_failed` for a rubric reason, it is a distinct
//       recorded state, and the session row must say which. Do not paper over it with a
//       sterner prompt — a prompt change that fixes this would prove it was never a harness
//       problem, and that claim needs the measurement, not the hope.
//
//   (a2) SATISFIED WITHOUT THE DELIVERABLE — measured after this note was first written
//       (07-first-bound-night.md §6, session 5fd9074a). The surveyor re-run reached the
//       write step, its POST /api/v1/events failed 400 'Invalid JSON body', no
//       conductor_report event was ever written — and the grader returned `satisfied` with
//       EMPTY feedback, because surveyor/rubric.md never mentions filing. A run that lost
//       its whole deliverable to malformed JSON reads green today. This is this phase's
//       FIRST job, not a refinement of it: a ceremony whose deliverable is an event may not
//       be satisfied unless that event EXISTS and names the session. It is also the live
//       case for Q9's parser — the survey was lost to a bracket, not to a judgement.
//
//   (b) SATISFIED ON AN EMPTY INTAKE. df2a5477 was satisfied for handling an empty queue
//       honestly — correct, and indistinguishable from satisfied after work. The gate_run_id
//       constraint this phase adds must therefore also carry what the run ACTED ON (rows
//       judged, files written, records posted: zero is a legitimate value that must be
//       STORED, not absent). "Nothing to do" and "did the thing" may not render alike.
await pipeline(
  () => agent(
    `${RULES}
     ITEMS 3+4 + the Q9 output contract — oracle-written satisfaction, no grader to start:
     - agent.schema.yaml: outcomes: requires gateset: naming an entry in state/judge-sets.yml.
       model.grader is OPTIONAL (Q10=b — start without one, add per-agent on evidence); when
       declared it MUST differ from model.backend (schema rule + refusal in AgentLoader —
       arXiv:2510.16657 is why the same-model fallback is not an option). DELETE the silent
       fallback to the proposer's own client in Runner.php (~853-855): no grader declared
       means NO grader call, oracle raw output is the needs_revision feedback.
     - schema-extensions.sql: agent_iterations.gate_run_id, and the constraint that
       outcome_result='satisfied' requires it NOT NULL (trigger or CHECK — the constraint
       lives in the SCHEMA, not in a test).
     - Runner.php runOutcomeLoop: satisfaction = the gateset subprocess exit read by the
       runner's reader path; report the BEST oracle-scored iteration, cap continuation past
       a peak at one iteration (arXiv:2607.25886: 78.26% of self-continued searches end
       below peak).
     - Q9 THREE-STAGE OUTPUT CONTRACT: agents deliver through tools (db rows, structured
       files) — prose is a report for a human, never the artifact a verdict reads. On a
       malformed structured output: (1) a HARDCODED deterministic parser repairs SHAPE only
       (unbalanced bracket, trailing comma, fenced block, prose preamble) — no model in this
       step; (2) only if that fails, ONE bounded format-only re-ask quoting the original
       content back, no new reasoning; (3) if both fail the run records UNPARSEABLE, never
       satisfied. agent_sessions gains output_repaired (idempotent ALTER) and ANY repair —
       parser or re-ask — sets it: silent repair is a success marker written by the thing
       that failed.
     SHIP THE GATES: test_satisfaction_is_written_by_a_gate_run.py (attempt the bare insert,
     assert the DB refuses), test_the_session_reports_its_best_iteration.py (stub oracle
     pass->fail->fail, assert iteration 1 reported), and
     test_a_repaired_output_says_so.py (feed the real parser a fixable malformation, assert
     repaired content AND output_repaired set; feed an unfixable one with a stub re-ask that
     also fails, assert UNPARSEABLE and not satisfied).`,
    { label: 'oracle:write', phase: 'Oracle', effort: 'high' }),
  () => agent(
    `${RULES}
     VERIFY Oracle phase: run the three new gates + full suite; try to write satisfied
     without a gate_run_id through every code path that touches outcome_result (grep them
     all); confirm NO code path calls a grader when none is declared, and that declaring
     model.grader == model.backend is refused; confirm the parser step contains no model
     call; confirm a parser-repaired success cannot record output_repaired unset; confirm
     existing agents WITHOUT outcomes: blocks still schema-validate. Report per-path.`,
    { label: 'oracle:verify', phase: 'Oracle', effort: 'high' }),
)

phase('Ledger')

// 2 agents. Why: joins the two provenance systems — until a proposal names a session,
// "AgentKit-driven nos-loop" is two systems sharing a string. Q13=a: existing ceilings.
await pipeline(
  () => agent(
    `${RULES}
     ITEM 5 — join the ledgers (Q13=a, existing ceilings):
     - files/anatomy/bone/ledger.py: loop_proposals gains session_uuid (idempotent ALTER);
       looproutes.py propose accepts + stores it.
     - tools/loop-propose.py: replace the claude --print bypassPermissions spawn with an
       AgentKit run via bin/run-agent.php (anthropic adapter — the only adapter that keeps
       tools, state/llm-backends.yml:26-28), passing the session uuid into the proposal
       POST. The proposer now contends on the Q12 slot lock as an AgentKit acquisition —
       keep the weakness-id plumbing unchanged.
     - Q6 SEAM (1): add 'harness' to the existing closed INTENT_CLASSES enum in ledger.py
       AND to a new DISABLED_INTENTS set beside OPERATOR_REQUIRED_INTENTS — same mechanism,
       one more set, NO special case. A harness proposal is refused at propose time this
       cycle, and the refusal message names the toggle that will one day govern it
       (harness_proposals_enabled in the KEAP config table — see the Surface phase). Do
       NOT wire the ledger to read the live toggle: that is the later cycle's one change.
     SHIP THE GATES: test_a_disabled_intent_is_refused_by_name.py — POST a harness proposal
     through the real propose route against a temp ledger, assert refusal and that the
     refusal names the toggle's table path; and test_every_proposal_names_a_session.py — run the real proposer entry
     point against temp Bone+Wing DBs, assert the JOIN: every new loop_proposals row has a
     matching agent_sessions.uuid whose model_uri resolved through BindingResolver.`,
    { label: 'ledger:write', phase: 'Ledger', effort: 'high' }),
  () => agent(
    `${RULES}
     VERIFY Ledger phase: run the new gate + full suite; grep tools/loop-propose.py for any
     surviving 'bypassPermissions' or bare 'claude --print'; confirm loop-pr.py and
     loop-review.py still read proposals correctly (they must tolerate NULL session_uuid on
     historical rows); confirm the proposer acquires the ONE lock as an AgentKit slot, not a
     private mutex. Report.`,
    { label: 'ledger:verify', phase: 'Ledger', effort: 'medium' }),
)

phase('Surface')

// 4 agents (3 writers, 1 verifier). Why: renders what is already recorded — the operator
// cannot supervise a loop they cannot see (02-visualisation.md) — and Q6's build order is
// SURFACE FIRST: the loop editor where harnesses are visible, the toggle with it (default
// OFF, denylisted), and only after that may a later cycle add the 'harness' proposal kind.
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
     /questions surface, per Q15 (channels: Wing UI ONLY — no ntfy actions, no telegram, an
     approval channel is an authentication surface; default_on_expiry: ALWAYS refuse):
     Wing QuestionsPresenter + route + latte view over agent_questions (open queue, answered
     by/via, expired-into-refuse count — the number that says the loop outran the operator).
     Tier-gate with the existing $minAccessTier pattern (BasePresenter). Respect the four
     existing agent_questions gates — read them BEFORE writing; the answering path
     (reconcile-inbox.php) is not yours to touch.
     SHIP THE GATE: extend the presenter-gate contract test to cover QuestionsPresenter.`,
    { label: 'surface:questions', phase: 'Surface', effort: 'high' }),
  () => agent(
    `${RULES}
     Q6 — the LOOP EDITOR surface + the harness-enhancement toggle, default OFF:
     - a Wing presenter (/loop-editor or nested under the loop views) that renders every
       agent's HARNESS read-only: agent.yml, system.md, tool roster, grants, gateset — the
       files that ARE the gates on an agent. You cannot consent to what you cannot see; this
       surface exists so the operator can, before any switch is thrown.
     - Q6 SEAM (3): the editor also lists every proposal INTENT CLASS from ledger.py's
       enum, disabled ones (harness) marked as such beside the toggle — the place a harness
       proposal will one day render already exists.
     - the toggle harness_proposals_enabled: a KEAP DATATABLE ROW (operator answer
       2026-08-28: configuration belongs in KEAP DataTables with fixtures committed in the
       repo). Look FIRST for an existing operator-config table; at authoring time none of
       the 15 definitions in state/keap-tables/ is one (controls is the face icon grid), so
       expect to author a small config table definition there + a committed default-OFF
       fixture row, following the roadmap/controls house pattern. The editor renders the
       toggle from it. With it OFF nothing changes behaviour — that is what makes shipping
       it safe.
     - Q7, made precise by the KEAP home: the denylist entry names the toggle's PATHS —
       the table definition file under state/keap-tables/, its fixture, and the
       (table, row-slug) address the ledger will one day read — WRITTEN into the denylist
       floor where it is recorded (docs/idea/11-agentic-loop-contract.md's list or its
       successor). The loop may not propose enabling its own harness editing: a permission
       a system can grant itself is not a permission.
     - do NOT build the 'harness' proposal kind — that is a later cycle; this cycle cuts
       its seams (the Ledger phase adds the disabled intent).
     SHIP THE GATES: extend the presenter-gate contract test to the new presenter, and
     test_the_harness_toggle_defaults_off.py — reads the ARTIFACTS (the committed table
     definition + fixture, and the denylist entry), asserts the fixture default is OFF and
     that the toggle's table path appears on the denylist.`,
    { label: 'surface:loop-editor', phase: 'Surface', effort: 'high' }),
])
await agent(
  `${RULES}
   VERIFY Surface phase: run the new gates + suite; open the regenerated anatomy-graph.json
   and hand-check surveyor's node (charter attr present? tools edges = its manifest roster?
   authentik edge present?); confirm the questions view has NO ntfy/telegram wiring and the
   expiry default is refuse; confirm the toggle is a KEAP table row with a committed
   default-OFF fixture (not a Wing setting, not a ~/.nos flag), that its table path sits on
   the denylist, and that the editor lists the disabled harness intent; render the new views via the wing live-verify recipe (memory: port
   9000 + edge token headers) ONLY if a deployed Wing exists on this host, else latte-lint
   the templates. Report.`,
  { label: 'surface:verify', phase: 'Surface', effort: 'medium' })

phase('Ops harness')

// 2 agents. Why (Q3=a): the ops plane's go/no-go is a measurement, not a feeling — this
// phase builds the instrument, not the plane. Q4: the instrument is parameterised over a
// model-size RANGE, because the question is not "is 1B enough" but "where is the boundary
// between the ~1B chain tier and the ~3-7B tool-use tier".
await pipeline(
  () => agent(
    `${RULES}
     one_shot mode + the nos-ops measurement harness (Q3=a, Q4 two-tier):
     - agent.schema.yaml + Runner.php: mode: one_shot — bind, ONE call, validate the emitted
       chain against a schema, record. Branch at session open; no tool-use loop, no outcome
       loop. (~60 LOC; NOT a fork.)
     - tools/nos-ops-harness.py: given a task-family dir (labelled sample set: inputs +
       expected extractions), run EVERY armed local binding from state/llm-backends.yml —
       parameterised over the declared model-size range, ~1B through ~7B, not pinned at any
       size — in one_shot mode, score by exact label reproduction (code oracle — the model
       NEVER self-assesses), and write a per-model report artifact (json) keyed by model
       size, so the report answers WHERE the chain-tier/tool-use-tier boundary sits, not
       whether one size passes. The ops plane's tool surface stays closed until the 3-7B
       tier has a number — the harness says so in its own report header.
     - ship ONE example task family with >=20 labelled samples (synthetic invoices are fine;
       label them by hand in the fixture, not by a model).
     - NOTHING here creates tenant DBs (Q11) or embryo machinery (Q5).
     SHIP THE GATE: test_one_shot_mode_makes_one_call.py — stub client, assert exactly one
     send() and that a schema-invalid chain records failed, never satisfied.`,
    { label: 'ops:harness', phase: 'Ops harness', effort: 'high' }),
  () => agent(
    `${RULES}
     VERIFY Ops harness: run the gate + suite; run the harness against the fixture set with
     STUB bindings at two declared sizes (no real model call needed to prove the plumbing);
     confirm the score is computed by the harness code from labels, that the report is keyed
     by model size, and that no code path lets model output set its own score. Report — and
     state plainly that NO capability claim exists for either tier until the operator arms
     real local bindings and runs it.`,
    { label: 'ops:verify', phase: 'Ops harness', effort: 'medium' }),
)

phase('Review')

// MEASURED-CLAIM CHECK (07-first-bound-night.md): the final reader must state, for each of
// the two findings this run was designed against, whether it is CLOSED, OPEN or UNKNOWN —
// (1) can a bound run reach a scoped Bone endpoint as itself, (2) is a read-only run now a
// distinct recorded outcome. UNKNOWN is a permitted answer and the honest one if no bound
// run happened; what is forbidden is silence, which would read as closed.

// 1 agent, read-only. Why: a final reader that wrote nothing — the workflow's own success
// marker is written by a non-writer, per doctrine.
const review = await agent(
  `${RULES}
   READ-ONLY final review. You wrote nothing in this workflow. On the feat branch:
   - run the FULL gate suite (pytest tests/anatomy -q) and report the exact counts;
   - list every commit with the gate(s) it ships; flag any machinery commit without one;
   - grep for the forbidden: converge commands in any new code, prose-reading gates,
     satisfaction written by non-readers, surviving bypassPermissions, any reappearance of
     agent memory (agent_memory_stores, loadMemoryContext), any second agent-run lock, any
     embryo or tenant-DB machinery, and any surviving 'nos-bi' or 'tier' used for the plane
     split;
   - write ${RSI}/06-build-report.md (this ONE file write is permitted): what landed, what
     was skipped and under which questionnaire answer, the exact commands the OPERATOR must
     run next (converge, token mint, GitHub push) — commands printed, never run.`,
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
