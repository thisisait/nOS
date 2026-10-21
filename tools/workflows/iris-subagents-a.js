export const meta = {
  "name": "iris-subagents-a",
  "description": "v0.18 track B, part 1: a sub-agent Iris started reports back into the conversation; tier-2 people may start the allow-listed agents; a running child can be stopped",
  "whenToUse": "After rel-018-hygiene-a lands or in parallel. iris-subagents-b follows it (limits, child threads, live tree).",
  "phases": [
    {
      "title": "Build",
      "detail": "each row in its own worktree, gate first"
    },
    {
      "title": "Review",
      "detail": "one skeptic per row, one re-review of the fixed"
    },
    {
      "title": "Fix",
      "detail": "at most two fix passes in all"
    },
    {
      "title": "Integrate",
      "detail": "merge the landed rows, one full run, report"
    }
  ]
}

// Rows are the spec: slug = the roadmap row in nos-seed; facts are the 2026-10-21 audits (verify, never trust).
const ROWS = [
  {
    "depends_on": [],
    "expected_red": [],
    "operator_decisions": [
      "the poll bound (default: the Runner's wall clock)"
    ],
    "security_lens": "",
    "slug": "iris-subagent-reports-back",
    "branch": "feat/iris-subagent-reports-back",
    "facts": "start_agent: files/anatomy/thalamus/thalamus/src/serve.rs:2353-2397 (card, then POST Wing /api/v1/agents/<name>/sessions with {prompt, parent:'thalamus:<session>'}, the thalamus bearer, x-nos-user-uid/groups; expects 202 + session_uuid); approve path serve.rs:1725-1734 pushes '[thalamus] started as session X; read_run draws it' (serve.rs:1800) and NO model turn follows. Wing: BaseApiPresenter.php:82-84 limits the thalamus bearer to POST sessions; AgentsPresenter.php:174 refuses a non-operator unless the agent's metadata.end_user is true (conductor and surveyor do not declare it); :178-189 shape-checks parent; Runner.php:291 stores parent_ref; Runner.php:397-406 is the ONLY startThread (primary); limits only in Runner: MAX_LLM_CALLS_PER_ITERATION=30 (:61), SESSION_WALL_CLOCK_S=3600 (:123, env :273), SESSION_TOKEN_CEILING=250000 (:124, :1305). read_run: serve.rs:3697-3710 runs tools/agent-status.py --run (children by parent_ref, agent-status.py:168-176); dendrogram serve.rs:4683-4784 (Iris node hard-coded Ok :4698-4699, children tokens None :4700-4702, events on the primary thread :4741-4742), rendered with pin: None (serve.rs:2649); WidgetSpec has no Run variant (thalamus/contract/src/wire.rs:209-215); AgentSessionsPresenter.php:27 has only GET; no cancel route. iris_startable_agents [conductor, surveyor] default.config.yml:635. Tests: thalamus tests/serve.rs:3169-3205, :6796-6912; e2e tests/e2e/journeys/test_iris_draws_an_agent_run.py is read-only and CI ignores tests/e2e (ci.yml:217). Wing emits events on session end (grep Runner.php for 'session_end' / agent_session events; the conductor posts a conductor_report event); the thalamus relay (relay.rs) and serve's ToShell loop are where a wake-up would land.",
    "files_owned": [
      "files/anatomy/thalamus/thalamus/src/serve.rs (new functions + the decide() branch for start_agent only)",
      "files/anatomy/thalamus/thalamus/src/relay.rs (if a wake-up channel is needed)",
      "files/anatomy/thalamus/thalamus/tests/serve.rs",
      "files/anatomy/wing/app/AgentKit/Runner.php (only if Wing must POST a completion hook)",
      "files/anatomy/wing/app/Presenters/Api/AgentSessionsPresenter.php (a result field on GET, if missing)",
      "files/anatomy/contracts/wing.openapi.yml + tests/anatomy/test_face_wing_contract.py (GATE CHANGE if the wire grows)"
    ],
    "gates": [
      "rig test: after approve, when the fake Wing reports the session ended with a report event, the person sees ONE Iris turn whose text carries the report's head (capped) and the session uuid; red today: nothing follows the approve",
      "rig test: a session that never ends within the bound is said so (no hang); the model hears 'still running'",
      "full cargo test of thalamus + contract; Wing PHP lane if Runner.php changed"
    ],
    "steps": "(1) Minimal honest design: the thalamus remembers the sessions it started per Iris session; a bounded poll (agent-sessions/<uuid> every N s, as the person, through the thalamus bearer's GET if allowed — else add that one GET to the bearer's allowed actions in BaseApiPresenter with a test) until ended or the bound; then the thalamus pushes a '[thalamus] agent <name> ended: <outcome>; report: <head>' user message AND runs one model turn so Iris answers in the chat. (2) The deliverable = the newest report/result event body of that session (cap 4 KB), never free text from the ledger beyond that. (3) The ledger records ids and lengths, not the report text."
  },
  {
    "depends_on": [],
    "expected_red": [],
    "operator_decisions": [
      "whether tier-2 people may read_run their own started runs (recommended yes)"
    ],
    "security_lens": "",
    "slug": "iris-subagent-for-tier-two",
    "branch": "feat/iris-subagent-for-tier-two",
    "facts": "start_agent: files/anatomy/thalamus/thalamus/src/serve.rs:2353-2397 (card, then POST Wing /api/v1/agents/<name>/sessions with {prompt, parent:'thalamus:<session>'}, the thalamus bearer, x-nos-user-uid/groups; expects 202 + session_uuid); approve path serve.rs:1725-1734 pushes '[thalamus] started as session X; read_run draws it' (serve.rs:1800) and NO model turn follows. Wing: BaseApiPresenter.php:82-84 limits the thalamus bearer to POST sessions; AgentsPresenter.php:174 refuses a non-operator unless the agent's metadata.end_user is true (conductor and surveyor do not declare it); :178-189 shape-checks parent; Runner.php:291 stores parent_ref; Runner.php:397-406 is the ONLY startThread (primary); limits only in Runner: MAX_LLM_CALLS_PER_ITERATION=30 (:61), SESSION_WALL_CLOCK_S=3600 (:123, env :273), SESSION_TOKEN_CEILING=250000 (:124, :1305). read_run: serve.rs:3697-3710 runs tools/agent-status.py --run (children by parent_ref, agent-status.py:168-176); dendrogram serve.rs:4683-4784 (Iris node hard-coded Ok :4698-4699, children tokens None :4700-4702, events on the primary thread :4741-4742), rendered with pin: None (serve.rs:2649); WidgetSpec has no Run variant (thalamus/contract/src/wire.rs:209-215); AgentSessionsPresenter.php:27 has only GET; no cancel route. iris_startable_agents [conductor, surveyor] default.config.yml:635. Tests: thalamus tests/serve.rs:3169-3205, :6796-6912; e2e tests/e2e/journeys/test_iris_draws_an_agent_run.py is read-only and CI ignores tests/e2e (ci.yml:217).",
    "files_owned": [
      "files/anatomy/agents/conductor/agent.yml",
      "files/anatomy/agents/surveyor/agent.yml",
      "files/anatomy/wing/app/Presenters/Api/AgentsPresenter.php (only the end_user check's test, if its message changes)",
      "tests/anatomy/test_a_child_session_names_its_parent.py or a new tests/anatomy/test_iris_startable_agents_serve_end_users.py",
      "files/anatomy/thalamus/thalamus/src/serve.rs (start_agent's tier check only)",
      "files/anatomy/thalamus/thalamus/tests/serve.rs"
    ],
    "gates": [
      "new gate: every agent in iris_startable_agents declares metadata.end_user: true and holds no keap.write (red today: neither declares it)",
      "Wing PHP gate: a tier-2 person's POST through the thalamus bearer gets 202 for conductor and 403 for an agent without end_user",
      "rig test: a manager's start_agent shows the card; nos-users is refused with 'tier 2'"
    ],
    "steps": "(1) end_user: true on conductor and surveyor with the reason in a comment (read-only agents; surveyor's mcp-wing-write is its report event only). (2) start_agent allowed for tier 2 (NOS_TIER2_GROUPS already reaches the thalamus) — read_run stays tier 1 unless the row says otherwise: a tier-2 person reads only runs they started (owner scoping in Wing already narrows GET agent-sessions; mirror it in read_run by actor). (3) The gate pins the allow-list's properties, so adding librarian later fails loudly."
  },
  {
    "depends_on": [],
    "expected_red": [],
    "operator_decisions": [
      "cancel as a plain tool call vs behind an approval card (default: plain; the person asked for it in words)"
    ],
    "security_lens": "",
    "slug": "iris-subagent-stop",
    "branch": "feat/iris-subagent-stop",
    "facts": "start_agent: files/anatomy/thalamus/thalamus/src/serve.rs:2353-2397 (card, then POST Wing /api/v1/agents/<name>/sessions with {prompt, parent:'thalamus:<session>'}, the thalamus bearer, x-nos-user-uid/groups; expects 202 + session_uuid); approve path serve.rs:1725-1734 pushes '[thalamus] started as session X; read_run draws it' (serve.rs:1800) and NO model turn follows. Wing: BaseApiPresenter.php:82-84 limits the thalamus bearer to POST sessions; AgentsPresenter.php:174 refuses a non-operator unless the agent's metadata.end_user is true (conductor and surveyor do not declare it); :178-189 shape-checks parent; Runner.php:291 stores parent_ref; Runner.php:397-406 is the ONLY startThread (primary); limits only in Runner: MAX_LLM_CALLS_PER_ITERATION=30 (:61), SESSION_WALL_CLOCK_S=3600 (:123, env :273), SESSION_TOKEN_CEILING=250000 (:124, :1305). read_run: serve.rs:3697-3710 runs tools/agent-status.py --run (children by parent_ref, agent-status.py:168-176); dendrogram serve.rs:4683-4784 (Iris node hard-coded Ok :4698-4699, children tokens None :4700-4702, events on the primary thread :4741-4742), rendered with pin: None (serve.rs:2649); WidgetSpec has no Run variant (thalamus/contract/src/wire.rs:209-215); AgentSessionsPresenter.php:27 has only GET; no cancel route. iris_startable_agents [conductor, surveyor] default.config.yml:635. Tests: thalamus tests/serve.rs:3169-3205, :6796-6912; e2e tests/e2e/journeys/test_iris_draws_an_agent_run.py is read-only and CI ignores tests/e2e (ci.yml:217). Wing's emergency halt (AdminPresenter halt/resume) pauses every Pulse job and is operator-only; it is NOT a per-session cancel.",
    "files_owned": [
      "files/anatomy/wing/app/Presenters/Api/AgentSessionsPresenter.php (new POST cancel action)",
      "files/anatomy/wing/app/Core/RouterFactory.php (the route)",
      "files/anatomy/wing/app/Presenters/Api/BaseApiPresenter.php ($thalamusActions += cancel on sessions the bearer started)",
      "files/anatomy/wing/app/AgentKit/Runner.php (a cooperative stop flag the loop checks between calls)",
      "files/anatomy/contracts/wing.openapi.yml + test_face_wing_contract (GATE CHANGE)",
      "files/anatomy/thalamus/thalamus/src/serve.rs (stop_agent tool; ASKING? no — a stop is not a write that needs a card: say why in the code comment, or make it a card if the row's reviewer disagrees)",
      "files/anatomy/thalamus/thalamus/tests/serve.rs",
      "state/fixtures/oneshot/thalamus-tools.json (GATE CHANGE regen)"
    ],
    "gates": [
      "Wing PHP gate: POST agent-sessions/<uuid>/cancel by the thalamus bearer for a session it started -> 202 and the session row reads status cancelled with stop_reason 'cancelled by <actor>'; another person's session -> 404 (never 403: absent and not-yours answer the same, as parent did)",
      "rig test: stop_agent(uuid) on a session Iris started POSTs cancel; on a uuid she did not start it is refused before any call",
      "Runner unit: the loop exits within one iteration after the flag"
    ],
    "steps": "(1) Runner: between LLM calls read a cancel flag (a column on agent_sessions set by the route; the Runner already re-reads the row for limits — find where). (2) Route + bearer allow. (3) Tool stop_agent, listed in the tool fixture; the model hears the outcome."
  }
]
const INTEGRATION_BRANCH = "feat/iris-subagents-a"
const INTEGRATION_EXTRA = ""

// ---- harness (shared by the v0.18-beta workflows; edit all or none) ------------------------------------
const A = typeof args !== 'undefined' && args ? args : {}
const BASE = A.base || 'origin/dev'
const SEED = A.seed || '/Users/pazny/projects/nos-seed'
const MAX_FIXES = 2 // builds + reviews + fixes + re-review + integrate <= 10 agents

const RULES = `House rules (nOS; the repo's CLAUDE.md applies):
- Work ONLY in your own git worktree. Branch as your task names it, cut from ${BASE}.
- Push with "tools/nos-push --skip-sync origin HEAD:<branch>" (no Gitea mirror write), then confirm with
  "git ls-remote origin refs/heads/<branch>". NEVER push to dev or master; never merge into dev.
- Gate first: write the gate, run it to a log file, read the exit code (never through a pipe), see it RED for the
  RIGHT reason (the failing assertion names the missing behaviour; an ImportError/SyntaxError/missing fixture is
  not red), commit "test: ... (red)"; then the fix, green, commit. Changing an EXISTING test's expectation is its
  own commit "test: GATE CHANGE ..." with the why.
- Commits: Conventional Commits, subject <= 50 chars, body <= 6 bullets, NO Co-Authored-By line.
- Never read ~/.nos/secrets.yml, credentials.yml or any .env; never print a secret.
- Never touch the live estate: no ansible-playbook, no nos (except read-only "nos dtt status"), no
  launchctl/systemctl, no useradd/groupadd/chown, no writes to ~/wing, ~/thalamus, ~/.nos, ~/stacks, /var/lib,
  /etc. Never run anything under tests/e2e/journeys or tests/e2e/estate (they default to the LIVE Wing
  127.0.0.1:9000 and the live wing.db) and never import tests/e2e/lib/estate_secrets.py. Any test you write that
  talks HTTP or SQLite takes an explicit scratch URL/path with NO default pointing at a live one. Read-only live
  reads through the repo's readers (tools/*-status.py) are allowed and must be reported as such.
- Run only the lanes you touch plus the full "cargo test" of every crate you touch
  (CARGO_TARGET_DIR=/Users/pazny/.cargo-target-nos). Gates stay Python; never port a gate.
- A new node in the anatomy graph gets an apex ruling entry (files/anatomy/apex/ruling.yml, "withheld" unless the
  row says otherwise) in its OWN clearly headed block. Do NOT commit regenerated artifacts (anatomy-graph,
  body-plan, IMPRINT, glossary, face layout pin): the integrator regenerates them once. Never run tools/apex-sign.py.
- The row that CREATES a thing owns every gate allow-list that thing needs (a new ssot article: its _BORN_IN_SSOT
  line in tests/anatomy/test_ssot_index.py; a new reader: its tools/README §Readers line; a new lockfile: its
  dependabot entry) as a "test: GATE CHANGE ..." commit of that row, never left for the operator.
- Expected-red is explicit per row: nothing else may be red on your branch; a reviewer refutes any other red lane.
- Rows are the spec; the roadmap files under ${SEED} are their source. Config keys, sudo, converges, closures of
  roadmap rows and anything destructive are the operator's: leave them in operator_questions.`

const BUILD_SCHEMA = { type: 'object', properties: {
  branch: { type: 'string' }, pushed: { type: 'boolean' }, worktree: { type: 'string' },
  commits: { type: 'array', items: { type: 'string' } }, red_shown: { type: 'array', items: { type: 'string' } },
  green: { type: 'array', items: { type: 'string' } }, not_verified: { type: 'array', items: { type: 'string' } },
  apex_resign_needed: { type: 'boolean' }, operator_questions: { type: 'array', items: { type: 'string' } } },
  required: ['branch', 'pushed', 'worktree', 'commits', 'red_shown', 'green', 'not_verified', 'apex_resign_needed', 'operator_questions'] }
const VERDICT_PROPS = { refuted: { type: 'boolean' }, defects: { type: 'array', items: { type: 'string' } },
  checked: { type: 'array', items: { type: 'string' } } }
const VERDICT_SCHEMA = { type: 'object', properties: VERDICT_PROPS, required: ['refuted', 'defects', 'checked'] }
const RECHECK_SCHEMA = { type: 'object', properties: { rows: { type: 'array', items: { type: 'object',
  properties: { slug: { type: 'string' }, ...VERDICT_PROPS }, required: ['slug', 'refuted', 'defects', 'checked'] } } },
  required: ['rows'] }
const honest = (v, who) => !v ? { refuted: true, defects: [`${who} returned nothing`], checked: [] }
  : (!v.checked || !v.checked.length) ? { ...v, refuted: true, defects: [...(v.defects || []), `${who} listed no command it ran`] } : v
const METHOD = `Method (in your own worktree): "git fetch origin", "git checkout --detach origin/<branch>",
"git diff ${BASE}...origin/<branch>"; for red-before, "git checkout --detach <the (red) commit>" and run that gate.
Run every gate to a log file and read the exit code, never through a pipe. List every command with its exit code in
"checked". refuted=true if any gate is not green, was never red for the RIGHT reason, a house rule is broken, a file
outside the row's ownership changed, or any new test/tool has a default URL/path/token pointing at the live Wing,
wing.db, ~/.nos or the Docker socket. Default to refuted=true when uncertain.`

const bySlug = Object.fromEntries(ROWS.map(r => [r.slug, r]))
const results = {}
for (const [s, b] of Object.entries(A.landed || {})) if (bySlug[s]) results[s] = { built: { branch: b, pushed: true,
  worktree: '(earlier run)', commits: [], red_shown: [], green: [], not_verified: ['landed by an earlier run'],
  apex_resign_needed: false, operator_questions: [] }, verdicts: [], defects: [], fixed: null, landed: true, still_refuted: false }
let fixes = 0

const build = row => agent(`${RULES}

Build roadmap row ${row.slug} on branch ${row.branch} (cut from ${BASE}${row.depends_on.length ?
  `, then merge ${row.depends_on.map(d => `origin/${bySlug[d].branch}`).join(' and ')} into it first` : ''}).
Measured facts (2026-10-21 audits; verify before relying on them): ${row.facts}
You own these files and no others: ${row.files_owned.join(', ')}.
Gates (each shown red first): ${row.gates.join('; ')}.
Expected red until the integrator regenerates (and nothing else): ${row.expected_red.join('; ') || 'none'}.
Steps: ${row.steps}
Leave open for the operator: ${row.operator_decisions.join('; ') || 'nothing named'}.
Return what you committed, what you saw red and green (exact commands + exit codes), your worktree path, what you did not verify.`,
  { label: `build:${row.slug}`, phase: 'Build', schema: BUILD_SCHEMA, isolation: 'worktree', model: 'opus' })

const review = (row, built, lens) => agent(`You are a skeptic reviewing branch origin/${built.branch} (roadmap row ${row.slug}) through the ${lens} lens.
Try to REFUTE that it is done. Its gates: ${row.gates.join('; ')}. It may change only: ${row.files_owned.join(', ')}.
Red is allowed ONLY on: ${row.expected_red.join('; ') || 'nothing'}; any other red lane among the row's lanes refutes it.
${METHOD}
${row.security_lens && lens === 'security' ? `Security lens: ${row.security_lens}` : ''}
Builder said: ${JSON.stringify(built)}`,
  { label: `review:${row.slug}:${lens}`, phase: 'Review', schema: VERDICT_SCHEMA, isolation: 'worktree', model: 'opus' })

async function runRow(row) {
  const built = await build(row)
  if (!built) return (results[row.slug] = { built: null, landed: false, why: 'the builder returned nothing' })
  const lenses = row.security_lens ? ['correctness', 'security'] : ['correctness']
  const raw = await parallel(lenses.map(l => () => review(row, built, l)))
  const verdicts = raw.map((v, i) => honest(v, `reviewer ${lenses[i]}`))
  const defects = verdicts.filter(v => v.refuted).flatMap(v => v.defects)
  let fixed = null
  if (defects.length && fixes < MAX_FIXES) {
    fixes++
    log(`${row.slug}: refuted, fix pass ${fixes}/${MAX_FIXES} (${defects.length} defects)`)
    fixed = await agent(`${RULES}

Fix branch ${built.branch} (roadmap row ${row.slug}); a reviewer refuted it:
${defects.map(d => `- ${d}`).join('\n')}
In your own worktree: "git fetch origin && git checkout --detach origin/${built.branch}", fix each defect with its own
commit (gate first where a gate is missing), push with "tools/nos-push --skip-sync origin HEAD:${built.branch}" and
confirm with git ls-remote. Files you may touch: ${row.files_owned.join(', ')}, plus a gate allow-list the row's new
thing needs as its own GATE CHANGE commit.`,
      { label: `fix:${row.slug}`, phase: 'Fix', schema: BUILD_SCHEMA, isolation: 'worktree', model: 'opus' })
  } else if (defects.length) log(`${row.slug}: refuted, no fix budget left (${MAX_FIXES} used)`)
  results[row.slug] = { built, verdicts, defects, fixed, landed: !defects.length && built.pushed, still_refuted: defects.length > 0 }
  return results[row.slug]
}

async function recheckFixed(tag) {
  const rows = Object.entries(results).filter(([, r]) => r.fixed && r.still_refuted && !r.rechecked)
  if (!rows.length) return
  phase('Review')
  const v = await agent(`You are a skeptic re-reviewing fixed branches:
${rows.map(([s, r]) => `- ${s}: origin/${r.fixed.branch}; defects claimed fixed: ${r.defects.join('; ')}; gates: ${bySlug[s].gates.join('; ')}; red allowed only on: ${bySlug[s].expected_red.join('; ') || 'nothing'}`).join('\n')}
${METHOD}
Return one verdict per slug.`, { label: `rereview${tag}`, phase: 'Review', schema: RECHECK_SCHEMA, isolation: 'worktree', model: 'opus' })
  for (const [s, r] of rows) {
    const h = honest(v && v.rows.find(x => x.slug === s), `re-reviewer of ${s}`)
    r.rechecked = h; r.still_refuted = h.refuted; r.landed = r.fixed.pushed && !h.refuted
  }
}

phase('Build')
const pending = new Set(ROWS.map(r => r.slug))
while (pending.size) {
  for (const s of [...pending]) if (results[s] && results[s].landed) pending.delete(s)
  if (!pending.size) break
  const ready = [...pending].map(s => bySlug[s]).filter(r => r.depends_on.every(d => results[d] && results[d].landed))
  if (!ready.length) {
    const waiting = Object.values(results).some(r => r.fixed && r.still_refuted && !r.rechecked)
    if (waiting) { await recheckFixed(''); phase('Build'); continue }
    log(`not built, a dependency did not land: ${[...pending].join(', ')}`); break
  }
  ready.forEach(r => pending.delete(r.slug))
  await parallel(ready.map(r => () => runRow(r)))
}
await recheckFixed('-late')

phase('Integrate')
const landed = ROWS.filter(r => results[r.slug] && results[r.slug].landed).map(r => (results[r.slug].fixed || results[r.slug].built).branch)
const integration = landed.length ? await agent(`${RULES}

Integrate ${landed.map(b => `origin/${b}`).join(', ')} into a new branch ${INTEGRATION_BRANCH} cut from ${BASE}, in your own
worktree (merge the origin/ refs, never local branch names: other worktrees hold them). Resolve conflicts keeping both
sides' intent; a ruling.yml conflict keeps every entry. Regenerate generated artifacts with their writers, once
(tools/anatomy-graph-gen.py --refreeze, tools/body-plan-gen.py, tools/imprint-gen.py, tools/genome-codegen.py if the
lexicon changed) and commit them. Your ONE full run, each to its own log file in the background with a long timeout,
reading the summary line and the exit code: "python3 -m pytest tests/anatomy -q -p no:cacheprovider", the full
"cargo test --locked" of every crate touched, the face vitest lane if face changed. Push with
"tools/nos-push --skip-sync origin HEAD:${INTEGRATION_BRANCH}". Report every failure with its reason; the apex signature
failing is expected (the operator signs): set apex_resign_needed. Put the output of "git worktree list" in
operator_questions' last entry. ${INTEGRATION_EXTRA || ''}`,
  { label: 'integrate', phase: 'Integrate', schema: BUILD_SCHEMA, isolation: 'worktree', model: 'opus' }) : null

return {
  rows: Object.fromEntries(ROWS.map(r => { const x = results[r.slug]; if (!x) return [r.slug, { built: false, why: 'a dependency did not land' }]
    const b = x.fixed || x.built; return [r.slug, b ? { branch: b.branch, worktree: b.worktree, pushed: b.pushed, landed: x.landed,
    fixed: !!x.fixed, still_refuted: !!x.still_refuted, commits: b.commits, red_shown: b.red_shown,
    review: (x.verdicts || []).map(v => ({ refuted: v.refuted, defects: v.defects, checked: v.checked })), rereview: x.rechecked || null,
    not_verified: b.not_verified, operator_questions: b.operator_questions } : { built: false, why: x.why }] })),
  integration,
  apex_resign_needed: !!(integration && integration.apex_resign_needed) || Object.values(results).some(r => r && (r.fixed || r.built) && (r.fixed || r.built).apex_resign_needed),
  operator_merge: integration && integration.pushed ? `from a checkout that does not hold the branch: git fetch origin && git merge --ff-only origin/${INTEGRATION_BRANCH}` : null,
}

