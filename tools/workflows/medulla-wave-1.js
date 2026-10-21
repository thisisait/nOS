export const meta = {
  name: 'medulla-wave-1',
  description: 'Build medulla rows 1-4 (identity reader, workspace skeleton, nos user, metrics seam) red-green, review, integrate',
  phases: [
    { title: 'Spec', detail: 'one agent turns rows 1-4 into build specs on the DAG 1 -> 2 -> {3,4}' },
    { title: 'Build', detail: 'rows in dependency order, each in its own worktree, gate first' },
    { title: 'Review', detail: 'one skeptic per row (plus security on the nos user), one re-review of every fixed row' },
    { title: 'Fix', detail: 'at most one fix pass per refuted row' },
    { title: 'Integrate', detail: 'merge the landed branches, one full test run, report' },
  ],
}

const A = typeof args !== 'undefined' && args ? args : {}
const BASE = A.base || 'origin/dev'
const SEED = A.seed || '/Users/pazny/projects/nos-seed'
const REPO = A.repo || '/Users/pazny/projects/nOS/.claude/worktrees/loops-pause'
const SLUGS = ['medulla-organ-identity-reader', 'medulla-skeleton', 'nos-system-user-linux', 'medulla-first-route-metrics']
const DEFERRED = {
  'medulla-admin-halt': 'halt state is wing.db pulse_jobs.paused, still written by PHP Pulse (a second writer breaks one-writer-per-table); ' +
    'the halt writes an audit-chain event (row medulla-events-chain comes first); its only e2e gate targets the LIVE Wing and would halt every Pulse job',
}

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
- Never touch the live estate: no ansible-playbook, no nos, no launchctl/systemctl, no useradd/groupadd/chown
  (not even under sudo), no writes to ~/wing, ~/thalamus, ~/.nos, ~/stacks, /var/lib, /etc. Never run anything
  under tests/e2e/journeys or tests/e2e/estate (they default to the LIVE Wing 127.0.0.1:9000 and the live wing.db)
  and never import tests/e2e/lib/estate_secrets.py. Any test you write that talks HTTP or SQLite takes an explicit
  scratch URL/path with NO default pointing at a live one. Templates (units, env files) are rendered to a temp
  dir by the gate.
- Run only the lanes you touch plus the full "cargo test" of every crate you touch
  (CARGO_TARGET_DIR=/Users/pazny/.cargo-target-nos). Gates stay Python; never port a gate.
- A new node in the anatomy graph gets an apex ruling entry (files/anatomy/apex/ruling.yml, "withheld" unless the
  spec says otherwise) in its OWN clearly headed block. Do NOT commit regenerated artifacts (anatomy-graph,
  body-plan, IMPRINT, glossary, face layout pin): the integrator regenerates them once. Never run tools/apex-sign.py.
- The row that CREATES a thing owns every gate allow-list that thing needs (wave-1 lesson: a new ssot article needs
  its _BORN_IN_SSOT line in tests/anatomy/test_ssot_index.py; a new reader its tools/README §Readers line; a new
  lockfile its dependabot entry). Such a line is a "test: GATE CHANGE ..." commit of that row, never left for the
  operator. Your spec names these files under files_owned; if one is missing and you need it, add it and say so.
- Expected-red is explicit: the spec lists the gates that stay red until the integrator regenerates (apex projection,
  graph/body-plan/glossary --check). Nothing else may be red on your branch; a reviewer refutes any other red lane.
- The organ is named "medulla" (operator ruling 2026-10-21). Row sources: ${SEED}/medulla*.md, ${SEED}/nos-system-user-linux.md.`

const SPEC_SCHEMA = {
  type: 'object',
  properties: {
    rows: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          slug: { type: 'string' },
          branch: { type: 'string' },
          depends_on: { type: 'array', items: { type: 'string' } },
          files_owned: { type: 'array', items: { type: 'string' } },
          gates: { type: 'array', items: { type: 'string' } },
          steps: { type: 'string' },
          expected_red: { type: 'array', items: { type: 'string' } },
          operator_decisions: { type: 'array', items: { type: 'string' } },
        },
        required: ['slug', 'branch', 'depends_on', 'files_owned', 'gates', 'expected_red', 'steps', 'operator_decisions'],
      },
    },
    overlaps: { type: 'array', items: { type: 'string' } },
  },
  required: ['rows', 'overlaps'],
}

const BUILD_SCHEMA = {
  type: 'object',
  properties: {
    branch: { type: 'string' },
    pushed: { type: 'boolean' },
    worktree: { type: 'string' },
    commits: { type: 'array', items: { type: 'string' } },
    red_shown: { type: 'array', items: { type: 'string' } },
    green: { type: 'array', items: { type: 'string' } },
    not_verified: { type: 'array', items: { type: 'string' } },
    apex_resign_needed: { type: 'boolean' },
    operator_questions: { type: 'array', items: { type: 'string' } },
  },
  required: ['branch', 'pushed', 'worktree', 'commits', 'red_shown', 'green', 'not_verified', 'apex_resign_needed', 'operator_questions'],
}

const VERDICT_PROPS = {
  refuted: { type: 'boolean' },
  defects: { type: 'array', items: { type: 'string' } },
  checked: { type: 'array', items: { type: 'string' } },
}
const VERDICT_SCHEMA = { type: 'object', properties: VERDICT_PROPS, required: ['refuted', 'defects', 'checked'] }
const RECHECK_SCHEMA = {
  type: 'object',
  properties: { rows: { type: 'array', items: { type: 'object', properties: { slug: { type: 'string' }, ...VERDICT_PROPS },
    required: ['slug', 'refuted', 'defects', 'checked'] } } },
  required: ['rows'],
}

// A verdict that is missing, or names no command it ran, is a refutation (a crashed reviewer is not a pass).
const honest = (v, who) => !v ? { refuted: true, defects: [`${who} returned nothing`], checked: [] }
  : (!v.checked || !v.checked.length) ? { ...v, refuted: true, defects: [...(v.defects || []), `${who} listed no command it ran`] } : v

const METHOD = `Method (in your own worktree): "git fetch origin", "git checkout --detach origin/<branch>",
"git diff <diff base>...origin/<branch>" where the diff base is the row's dependency branch when it has one (its files are
not this row's), else ${BASE}; for red-before, "git checkout --detach <the (red) commit>" and run that gate.
Run every gate to a log file and read the exit code, never through a pipe. List every command with its exit code in
"checked". refuted=true if any gate is not green, was never red for the RIGHT reason (the assertion names the
missing behaviour), a house rule is broken, a file outside the row's ownership changed, or any new test/tool has a
default URL/path/token pointing at the live Wing, wing.db, ~/.nos or the Docker socket. Default to refuted=true
when uncertain.`

phase('Spec')
const spec = await agent(
  `${RULES}

Read the roadmap rows medulla, ${SLUGS.join(', ')} (files in ${SEED}) and the code they name, from ${REPO}
(absolute paths; read only). Produce one build spec per row, these four slugs exactly (medulla-admin-halt is
DEFERRED: ${DEFERRED['medulla-admin-halt']}).
The DAG is fixed: medulla-organ-identity-reader first (it defines the lexicon row, ssot/doctrine/medulla.md
(PROPOSED, in_force: false) and the apex entries the others cite); medulla-skeleton depends on it;
nos-system-user-linux and medulla-first-route-metrics both depend on medulla-skeleton. Rows that run in parallel
(3 and 4) may touch default.config.yml and ruling.yml only in a new, separately headed block each; generated
artifacts are never committed by a row (the integrator regenerates them).
Facts to build on, measured: files/anatomy/thalamus/ holds two crates (thalamus, contract) with NO workspace root
and a per-crate thalamus/thalamus/Cargo.lock; the lane gate tests/anatomy/test_pupil_and_thalamus_lanes_run.py
(CRATES dict) pins those paths with "cargo test --locked", and 13 more tests/anatomy/test_*.py,
roles/pazny.thalamus/tasks/{main,linux,macos}.yml, tools/nos_cell_binding.py and .github/dependabot.yml hard-code
files/anatomy/thalamus. So medulla-skeleton puts a workspace root Cargo.toml IN files/anatomy/thalamus/ with
members thalamus, contract, medulla and ONE workspace Cargo.lock (update the gate's --locked paths in a GATE CHANGE
commit); renaming the directory to files/anatomy/medulla is an operator decision for a later row, not part of this
(a git symlink would not be followed by dependabot or --locked CI). thalamus/src/relay.rs already has a std
TcpListener HTTP loop on loopback: medulla-first-route-metrics reuses that pattern (no new HTTP stack); decide and
state what the medulla enforces for /api/v1/metrics (today Nette's token layer guards it: loopback-only? a scrape
bearer?). Its two-backend contract run is offline exactly like tests/anatomy/test_halt_has_a_break_glass.py does
it: real PHP presenters over a scratch wing.db (bin/init-db.php + php's built-in server) and the medulla binary on
the same scratch db, both answers validated against files/anatomy/contracts/wing.openapi.yml#/api/v1/metrics; red =
the rendered wing.Caddyfile.j2 has no "handle /api/v1/metrics*" block. nos-system-user-linux is Linux only: a role
plus gates that render the unit/user/env to a temp dir; never applied on this macOS host; the unit runs the
medulla binary as User=nos (not root, not in the docker group), ReadWritePaths=/var/lib/nos only (never the repo or
$HOME), EnvironmentFile 0640 root:nos asserted by the gate; the config key nos_system_user is the operator's.
For each row: branch feat/<slug>, depends_on, the EXACT files it owns (INCLUDING every gate allow-list the row's
new things need: tests/anatomy/test_ssot_index.py _BORN_IN_SSOT for a new ssot article, tools/README.md for a new
reader, .github/dependabot.yml for a new lockfile, the lane gate for a new crate path), its gates (named tests, red
first), the expected_red list (gates that stay red until the integrator regenerates; nothing else may be red),
concrete steps, and operator_decisions left open. Return the specs and any overlap you could not remove.`,
  { label: 'spec', phase: 'Spec', schema: SPEC_SCHEMA })

if (!spec) return { error: 'the spec agent returned nothing' }
const bySlug = Object.fromEntries(spec.rows.map(r => [r.slug, r]))
const badSlugs = SLUGS.filter(s => !bySlug[s]).concat(spec.rows.map(r => r.slug).filter(s => !SLUGS.includes(s)))
if (badSlugs.length) return { error: `spec slugs mismatch: ${badSlugs.join(', ')}`, spec }
const unknownDeps = spec.rows.flatMap(r => r.depends_on.filter(d => !bySlug[d]))
if (unknownDeps.length) return { error: `depends_on names unknown slugs: ${unknownDeps.join(', ')}`, spec }
if (spec.overlaps.length) log(`spec reports overlaps: ${spec.overlaps.join(' | ')}`)

const build = row => agent(
  `${RULES}

Build roadmap row ${row.slug} on branch ${row.branch} (cut from ${BASE}${row.depends_on.length ?
    `, then merge ${row.depends_on.map(d => `origin/${bySlug[d].branch}`).join(' and ')} into it first` : ''}).
You own these files and no others: ${row.files_owned.join(', ')}.
Gates (each shown red first): ${row.gates.join('; ')}.
Expected red until the integrator regenerates (and nothing else): ${row.expected_red.join('; ') || 'none'}.
Steps: ${row.steps}
Leave open for the operator: ${row.operator_decisions.join('; ') || 'nothing named'}.
Return what you committed, what you saw red and green (exact commands + exit codes), your worktree path, what you did not verify.`,
  { label: `build:${row.slug}`, phase: 'Build', schema: BUILD_SCHEMA, isolation: 'worktree', model: 'opus' })

const review = (row, built, lens) => agent(
  `You are a skeptic reviewing branch origin/${built.branch} (roadmap row ${row.slug}) through the ${lens} lens.
Try to REFUTE that it is done. Its gates: ${row.gates.join('; ')}. It may change only: ${row.files_owned.join(', ')}.
Diff base for ownership: ${row.depends_on.length ? row.depends_on.map(d => `origin/${bySlug[d].branch}`).join(' + ') : BASE}.
Red is allowed ONLY on: ${row.expected_red.join('; ') || 'nothing'} (they wait for the integrator's regeneration); any
other red lane among the row's named lanes refutes it.
${METHOD}
${lens === 'security' ? 'Security lens: the nos user is not in the docker group; the unit is not root; ReadWritePaths never includes the repo or $HOME; EnvironmentFile 0640 root:nos is asserted by a gate, not by prose; file modes and ownership never widen access; nothing assumes $HOME; sudo only at converge.' : ''}
Builder said: ${JSON.stringify(built)}`,
  { label: `review:${row.slug}:${lens}`, phase: 'Review', schema: VERDICT_SCHEMA, isolation: 'worktree', model: 'opus' })

const results = {}
// args.landed: {slug: branch} rows already built, reviewed and pushed by an earlier run; treated as landed.
for (const [s, b] of Object.entries(A.landed || {})) {
  if (SLUGS.includes(s)) results[s] = { built: { branch: b, pushed: true, worktree: '(earlier run)', commits: [], red_shown: [], green: [],
    not_verified: ['landed by an earlier run; not re-reviewed here'], apex_resign_needed: true, operator_questions: [] },
    verdicts: [], defects: [], fixed: null, landed: true, still_refuted: false }
}

async function runRow(row) {
  const built = await build(row)
  if (!built) return (results[row.slug] = { built: null, landed: false, why: 'the builder returned nothing' })
  const lenses = row.slug === 'nos-system-user-linux' ? ['correctness', 'security'] : ['correctness']
  const raw = await parallel(lenses.map(l => () => review(row, built, l)))
  const verdicts = raw.map((v, i) => honest(v, `reviewer ${lenses[i]}`))
  const defects = verdicts.filter(v => v.refuted).flatMap(v => v.defects)
  let fixed = null
  if (defects.length) {
    log(`${row.slug}: refuted, one fix pass (${defects.length} defects)`)
    fixed = await agent(
      `${RULES}

Fix branch ${built.branch} (roadmap row ${row.slug}); a reviewer refuted it:
${defects.map(d => `- ${d}`).join('\n')}
In your own worktree: "git fetch origin && git checkout --detach origin/${built.branch}", fix each defect with its own
commit (gate first where a gate is missing), then push with "tools/nos-push --skip-sync origin HEAD:${built.branch}"
and confirm with git ls-remote. Files you may touch: ${row.files_owned.join(', ')}, plus a gate allow-list the
row's new thing needs (ssot _BORN_IN_SSOT, tools/README, dependabot) as its own GATE CHANGE commit.`,
      { label: `fix:${row.slug}`, phase: 'Fix', schema: BUILD_SCHEMA, isolation: 'worktree', model: 'opus' })
  }
  results[row.slug] = { built, verdicts, defects, fixed,
    landed: !defects.length && built.pushed, still_refuted: defects.length > 0 }
  return results[row.slug]
}

phase('Build')
const pending = new Set(SLUGS)
while (pending.size) {
  for (const s of [...pending]) if (results[s] && results[s].landed) pending.delete(s)
  if (!pending.size) break
  const ready = [...pending].map(s => bySlug[s]).filter(r => r.depends_on.every(d => results[d] && results[d].landed))
  // A row whose dependency was refuted and is being fixed waits for the re-review below; anything else is blocked.
  if (!ready.length) {
    const fixedRows = Object.entries(results).filter(([, r]) => r.fixed && r.still_refuted && !r.rechecked)
    if (fixedRows.length) {
      phase('Review')
      const recheck = await agent(
        `You are a skeptic re-reviewing fixed branches:
${fixedRows.map(([s, r]) => `- ${s}: origin/${r.fixed.branch}; defects claimed fixed: ${r.defects.join('; ')}; gates: ${bySlug[s].gates.join('; ')}`).join('\n')}
${METHOD}
Return one verdict per slug.`,
        { label: 'rereview', phase: 'Review', schema: RECHECK_SCHEMA, isolation: 'worktree', model: 'opus' })
      for (const [s, r] of fixedRows) {
        const v = honest(recheck && recheck.rows.find(x => x.slug === s), `re-reviewer of ${s}`)
        r.rechecked = v
        r.still_refuted = v.refuted
        r.landed = r.fixed.pushed && !v.refuted
      }
      phase('Build')
      continue
    }
    log(`not built, a dependency did not land: ${[...pending].join(', ')}`)
    break
  }
  ready.forEach(r => pending.delete(r.slug))
  await parallel(ready.map(r => () => runRow(r)))
}
// Rows fixed in the last wave get their re-review too.
const lateFixed = Object.entries(results).filter(([, r]) => r.fixed && r.still_refuted && !r.rechecked)
if (lateFixed.length) {
  phase('Review')
  const recheck = await agent(
    `You are a skeptic re-reviewing fixed branches:
${lateFixed.map(([s, r]) => `- ${s}: origin/${r.fixed.branch}; defects claimed fixed: ${r.defects.join('; ')}; gates: ${bySlug[s].gates.join('; ')}`).join('\n')}
${METHOD}
Return one verdict per slug.`,
    { label: 'rereview-late', phase: 'Review', schema: RECHECK_SCHEMA, isolation: 'worktree', model: 'opus' })
  for (const [s, r] of lateFixed) {
    const v = honest(recheck && recheck.rows.find(x => x.slug === s), `re-reviewer of ${s}`)
    r.rechecked = v
    r.still_refuted = v.refuted
    r.landed = r.fixed.pushed && !v.refuted
  }
}

phase('Integrate')
const landed = SLUGS.filter(s => results[s] && results[s].landed).map(s => (results[s].fixed || results[s].built).branch)
const integration = landed.length ? await agent(
  `${RULES}

Integrate ${landed.map(b => `origin/${b}`).join(', ')} into a new branch feat/medulla-wave-1 cut from ${BASE}, in your
own worktree (merge the origin/ refs, never local branch names: other worktrees hold them). Resolve conflicts keeping
both sides' intent; a ruling.yml conflict keeps every entry (never drop one). Then regenerate the generated artifacts
with their writers, once (tools/anatomy-graph-gen.py --refreeze, tools/body-plan-gen.py, tools/imprint-gen.py,
tools/genome-codegen.py if the lexicon changed), and commit them.
Your ONE full run, each to its own log file in the background with a long timeout, reading the summary line and the
exit code (never "| tail"): "python3 -m pytest tests/anatomy -q -p no:cacheprovider", the full "cargo test --locked"
of every crate touched, the face vitest lane if face changed. Push feat/medulla-wave-1 with
"tools/nos-push --skip-sync origin HEAD:feat/medulla-wave-1". Report every failure with its reason; the apex signature
failing is expected (the operator signs): set apex_resign_needed and do not "fix" it. Include in not_verified anything
you did not run, and put the output of "git worktree list" in operator_questions' last entry.`,
  { label: 'integrate', phase: 'Integrate', schema: BUILD_SCHEMA, isolation: 'worktree', model: 'opus' }) : null

return {
  deferred: DEFERRED,
  spec: spec.rows.map(r => ({ slug: r.slug, branch: r.branch, depends_on: r.depends_on, files_owned: r.files_owned,
    gates: r.gates, operator_decisions: r.operator_decisions })),
  spec_overlaps: spec.overlaps,
  rows: Object.fromEntries(SLUGS.map(s => {
    const r = results[s]
    if (!r) return [s, { built: false, why: 'a dependency did not land' }]
    const b = r.fixed || r.built
    return [s, b ? {
      branch: b.branch, worktree: b.worktree, pushed: b.pushed, landed: r.landed, fixed: !!r.fixed,
      still_refuted: !!r.still_refuted, commits: b.commits, red_shown: b.red_shown,
      review: (r.verdicts || []).map(v => ({ refuted: v.refuted, defects: v.defects, checked: v.checked })),
      rereview: r.rechecked || null, not_verified: b.not_verified, operator_questions: b.operator_questions,
    } : { built: false, why: r.why }]
  })),
  integration,
  apex_resign_needed: !!(integration && integration.apex_resign_needed) ||
    Object.values(results).some(r => r && (r.fixed || r.built) && (r.fixed || r.built).apex_resign_needed),
  operator_merge: integration && integration.pushed
    ? 'from a checkout that does not hold the branch: git fetch origin && git merge --ff-only origin/feat/medulla-wave-1'
    : null,
}
