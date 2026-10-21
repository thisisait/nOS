export const meta = {
  "name": "rel-018-hygiene-b",
  "description": "v0.18 track A, roadmap: the reconcile after v0.17-beta prepared row by row with evidence, in the PRIVATE seed repo; the operator confirms closures",
  "whenToUse": "After rel-018-hygiene-a or in parallel. Touches the seed repo only (NOS_SEED_DIR, a branch reconcile-2026-10); no nOS code. The integrator's output is ONE confirm list.",
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
      "every closure and reparent: one confirm per group, from the list"
    ],
    "security_lens": "",
    "slug": "reconcile-release-and-stubs",
    "branch": "reconcile-2026-10/release-and-stubs",
    "facts": "Seed rows rel-015 (active), rel-016 (next), rel-017 (next) are open while tags v0.15-beta, v0.16-beta, v0.17-beta exist (git tag). edge-two-doors has parent rel-016; w-agentkit-spine and w-datalog carry release: v0.11-beta under shipped rel-011. Ten RENAMED stubs are open: active claude-cli-respects-existing->symbiont-claude, home-benchmark->apgar, home-graph->body-plan, host-software-ownership->self-symbiont-host; next docker-runtime-choice->habitat-docker-runtime, genome-ownership-facets->genome-facets, home-door->imprint, profile-builder-graph->phenotype, specialization-packs->tissues, stable-contract->maturity (their bodies say 'RENAMED 2026-10-05 … this one is dropped'); rel-017's five next children are all stubs.",
    "files_owned": [
      "<seed>/rel-015.md, rel-016.md, rel-017.md, edge-two-doors.md, w-agentkit-spine.md, w-datalog.md and the ten stub files (git-owned halves only, via nos dtt capture --update)",
      "<seed>/reconcile-2026-10.md (the evidence list, one line per row: slug, proposed status, evidence)"
    ],
    "gates": [
      "nos dtt capture --dry-run on every touched file passes (the seeder would accept it)",
      "the evidence list names a tag, commit or file for every proposed closure"
    ],
    "steps": "(1) For each row append an 'Evidence 2026-10-21' paragraph to the body with the tag/commit and the proposed move (shipped / dropped / reparent). (2) NEVER change status in the file for a row the table already holds: status moves are the operator's 'nos dtt update'; write the exact commands into reconcile-2026-10.md. (3) rel-017's non-beta goal becomes one sentence in rel-018's body (already there: 'stays -beta')."
  },
  {
    "depends_on": [],
    "expected_red": [],
    "operator_decisions": [
      "each ship/drop from the list"
    ],
    "security_lens": "",
    "slug": "reconcile-done-and-duplicates",
    "branch": "reconcile-2026-10/done-and-duplicates",
    "facts": "Next rows git shows as done (one matching commit subject each; verify the GATE, not the subject): blank-run-record (10f280e2), blank-record-after-last-step (1bcb16ce), prompt-echoes-password-prefix (fc4c3525), agent-session-rebind-event (ff576686), converge-keychain-preflight = ssh-converge-locked-keychain (754fa5c17), halt-has-no-break-glass (12bb6a7d8), iris-reads-red-status (e6ef2b068), imprint-short-for-local-models (638cb3ed9), iris-genui-tree-timeline (6fa814beb), keap-recall (ecf278d6a), ci-ubuntu-latest-moves-to-26 (d97c872d0), event-type-gate-dot-blind (31f425905), iris-face-app (IrisApp.svelte exists), iris-transport-seam (transport.ts/transport.tauri.ts exist). Duplicate groups: docker-headroom-not-a-constant ~ keap-converge-stall; organ-one-meaning ~ plat-organ-identity ~ daemon-manifest-drift; tissues ~ tissue-is-the-chart; prose-retirement ~ retire-healing-words ~ keap-is-memory-cortex-reasons ~ lexicon-gate-sees-the-body; plat-active-work-datatable ~ tables.",
    "files_owned": [
      "the named seed files (git-owned halves via nos dtt capture --update)",
      "<seed>/reconcile-2026-10.md (append)"
    ],
    "gates": [
      "for every 'done' claim the named gate was RUN (to a log, exit code read) in a worktree of origin/dev and is green; a row whose gate is absent or red stays open and says so",
      "nos dtt capture --dry-run passes on every touched file"
    ],
    "steps": "(1) Done rows: run the gate the row names (or the commit's test), record 'Evidence: <gate> green at <sha>' and propose shipped. (2) Duplicates: pick the survivor (the one with the gate or the newest ruling), fold the others' unique facts into it, propose dropped for the rest with 'folded into <slug>'. (3) Everything into reconcile-2026-10.md as operator commands."
  },
  {
    "depends_on": [],
    "expected_red": [],
    "operator_decisions": [
      "reparents and drops from the list"
    ],
    "security_lens": "",
    "slug": "reconcile-contradictions-and-refs",
    "branch": "reconcile-2026-10/contradictions-and-refs",
    "facts": "Operator ruling 2026-10-21 (seed row medulla): the host bridge is a THREAD of the medulla with a tiny root-side unit, nos system user on Linux, PHP leaves Wing route by route. Contradicted rows: core-host-bridge ('one native daemon'), containerized-core (order: bridge first as its own daemon), w-agentkit-spine ('every agent run goes through AgentKit', PHP), organelles-not-agentkit and agentkit-rust-organ overlap the medulla plan, face-the-endpoint's title says 'write path into Wing AgentKit comes first'. Parent/child status inversions: rbac-permission-genome (queued) with next children rbac-genome-and-reader, rbac-measured-defects; face-app-builder and iris-app-toolchain (queued) with next child app-standards-are-parsed. Broken refs: docs/doctrine/{organs,tissues,identity,cross-repo-contracts,foreign-properties}.md -> ssot/doctrine/{body-plan,tissue,identity,cross-repo-contracts,foreign-properties}.md; docs/bones-and-wings-refactor.md -> docs/archive/; files/anatomy/skills/contracts/wing.openapi.yml -> files/anatomy/contracts/wing.openapi.yml; tools/cortex-query.py -> tools/keap-recall.py; body-organ's BLOCKER cites the promoted organs.md §3. ssot/doctrine/loops.md §7.1 lists requires_operator as missing though seed row loop-requires-operator is shipped (that one is an nOS doc fix: report it, do not edit nOS here).",
    "files_owned": [
      "the named seed files (git-owned halves via nos dtt capture --update)",
      "<seed>/reconcile-2026-10.md (append)"
    ],
    "gates": [
      "every ref in the touched rows resolves with git ls-files in a worktree of origin/dev",
      "nos dtt capture --dry-run passes"
    ],
    "steps": "(1) Amend each contradicted body with a dated 'Superseded in part by the medulla ruling 2026-10-21: …' paragraph and propose reparent under medulla where the row survives, dropped where the medulla rows cover it entirely (say which medulla-* row). (2) Fix the refs. (3) Propose status next for the two inverted parents. (4) body-organ: replace the BLOCKER with the body-plan.md section it meant."
  }
]
const INTEGRATION_BRANCH = "reconcile-2026-10"
const INTEGRATION_EXTRA = "THIS INTEGRATION IS IN THE SEED REPO (NOS_SEED_DIR): merge the three reconcile branches into reconcile-2026-10 there, run 'nos dtt seed --dry-run' and put its output plus the consolidated operator command list (nos dtt update \u2026 per row, grouped) into operator_questions. No pytest, no cargo, no apex: set apex_resign_needed false."

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

