export const meta = {
  "name": "iris-subagents-b",
  "description": "v0.18 track B, part 2: per-run limits and tool narrowing, child threads so the tree branches, a live pinned run tree with Iris's own status; journeys",
  "whenToUse": "After iris-subagents-a (merge its integration branch into the base first, or pass base=origin/feat/iris-subagents-a).",
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
      "the defaults"
    ],
    "security_lens": "",
    "slug": "iris-subagent-limits",
    "branch": "feat/iris-subagent-limits",
    "facts": "start_agent: files/anatomy/thalamus/thalamus/src/serve.rs:2353-2397 (card, then POST Wing /api/v1/agents/<name>/sessions with {prompt, parent:'thalamus:<session>'}, the thalamus bearer, x-nos-user-uid/groups; expects 202 + session_uuid); approve path serve.rs:1725-1734 pushes '[thalamus] started as session X; read_run draws it' (serve.rs:1800) and NO model turn follows. Wing: BaseApiPresenter.php:82-84 limits the thalamus bearer to POST sessions; AgentsPresenter.php:174 refuses a non-operator unless the agent's metadata.end_user is true (conductor and surveyor do not declare it); :178-189 shape-checks parent; Runner.php:291 stores parent_ref; Runner.php:397-406 is the ONLY startThread (primary); limits only in Runner: MAX_LLM_CALLS_PER_ITERATION=30 (:61), SESSION_WALL_CLOCK_S=3600 (:123, env :273), SESSION_TOKEN_CEILING=250000 (:124, :1305). read_run: serve.rs:3697-3710 runs tools/agent-status.py --run (children by parent_ref, agent-status.py:168-176); dendrogram serve.rs:4683-4784 (Iris node hard-coded Ok :4698-4699, children tokens None :4700-4702, events on the primary thread :4741-4742), rendered with pin: None (serve.rs:2649); WidgetSpec has no Run variant (thalamus/contract/src/wire.rs:209-215); AgentSessionsPresenter.php:27 has only GET; no cancel route. iris_startable_agents [conductor, surveyor] default.config.yml:635. Tests: thalamus tests/serve.rs:3169-3205, :6796-6912; e2e tests/e2e/journeys/test_iris_draws_an_agent_run.py is read-only and CI ignores tests/e2e (ci.yml:217).",
    "files_owned": [
      "files/anatomy/wing/app/Presenters/Api/AgentsPresenter.php (POST body: limits{max_calls,wall_clock_s,token_ceiling}, tools[] narrowing)",
      "files/anatomy/wing/app/AgentKit/Runner.php (per-session limits override the constants, never exceed them; tool narrowing = intersection with the agent's own set)",
      "files/anatomy/wing/app/AgentKit/Tools/ToolRegistry.php (intersection)",
      "files/anatomy/wing/db/schema-extensions.sql + bin/init-db.php add-missing-columns (limits_json on agent_sessions) + files/anatomy/contracts/wing.db-schema.sql regen",
      "files/anatomy/contracts/wing.openapi.yml + test_face_wing_contract (GATE CHANGE)",
      "files/anatomy/thalamus/thalamus/src/serve.rs (start_agent args + the card shows them)",
      "files/anatomy/thalamus/thalamus/tests/serve.rs",
      "state/fixtures/oneshot/thalamus-tools.json (GATE CHANGE regen)"
    ],
    "gates": [
      "Wing PHP gate: a POST with limits stores them; a limit above the Runner's constant is clamped and the response says so; a tool not in the agent's set is refused by name",
      "Runner unit: the loop stops at max_calls of the session, not the constant",
      "rig test: the card text names the agent, the prompt head and the limits; the ledger records the limits, not the prompt"
    ],
    "steps": "(1) Schema + contract first. (2) Runner reads the session's limits_json. (3) Thalamus: optional limits on start_agent with sane defaults (max_calls 20, wall 900 s, tokens 100k) shown on the card."
  },
  {
    "depends_on": [],
    "expected_red": [],
    "operator_decisions": [],
    "security_lens": "",
    "slug": "iris-subagent-child-threads",
    "branch": "feat/iris-subagent-child-threads",
    "facts": "start_agent: files/anatomy/thalamus/thalamus/src/serve.rs:2353-2397 (card, then POST Wing /api/v1/agents/<name>/sessions with {prompt, parent:'thalamus:<session>'}, the thalamus bearer, x-nos-user-uid/groups; expects 202 + session_uuid); approve path serve.rs:1725-1734 pushes '[thalamus] started as session X; read_run draws it' (serve.rs:1800) and NO model turn follows. Wing: BaseApiPresenter.php:82-84 limits the thalamus bearer to POST sessions; AgentsPresenter.php:174 refuses a non-operator unless the agent's metadata.end_user is true (conductor and surveyor do not declare it); :178-189 shape-checks parent; Runner.php:291 stores parent_ref; Runner.php:397-406 is the ONLY startThread (primary); limits only in Runner: MAX_LLM_CALLS_PER_ITERATION=30 (:61), SESSION_WALL_CLOCK_S=3600 (:123, env :273), SESSION_TOKEN_CEILING=250000 (:124, :1305). read_run: serve.rs:3697-3710 runs tools/agent-status.py --run (children by parent_ref, agent-status.py:168-176); dendrogram serve.rs:4683-4784 (Iris node hard-coded Ok :4698-4699, children tokens None :4700-4702, events on the primary thread :4741-4742), rendered with pin: None (serve.rs:2649); WidgetSpec has no Run variant (thalamus/contract/src/wire.rs:209-215); AgentSessionsPresenter.php:27 has only GET; no cancel route. iris_startable_agents [conductor, surveyor] default.config.yml:635. Tests: thalamus tests/serve.rs:3169-3205, :6796-6912; e2e tests/e2e/journeys/test_iris_draws_an_agent_run.py is read-only and CI ignores tests/e2e (ci.yml:217). agent_threads already has parent_thread_uuid and role primary|child (wing/db/schema-extensions.sql ~557+); AgentSessionRepository.php:361,404 read children; nothing writes a child.",
    "files_owned": [
      "files/anatomy/wing/app/AgentKit/Runner.php (startThread child where the runner forks work: a tool call batch, a grader iteration — pick the honest unit and say why)",
      "files/anatomy/wing/app/Model/AgentSessionRepository.php",
      "tools/agent-status.py (--run joins threads with parent_thread_uuid; events keep hanging off the thread that ran them if the event carries a thread uuid — add thread_uuid to the events the Runner writes)",
      "files/anatomy/thalamus/thalamus/src/serve.rs (dendrogram(): thread nodes under their parent thread)",
      "tests/anatomy/test_agent_status_reads_one_run.py",
      "files/anatomy/thalamus/thalamus/tests/serve.rs",
      "tests/wing-api or tests/anatomy Wing PHP gate for the Runner"
    ],
    "gates": [
      "Wing gate: one run with two forked units writes two child threads under the primary, each event names its thread",
      "reader gate: --run returns threads nested by parent_thread_uuid; red today: all rows role primary",
      "rig: the dendrogram draws thread -> tool nodes under the right thread"
    ],
    "steps": "(1) Decide the unit (document it in Runner.php's header). (2) Write child threads + thread_uuid on events. (3) Reader + tree."
  },
  {
    "depends_on": [],
    "expected_red": [],
    "operator_decisions": [
      "run the live journey once after converge and paste the result into the row"
    ],
    "security_lens": "",
    "slug": "iris-run-widget-and-journeys",
    "branch": "feat/iris-run-widget-and-journeys",
    "facts": "start_agent: files/anatomy/thalamus/thalamus/src/serve.rs:2353-2397 (card, then POST Wing /api/v1/agents/<name>/sessions with {prompt, parent:'thalamus:<session>'}, the thalamus bearer, x-nos-user-uid/groups; expects 202 + session_uuid); approve path serve.rs:1725-1734 pushes '[thalamus] started as session X; read_run draws it' (serve.rs:1800) and NO model turn follows. Wing: BaseApiPresenter.php:82-84 limits the thalamus bearer to POST sessions; AgentsPresenter.php:174 refuses a non-operator unless the agent's metadata.end_user is true (conductor and surveyor do not declare it); :178-189 shape-checks parent; Runner.php:291 stores parent_ref; Runner.php:397-406 is the ONLY startThread (primary); limits only in Runner: MAX_LLM_CALLS_PER_ITERATION=30 (:61), SESSION_WALL_CLOCK_S=3600 (:123, env :273), SESSION_TOKEN_CEILING=250000 (:124, :1305). read_run: serve.rs:3697-3710 runs tools/agent-status.py --run (children by parent_ref, agent-status.py:168-176); dendrogram serve.rs:4683-4784 (Iris node hard-coded Ok :4698-4699, children tokens None :4700-4702, events on the primary thread :4741-4742), rendered with pin: None (serve.rs:2649); WidgetSpec has no Run variant (thalamus/contract/src/wire.rs:209-215); AgentSessionsPresenter.php:27 has only GET; no cancel route. iris_startable_agents [conductor, surveyor] default.config.yml:635. Tests: thalamus tests/serve.rs:3169-3205, :6796-6912; e2e tests/e2e/journeys/test_iris_draws_an_agent_run.py is read-only and CI ignores tests/e2e (ci.yml:217). WidgetSpec variants Rows/Chart/Form/Kpi/Knowledge in contract wire.rs:209-215; run_widget in serve.rs re-runs a spec as the person; face Widget/CanvasItem pin path; thalamus-shell.yml contract_version 11 with fixture; face/src/lib/iris/fixture.test.ts pins PROPS/OPTIONAL.",
    "files_owned": [
      "files/anatomy/thalamus/contract/src/wire.rs (WidgetSpec::Run{session})",
      "files/anatomy/contracts/thalamus-shell.yml + fixture (contract_version 12) + files/anatomy/face/src/lib/iris/fixture.test.ts (GATE CHANGE)",
      "files/anatomy/thalamus/thalamus/src/serve.rs (read_run renders with pin Some(Run); run_widget Run arm; Iris node status from the ledger: running if this session has an open turn, else ok)",
      "files/anatomy/face/src/lib/iris/Dendrogram.svelte (refresh on widget re-run; node click -> read_run focused on the child session)",
      "files/anatomy/thalamus/thalamus/tests/serve.rs",
      "tests/e2e/journeys/test_iris_starts_a_subagent.py (live, skipped without IRIS_E2E=1 and explicit WING_API_URL/THALAMUS_SOCK; never defaults to live)",
      "files/anatomy/thalamus/thalamus/tests/ (one offline rig journey: approve -> fake Wing ends -> report turn -> tree has parent+child)"
    ],
    "gates": [
      "contract parity gates (test_thalamus_shell_contract, test_pupil_renders_the_fixture, face fixture.test.ts) green at v12; red before: unknown widget spec 'run'",
      "rig journey green; the live journey file collects and is skipped by default (proved by running pytest --collect-only)"
    ],
    "steps": "(1) Contract bump with fixture sample. (2) Pin + re-run. (3) Iris node status. (4) Journeys."
  }
]
const INTEGRATION_BRANCH = "feat/iris-subagents-b"
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

