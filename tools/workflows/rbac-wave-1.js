export const meta = {
  "name": "rbac-wave-1",
  "description": "v0.18 track D, permissions: the genome file and its reader (no behaviour change) and the measured RBAC defects fixed with gates",
  "whenToUse": "Independent; run after the operator rules on permissions.md §5 only if contributor/moderator are wanted inside (they are not in this wave).",
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
    "expected_red": [
      "everything a regenerate plus a re-sign clears, measured: apex projection/sign/serve/rebuild/fonts, anatomy-graph --check, body-plan --check, test_imprint_is_rendered, the face layout pin (reader:rbac-status is a new graph node; the integrator regenerates, the operator signs)"
    ],
    "operator_decisions": [
      "doors and agents in the same genome as people (default yes, one file)"
    ],
    "security_lens": "",
    "slug": "rbac-genome-and-reader",
    "branch": "feat/rbac-genome-and-reader",
    "facts": "Inventory 2026-10-21 (ssot/doctrine/permissions.md §4, PROPOSED): ~45 enforcement points in 9 areas; tier 1 decided in six places (Wing EndUser.php:19 OPERATOR_GROUPS, Wing BasePresenter.php:63-68 TIER_GROUPS + :383 requireSuperAdmin, thalamus NOS_TIER1_GROUPS main.rs:105, face lib/security/tier.ts:12-24, KEAP internally, Authentik is_superuser in authentik-base blueprints 00-admin-groups.yaml.j2:26); five different missing-tier defaults (blueprint 3, load_plugins.py:419-425 2, face hub 3, Wing HubPresenter.php:152-155 1 = show all, cortex rbac.ts guest). Readers: tools/identity-status.py (roster vs realms), none prints capability x role. Defects: GitLab roles/pazny.gitlab/templates/compose.yml.j2:56 admin_groups = tier-1 groups | last (drops nos-providers); same idiom in roles/pazny.receptor/templates/identity-map.yml.j2, roles/pazny.linux.users/tasks/main.yml:23, roles/pazny.jupyterhub/templates/jupyterhub_config.py.j2:41-49, tools/identity-status.py:201-215; Node-RED roles/pazny.nodered/templates/settings.js.j2:41 every authenticated user is admin; Wing BasePresenter.php:378 cites test_security_admin_gate_unchanged which does not exist; declared-unenforced scopes events.write, audit.read, security.scan, pentest.execute (agents) and Bone nos:security:*, nos:pentest:execute, nos:devlog:write. twofauth tier fixed 2026-10-21 (159f446b8, gate test_an_app_states_one_tier.py).",
    "files_owned": [
      "state/genome/permissions.yml (new: capabilities x roles seeded from what is enforced today; roles = tiers 1-4, agent:<name>, door:<bearer>, operator-local)",
      "tools/rbac-status.py (new reader: matrix + drift per enforcement point + UNKNOWN; reads the literals listed in the facts, never the live estate)",
      "tests/anatomy/test_rbac_status_reads_the_matrix.py (new)",
      "tools/README.md (§Readers line)",
      "files/anatomy/apex/ruling.yml (reader:rbac-status withheld, own block)",
      "state/genome/lexicon.yml only if a word is new (say so)"
    ],
    "gates": [
      "new gate: the reader prints every capability with its roles; a planted drift fixture (a literal that disagrees with the genome) is named with file:line; an unreadable source is UNKNOWN; red today: no reader",
      "test_the_tools_index_is_complete, test_readers_section_only_reads, test_the_new_readers_only_read green"
    ],
    "steps": "(1) Genome file with a header that says it is DESCRIPTIVE in this wave (what is enforced), prescriptive later. (2) Reader with one parser per enforcement point family (PHP const, TS const, Jinja literal, YAML tier). (3) No enforcement point changes."
  },
  {
    "depends_on": [],
    "expected_red": [],
    "operator_decisions": [
      "GitLab: a converge re-syncs admin_groups; existing admins unchanged"
    ],
    "security_lens": "",
    "slug": "rbac-groups-last-idiom",
    "branch": "feat/rbac-groups-last-idiom",
    "facts": "Inventory 2026-10-21 (ssot/doctrine/permissions.md §4, PROPOSED): ~45 enforcement points in 9 areas; tier 1 decided in six places (Wing EndUser.php:19 OPERATOR_GROUPS, Wing BasePresenter.php:63-68 TIER_GROUPS + :383 requireSuperAdmin, thalamus NOS_TIER1_GROUPS main.rs:105, face lib/security/tier.ts:12-24, KEAP internally, Authentik is_superuser in authentik-base blueprints 00-admin-groups.yaml.j2:26); five different missing-tier defaults (blueprint 3, load_plugins.py:419-425 2, face hub 3, Wing HubPresenter.php:152-155 1 = show all, cortex rbac.ts guest). Readers: tools/identity-status.py (roster vs realms), none prints capability x role. Defects: GitLab roles/pazny.gitlab/templates/compose.yml.j2:56 admin_groups = tier-1 groups | last (drops nos-providers); same idiom in roles/pazny.receptor/templates/identity-map.yml.j2, roles/pazny.linux.users/tasks/main.yml:23, roles/pazny.jupyterhub/templates/jupyterhub_config.py.j2:41-49, tools/identity-status.py:201-215; Node-RED roles/pazny.nodered/templates/settings.js.j2:41 every authenticated user is admin; Wing BasePresenter.php:378 cites test_security_admin_gate_unchanged which does not exist; declared-unenforced scopes events.write, audit.read, security.scan, pentest.execute (agents) and Bone nos:security:*, nos:pentest:execute, nos:devlog:write. twofauth tier fixed 2026-10-21 (159f446b8, gate test_an_app_states_one_tier.py).",
    "files_owned": [
      "roles/pazny.gitlab/templates/compose.yml.j2",
      "roles/pazny.receptor/templates/identity-map.yml.j2",
      "roles/pazny.linux.users/tasks/main.yml",
      "roles/pazny.jupyterhub/templates/jupyterhub_config.py.j2",
      "tools/identity-status.py",
      "tests/anatomy/test_receptor_relay.py (GATE CHANGE: its tier-1 pin ['nos-admins'] becomes both groups; own commit)",
      "tests/anatomy/test_tier_one_is_every_tier_one_group.py (new: renders each template with stock Jinja and asserts both nos-providers and nos-admins appear where tier 1 is meant)",
      "tests/anatomy/test_identity_status_*.py (GATE CHANGE if an expectation moves)"
    ],
    "gates": [
      "new gate red today on GitLab admin_groups and the three others",
      "existing identity gates green"
    ],
    "steps": "(1) Replace '| last' with the full tier-1 list in the form each consumer takes (GitLab: a list; receptor/unix: groups list; Jupyter: the set). (2) identity-status reports all tier-1 groups per login."
  },
  {
    "depends_on": [],
    "expected_red": [],
    "operator_decisions": [
      "Node-RED: whether non-admins get 'read' or nothing"
    ],
    "security_lens": "",
    "slug": "rbac-nodered-and-dead-citation",
    "branch": "feat/rbac-nodered-and-dead-citation",
    "facts": "Inventory 2026-10-21 (ssot/doctrine/permissions.md §4, PROPOSED): ~45 enforcement points in 9 areas; tier 1 decided in six places (Wing EndUser.php:19 OPERATOR_GROUPS, Wing BasePresenter.php:63-68 TIER_GROUPS + :383 requireSuperAdmin, thalamus NOS_TIER1_GROUPS main.rs:105, face lib/security/tier.ts:12-24, KEAP internally, Authentik is_superuser in authentik-base blueprints 00-admin-groups.yaml.j2:26); five different missing-tier defaults (blueprint 3, load_plugins.py:419-425 2, face hub 3, Wing HubPresenter.php:152-155 1 = show all, cortex rbac.ts guest). Readers: tools/identity-status.py (roster vs realms), none prints capability x role. Defects: GitLab roles/pazny.gitlab/templates/compose.yml.j2:56 admin_groups = tier-1 groups | last (drops nos-providers); same idiom in roles/pazny.receptor/templates/identity-map.yml.j2, roles/pazny.linux.users/tasks/main.yml:23, roles/pazny.jupyterhub/templates/jupyterhub_config.py.j2:41-49, tools/identity-status.py:201-215; Node-RED roles/pazny.nodered/templates/settings.js.j2:41 every authenticated user is admin; Wing BasePresenter.php:378 cites test_security_admin_gate_unchanged which does not exist; declared-unenforced scopes events.write, audit.read, security.scan, pentest.execute (agents) and Bone nos:security:*, nos:pentest:execute, nos:devlog:write. twofauth tier fixed 2026-10-21 (159f446b8, gate test_an_app_states_one_tier.py).",
    "files_owned": [
      "roles/pazny.nodered/templates/settings.js.j2 (adminAuth: tier-1 groups -> permission '*', others 'read'; from the forward-auth header the plugin already trusts)",
      "files/anatomy/plugins/nodered-base/plugin.yml (only if the header mapping lives there)",
      "tests/anatomy/test_nodered_admin_is_tier_one.py (new)",
      "files/anatomy/wing/app/Presenters/BasePresenter.php:378 (the comment names an existing gate or is removed)",
      "tests/anatomy/test_wing_comments_cite_existing_gates.py (new, small: every 'test_*.py' named in a Wing PHP comment exists)"
    ],
    "gates": [
      "Node-RED gate red today (every user admin); Wing citation gate red today (test_security_admin_gate_unchanged missing)"
    ],
    "steps": "(1) Node-RED: read the group header, map tier 1 to '*', the rest to 'read'; a missing header = no login (fail closed). (2) Wing: cite the real gate (find which test pins requireSuperAdmin; if none, write the smallest one and cite it)."
  }
]
const INTEGRATION_BRANCH = "feat/rbac-wave-1"
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

