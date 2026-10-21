export const meta = {
  "name": "iris-loops",
  "description": "v0.18 track C: loops are data with one validator the scheduler shares; Iris reads loop runs and proposes a loop through that validator",
  "whenToUse": "After the operator turned install_loops on and one night of Pulse has run (so read_loop_runs has data to show live). Independent of the Iris sub-agent workflows.",
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
    "operator_decisions": [],
    "security_lens": "",
    "slug": "loop-validator-cli",
    "branch": "feat/loop-validator-cli",
    "facts": "Loops as data: files/anatomy/loops/<id>.loop.yml (4: news-scout, repo-check, pipeline-exercise, vision-bench); validator tools/loop-graph-gen.py::_validate_manifest (:107-140, private; _STEP_RUNNERS :95, _SLUG :96; _load_manifests :143-151 adds id uniqueness) with only a whole-graph --check CLI; scheduler files/anatomy/scripts/discover-pulse-catalog.py:224-251 globs the manifests and makes 'loop:<id>' Pulse jobs WITHOUT calling the validator (gate tests/anatomy/test_loop_generates_its_pulse_job.py). SERE = code: bone/ledger.py (INTENT_CLASSES :105, role writes :136, schema :254-394 + _ADDED_COLUMNS :401-414), plugin loop-base (propose 01:30 loop-propose.py --invoke, drive 06:10 loop-pr.py --open-mr --rejudge, review 06:50 loop-review.py --merge), judge sets state/judge-sets.yml, budget.py ALLOWED_ROOTS :78-86 excludes files/anatomy/loops. Readers: tools/loop-status.py (--json, --unresolved, --gap, --awaiting; per weakness source; no --loop/--since; ignores pulse_runs); tools/red-status.py reads pulse_runs. Live 2026-10-21 on the operator host: install_loops was false (now switched on by the operator — verify with the readers, never by hand); ledger 32 baseline 'live' verdicts, 0 proposals. Wing LoopEditorPresenter.php:9-31 is a read-only harness viewer. Thalamus patterns: read_run serve.rs:3697-3710 via reader(); propose_app serve.rs:4188-4224 + app_parser :4325 + write_draft :4356; ASKING :554; renderer kinds in contracts/thalamus-shell.yml v11 (timeline :217, chart :208, table :205, graph :224); kpi is KEAP-only.",
    "files_owned": [
      "tools/loop-graph-gen.py (public validate_manifest(path) + CLI --validate <file>: exit 0, or 1 with every reason on stderr)",
      "files/anatomy/scripts/discover-pulse-catalog.py (calls the same function; a refused manifest becomes no job and is said)",
      "tests/anatomy/test_loop_generates_its_pulse_job.py (GATE CHANGE: + the refused case)",
      "tests/anatomy/test_loop_validator_cli.py (new)",
      "tools/README.md"
    ],
    "gates": [
      "new gate: --validate accepts the 4 committed manifests, refuses fixtures for each rule (bad id, 'sere', no trigger, unknown runner, for_each on an undeclared param, duplicate step id) with the rule named; red today: no CLI",
      "GATE CHANGE in test_loop_generates_its_pulse_job: a manifest the validator refuses yields no loop:<id> job and the catalog says why (red today: it schedules it)"
    ],
    "steps": "(1) Lift _validate_manifest to a public function that returns a list of reasons; keep --check. (2) Add the three checks the audit found missing where cheap: cron syntax (croniter if already a dependency, else a strict regex), run names an existing tools/loops/* file, writes paths under the allowed roots. (3) Scheduler shares it."
  },
  {
    "depends_on": [],
    "expected_red": [],
    "operator_decisions": [],
    "security_lens": "",
    "slug": "loop-status-reader-mode",
    "branch": "feat/loop-status-reader-mode",
    "facts": "Loops as data: files/anatomy/loops/<id>.loop.yml (4: news-scout, repo-check, pipeline-exercise, vision-bench); validator tools/loop-graph-gen.py::_validate_manifest (:107-140, private; _STEP_RUNNERS :95, _SLUG :96; _load_manifests :143-151 adds id uniqueness) with only a whole-graph --check CLI; scheduler files/anatomy/scripts/discover-pulse-catalog.py:224-251 globs the manifests and makes 'loop:<id>' Pulse jobs WITHOUT calling the validator (gate tests/anatomy/test_loop_generates_its_pulse_job.py). SERE = code: bone/ledger.py (INTENT_CLASSES :105, role writes :136, schema :254-394 + _ADDED_COLUMNS :401-414), plugin loop-base (propose 01:30 loop-propose.py --invoke, drive 06:10 loop-pr.py --open-mr --rejudge, review 06:50 loop-review.py --merge), judge sets state/judge-sets.yml, budget.py ALLOWED_ROOTS :78-86 excludes files/anatomy/loops. Readers: tools/loop-status.py (--json, --unresolved, --gap, --awaiting; per weakness source; no --loop/--since; ignores pulse_runs); tools/red-status.py reads pulse_runs. Live 2026-10-21 on the operator host: install_loops was false (now switched on by the operator — verify with the readers, never by hand); ledger 32 baseline 'live' verdicts, 0 proposals. Wing LoopEditorPresenter.php:9-31 is a read-only harness viewer. Thalamus patterns: read_run serve.rs:3697-3710 via reader(); propose_app serve.rs:4188-4224 + app_parser :4325 + write_draft :4356; ASKING :554; renderer kinds in contracts/thalamus-shell.yml v11 (timeline :217, chart :208, table :205, graph :224); kpi is KEAP-only.",
    "files_owned": [
      "tools/loop-status.py (--loop <id> --since <date> --json)",
      "tests/anatomy/test_loop_status_*.py (new or extended, tmp wing.db built from the ledger schema)",
      "tools/README.md"
    ],
    "gates": [
      "new gate over a tmp wing.db: --loop sere --since D returns verdicts by gate_set/result, judge_runs not passed, awaiting states; --loop news-scout returns its pulse_runs rows (count, exit codes, last fired, stderr tail of failures) and held jobs; with no loop:* job registered the answer is {registered: false, said: 'no loop job registered (install_loops?)'} and never an empty history; red today: the flags do not exist",
      "existing: tests/anatomy -k loop_status; test_readers_open_the_ledger_one_way; the readers-only-read gate"
    ],
    "steps": "(1) One function per source (ledger, pulse_runs, job_readiness), each UNKNOWN when unreadable. (2) The default output is unchanged. (3) Read-only, through the shared ledger opener."
  },
  {
    "depends_on": [
      "loop-validator-cli",
      "loop-status-reader-mode"
    ],
    "expected_red": [],
    "operator_decisions": [
      "whether Tier 2 may read loop runs of operational loops (default: tier 1 only)"
    ],
    "security_lens": "",
    "slug": "iris-reads-and-proposes-loops",
    "branch": "feat/iris-reads-and-proposes-loops",
    "facts": "Loops as data: files/anatomy/loops/<id>.loop.yml (4: news-scout, repo-check, pipeline-exercise, vision-bench); validator tools/loop-graph-gen.py::_validate_manifest (:107-140, private; _STEP_RUNNERS :95, _SLUG :96; _load_manifests :143-151 adds id uniqueness) with only a whole-graph --check CLI; scheduler files/anatomy/scripts/discover-pulse-catalog.py:224-251 globs the manifests and makes 'loop:<id>' Pulse jobs WITHOUT calling the validator (gate tests/anatomy/test_loop_generates_its_pulse_job.py). SERE = code: bone/ledger.py (INTENT_CLASSES :105, role writes :136, schema :254-394 + _ADDED_COLUMNS :401-414), plugin loop-base (propose 01:30 loop-propose.py --invoke, drive 06:10 loop-pr.py --open-mr --rejudge, review 06:50 loop-review.py --merge), judge sets state/judge-sets.yml, budget.py ALLOWED_ROOTS :78-86 excludes files/anatomy/loops. Readers: tools/loop-status.py (--json, --unresolved, --gap, --awaiting; per weakness source; no --loop/--since; ignores pulse_runs); tools/red-status.py reads pulse_runs. Live 2026-10-21 on the operator host: install_loops was false (now switched on by the operator — verify with the readers, never by hand); ledger 32 baseline 'live' verdicts, 0 proposals. Wing LoopEditorPresenter.php:9-31 is a read-only harness viewer. Thalamus patterns: read_run serve.rs:3697-3710 via reader(); propose_app serve.rs:4188-4224 + app_parser :4325 + write_draft :4356; ASKING :554; renderer kinds in contracts/thalamus-shell.yml v11 (timeline :217, chart :208, table :205, graph :224); kpi is KEAP-only.",
    "files_owned": [
      "files/anatomy/thalamus/thalamus/src/serve.rs (read_loop_runs tier 1 -> loop-status.py --loop --since, drawn as timeline (lane = loop or gate set) or table; propose_loop tier 1 -> YAML, loop-graph-gen.py --validate on a temp file, Markdown card with the full YAML, approve writes <data>/loops/<id>.loop.yml.draft with create_new; ASKING += propose_loop)",
      "files/anatomy/thalamus/thalamus/src/ledger.rs (approved_loop like approved_app)",
      "files/anatomy/thalamus/thalamus/tests/serve.rs",
      "state/fixtures/oneshot/thalamus-tools.json (GATE CHANGE regen) + the tool-name pin in tests/serve.rs"
    ],
    "gates": [
      "rig tests: an invalid loop gets the validator's reasons and no card; a valid one gets the card whose YAML parses back; approve writes exactly that draft; reject writes nothing; nos-users refused; read_loop_runs with the reader saying registered:false tells the model 'no loop job registered' (never an empty history); red today: unknown tools",
      "tool-list gates green after the regen; full cargo test"
    ],
    "steps": "(1) Mirror propose_app's code shape (the parser is the check). (2) The model's tool description: a draft may be graph-only or reuse an existing runner (a new runner is code: the operator's). (3) Timeline render chosen by the tool, no contract change."
  }
]
const INTEGRATION_BRANCH = "feat/iris-loops"
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
  A row that adds a graph node (reader, article, organ, tool) lists as expected-red everything a regenerate plus a
  re-sign clears (apex projection/sign/serve, anatomy-graph, body-plan, IMPRINT, the face pin), because artifacts
  are regenerated once by the integrator, not by the row.
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
"git diff <diff base>...origin/<branch>" where the diff base is the row's dependency branch when it has one (its files are
not this row's), else ${BASE}; for red-before, "git checkout --detach <the (red) commit>" and run that gate.
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
Diff base for ownership: ${row.depends_on.length ? row.depends_on.map(d => `origin/${bySlug[d].branch}`).join(' + ') : BASE}.
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

