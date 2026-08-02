export const meta = {
  name: 'cortex-s1c-pulse-selfmodel',
  description: 'S1c (debt 1) — give Pulse a manifest row, a self-model node and a docs tree, so the fourth host organ stops being invisible to the estate.',
  whenToUse: 'After cortex-s1b-docs-backfill. S1b reached 62/62 on the manifest denominator but named Pulse as the one genuinely-installed service OUTSIDE it — no manifest row, no self-model node, zero typed nodes. Prerequisite before S2 embedding.',
  phases: [
    { title: 'Ground', detail: 'pulse facts from source + what else consumes the manifest' },
    { title: 'Build', detail: 'manifest row + docs tree, regenerate the self-model' },
    { title: 'Verify', detail: 'adversarial: row-vs-source, and consumer regressions from a 63rd row' },
    { title: 'Finalise', detail: 'fix confirmed defects, run every suite, commit' },
  ],
}

const NOS = '/Users/pazny/projects/nOS'
const SCHEMA = NOS + '/docs/archive/cortex-docs-schema.md'
const BRANCH = 'feat/cortex-docs-knowledge'

const RULES = [
  'HARD CONSTRAINTS',
  '- Work in ' + NOS + ' on branch ' + BRANCH + '. NEVER touch main/dev, never tag, never release, never merge.',
  '- DO NOT DEPLOY: no ansible-playbook run, no converge, no docker restart, no launchctl, no container writes. Read the repo. A syntax-check (ansible-playbook --syntax-check) is allowed; nothing that mutates the host is.',
  '- NEVER host-sqlite3 the live KEAP db. Run generators into an ISOLATED temp store only; never disturb a running daemon.',
  '- No new dependencies. tests/anatomy is pytest; the organ suite is vitest; both stay green.',
  '- Commit with a real message that says WHY.',
  '',
  'ACCURACY OVER COMPLETION. Every value you write must be read from source (roles/pazny.pulse/defaults/main.yml, roles/pazny.pulse/templates/pulse.plist.j2, roles/pazny.pulse/tasks/, files/anatomy/pulse/, default.config.yml). If a field has no true value, OMIT it — do not invent one to make the row look complete.',
  '',
  'THE ONE TRAP, NAMED: Pulse does NOT listen on a port. It is a scheduler that CALLS Wing at pulse_wing_api_base (loopback 127.0.0.1:wing_port) and reports runs back. It has no domain and no inbound HTTP surface. So it gets NO port_var, NO domain_var, and NO http health_check. Portless rows are legitimate precedent (watchtower, opencode, iiab_terminal, backup, tailscale) and health_check type exec exists (5 rows). Inventing http://localhost:<port>/health for Pulse would be the exact confident-wrong failure this whole stage exists to remove.',
].join('\n')

const GROUND = {
  type: 'object', additionalProperties: false, required: ['summary', 'fields', 'risks'],
  properties: {
    summary: { type: 'string' },
    fields: { type: 'array', items: {
      type: 'object', additionalProperties: false, required: ['field', 'value', 'source'],
      properties: { field: { type: 'string' }, value: { type: 'string' }, source: { type: 'string' }, note: { type: 'string' } },
    } },
    risks: { type: 'array', items: { type: 'string' } },
  },
}
const FINDINGS = {
  type: 'object', additionalProperties: false, required: ['findings'],
  properties: { findings: { type: 'array', items: {
    type: 'object', additionalProperties: false, required: ['title', 'file', 'severity', 'failure_scenario'],
    properties: { title: { type: 'string' }, file: { type: 'string' }, severity: { type: 'string', enum: ['major', 'minor'] }, failure_scenario: { type: 'string' } },
  } } },
}
const VERDICT = { type: 'object', additionalProperties: false, required: ['real', 'why'], properties: { real: { type: 'boolean' }, why: { type: 'string' } } }

phase('Ground')

const LENSES = [
  { key: 'pulse-facts', prompt: [
    'Establish the TRUE manifest row for Pulse, field by field, from source only.',
    'Read: roles/pazny.pulse/defaults/main.yml, roles/pazny.pulse/tasks/main.yml, roles/pazny.pulse/templates/pulse.plist.j2, roles/pazny.pulse/meta/main.yml, roles/pazny.pulse/README.md, files/anatomy/pulse/ (the source tree), and the pulse lines in default.config.yml.',
    'Then read state/schema/manifest.schema.json and state/manifest.yml to learn the EXACT row contract: which fields are required, which are optional, what enums a field accepts (category, version_source, health_check.type).',
    'Compare against the three existing host-organ rows (bone, wing, cortex) — they are the precedent: stack null, version_source launchd, launchd_label set. And against the portless rows (watchtower, opencode, iiab_terminal, backup, tailscale) — the precedent for a row with no port_var.',
    'Decide and JUSTIFY each field: id, category, stack, install_flag, version_source, launchd_label, data_path_var, health_check (if any), upgrade_recipe, coexistence_supported, breaking_boundaries.',
    'Specifically resolve: (a) which var is the right data_path_var — pulse_home or pulse_state_dir — and why; (b) whether a health_check is honestly expressible for a portless launchd daemon (an exec check against launchctl / the state dir / the log is possible — is one of them TRUE and useful, or is omitting health_check the honest answer?); (c) what the Linux side is (systemd --user unit name) and whether the row must express both.',
    'Also note: does Pulse appear in state/manifest.yml under some OTHER id form (pulse_daemon, nos-pulse)? Confirm it is genuinely absent, not just differently named.',
  ].join('\n') },
  { key: 'consumers', prompt: [
    'Inventory EVERY consumer of state/manifest.yml and predict what a 63rd row — a portless, domainless host-organ row for Pulse — does to each.',
    'Find them by searching the repo for manifest.yml reads: Ansible tasks, roles, files/anatomy/scripts/*.py (especially keap_selfmodel_gen.py and keap_docs_gen.py), files/anatomy/library/*.py, tools/*.py, the Traefik file-provider derivation, the service registry, the tofu authentik registry generator, backup, and tests/anatomy/*.py.',
    'For each consumer answer: does it iterate all services? does it REQUIRE port_var/domain_var (and would it KeyError / emit a broken route for a row without them)? does it assume a docker stack (stack null)? does it hardcode the count 62?',
    'The specific risks to confirm or refute:',
    '  - Traefik file provider: does a row without domain_var+port_var get skipped cleanly, or does it emit a malformed router? (a broken route would be a live-estate regression)',
    '  - keap_selfmodel_gen.py: what does it emit for a stack-null row, and where does the node land in the tree (nos.<stack>.<id> needs a stack)? THIS IS THE LOAD-BEARING ONE — if stack is null, what is the node id? Look at how bone/wing/cortex nodes are actually emitted today.',
    '  - tests that pin the denominator: grep tests/anatomy for 62, and for the manifest service count, so Build knows exactly which assertions must move to 63.',
    'Report each as a risk with the file that carries it. Do not speculate where you can read the code.',
  ].join('\n') },
]

const ground = await parallel(LENSES.map((l) => () => agent([RULES, '', l.prompt].join('\n'),
  { label: 'ground:' + l.key, phase: 'Ground', schema: GROUND, effort: 'high' })))

const facts = ground.filter(Boolean)
log('ground: ' + facts.reduce((n, g) => n + (g.fields || []).length, 0) + ' fields established, ' +
    facts.reduce((n, g) => n + (g.risks || []).length, 0) + ' risks named')

phase('Build')

const build = await agent([RULES, '',
  'Ground truth established by the two research lenses:',
  JSON.stringify(facts, null, 1).slice(0, 6000),
  '',
  'Now close debt 1. Three artefacts, in this order:',
  '',
  '1. THE MANIFEST ROW. Add Pulse to state/manifest.yml using ONLY the fields the ground phase justified. Place it beside the other host organs (bone/wing/cortex) rather than at the end, if the file has a discernible order. Validate the result against state/schema/manifest.schema.json (find how the repo validates it — a test, a script, or jsonschema directly) and confirm the whole file still parses.',
  '',
  '2. THE SELF-MODEL NODE. Run files/anatomy/scripts/keap_selfmodel_gen.py --schema slug and confirm Pulse now emits a node. Report its EXACT node id. If a stack-null row lands somewhere wrong or nowhere at all, fix the placement properly — do not paper over it by inventing a fake stack. The three existing host organs are the precedent for where a stack-null organ belongs; follow whatever they actually do.',
  '',
  '3. THE DOCS TREE. Author docs/systems/pulse/{README,AGENTS,SKILLS}.md to the same contract S1b used. Read ' + SCHEMA + ' for the ingestion contract (only those three filenames; **Trigger:** ⇒ skill, **When/If** ⇒ hint, fenced code ⇒ snippet, else note; every heading slug must start with a letter).',
  '   Ground every value in source: the launchd label, the runtime tree (~/pulse/{venv,state,log}), the tick interval and concurrency, the Wing API base and WHY it is loopback rather than through Traefik (the 302 storm is documented in the role defaults — that is a real hint, exactly the conditional kind), the shared wing_api_token, the Python interpreter split macOS/Linux, and how jobs are declared (plugin manifest pulse_jobs: blocks).',
  '   Pulse HAS a real skill surface (job registry, run reporting, the catalog) — but only write skills that genuinely exist and can be invoked; anything you cannot trace, omit. Use NO stale-scheme paths.',
  '',
  '4. Update every test assertion the consumers lens found pinned to the old denominator (62 → 63), and any that enumerate the manifest. Do not weaken an assertion to make it pass — move the number, keep the strength.',
  '',
  'Then run keap_docs_gen.py into an ISOLATED temp store and report: services_covered / services_missed by name / nodes-per-kind. Pulse must now be covered.',
].join('\n'), { label: 'build', phase: 'Build', effort: 'high' })

phase('Verify')

const VLENSES = [
  { key: 'row', prompt: 'Attack the MANIFEST ROW and the docs tree for wrongness. Hunt: a field whose value contradicts roles/pazny.pulse source; an invented health_check or port for a daemon that listens on nothing; a data_path_var naming a var that does not exist or resolves to the wrong tree; a launchd_label that does not match the plist; a category or version_source outside the schema enum; a docs card citing a path, token, interval or endpoint that source does not support; a stale-scheme path. Also check the Linux side is not silently claimed as macOS-only or vice versa.' },
  { key: 'blast', prompt: 'Attack the BLAST RADIUS of a 63rd row. Hunt a real regression in any manifest consumer: a Traefik router emitted for a service with no domain/port; a registry or tofu-registry entry that now carries nulls; a self-model node landing under a wrong or duplicated parent; a doc node id colliding with an existing node; a test whose assertion was weakened rather than moved; the docs coverage gate no longer able to distinguish full coverage from partial. Also verify the self-model node id the Build phase reported is genuinely what the generator emits, not what the agent believed it emits.' },
]

const verified = await pipeline(
  VLENSES,
  (l) => agent([RULES, '', 'Adversarial review of ' + BRANCH + ' (git diff against the pre-build commit). Real defects with concrete failure scenarios only.', l.prompt].join('\n'),
    { label: 'verify:' + l.key, phase: 'Verify', schema: FINDINGS, effort: 'high' }),
  (res, lens) => parallel(((res && res.findings) || [])
    .slice().sort((a, b) => (a.severity === b.severity ? 0 : a.severity === 'major' ? -1 : 1)).slice(0, 3)
    .map((f) => () => agent([RULES, '', 'READ-ONLY. Try to REFUTE this defect. Default to real=false unless you can trace it in the code.',
      'Title: ' + f.title, 'File: ' + f.file, 'Scenario: ' + f.failure_scenario].join('\n'),
      { label: 'refute:' + lens.key, phase: 'Verify', schema: VERDICT })
      .then((v) => ({ ...f, lens: lens.key, verdict: v })))),
)
const confirmed = verified.flat().filter(Boolean).filter((f) => f.verdict && f.verdict.real)
log('verify: ' + verified.flat().filter(Boolean).length + ' claimed, ' + confirmed.length + ' confirmed')

phase('Finalise')

const final = await agent([RULES, '',
  (confirmed.length
    ? 'FIRST fix these confirmed defects, each with a test that fails without the fix:\n' + confirmed.map((f, i) => (i + 1) + '. [' + f.severity + '] ' + f.title + ' — ' + f.file + '\n   ' + f.failure_scenario).join('\n\n')
    : 'No confirmed defects.'),
  '',
  'Then verify and report, with numbers:',
  '- pytest tests/anatomy/ (S1b baseline: 1977 passed, 3 skipped)',
  '- the organ vitest suite (baseline: 199 passed)',
  '- node knowledge/onto1-conformance.mjs under files/anatomy/cortex/ (baseline: 6/6)',
  '- ansible-playbook main.yml --syntax-check (the manifest is play-consumed; a malformed row must not break the play)',
  '- keap_selfmodel_gen.py + keap_docs_gen.py into a temp store: services_covered / services_missed BY NAME / nodes-per-kind, and Pulse node id.',
  '',
  'Then state plainly:',
  '- Is Pulse now inside the denominator (63/63), with a self-model node AND a doc-derived typed node?',
  '- Did anything regress? Name it.',
  '- What remains owed after this stage (debt 2 — the ~22 legacy trees with stale Data paths — is NOT in scope here; confirm it is untouched and still owed).',
  '',
  'Commit on ' + BRANCH + '. Report the sha and a clean tree. Do NOT merge to dev.',
].join('\n'), { label: 'finalise', phase: 'Finalise', effort: 'high' })

return {
  fields: facts.flatMap((g) => (g.fields || []).map((f) => ({ field: f.field, value: f.value }))),
  risks: facts.flatMap((g) => g.risks || []),
  build: typeof build === 'string' ? build.slice(0, 2000) : build,
  confirmed: confirmed.map((f) => ({ lens: f.lens, severity: f.severity, title: f.title })),
  final: typeof final === 'string' ? final.slice(0, 3000) : final,
}
