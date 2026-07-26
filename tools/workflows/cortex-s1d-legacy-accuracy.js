export const meta = {
  name: 'cortex-s1d-legacy-accuracy',
  description: 'S1d (debt 2) — reconcile the 22 legacy docs/systems trees against source before the corpus is embedded. Stale Data paths are the fee-04 confident-wrong failure.',
  whenToUse: 'After cortex-s1c-pulse-selfmodel. S1b authored 40 accurate trees but deliberately did not bulk-edit the 22 pre-existing ones, which still cite pre-nos_data_root paths that do not exist. Must close BEFORE S2 embeds the corpus.',
  phases: [
    { title: 'Ground', detail: 'the true Quick Reference for every legacy service, from source' },
    { title: 'Reconcile', detail: 'fix each tree per-service against its verified facts' },
    { title: 'Verify', detail: 'adversarial: wrong values, and edits that changed meaning' },
    { title: 'Finalise', detail: 'fix confirmed defects, regenerate, run every suite, commit' },
  ],
}

const NOS = '/Users/pazny/projects/nOS'
const BRANCH = 'feat/cortex-docs-knowledge'

const RULES = [
  'HARD CONSTRAINTS',
  '- Work in ' + NOS + ' on branch ' + BRANCH + '. NEVER touch main/dev, never tag, never release, never merge.',
  '- DO NOT DEPLOY: no ansible-playbook run, no converge, no docker restart, no container writes. --syntax-check is allowed; nothing that mutates the host is.',
  '- NEVER host-sqlite3 the live KEAP db. Generators run into an ISOLATED temp store only.',
  '- No new dependencies. tests/anatomy is pytest; the organ suite is vitest; both stay green.',
  '- Commit with a real message that says WHY.',
  '',
  'THE RULE THAT DEFINES THIS STAGE: NO BULK SED. Every path you change must be READ from that service own source — roles/pazny.<svc>/defaults/main.yml (the *_data_dir / *_storage_path var and its default), roles/pazny.<svc>/templates/compose.yml.j2 (the actual volume mount, left side of the colon), the service row in state/manifest.yml (data_path_var), and tasks/stacks/external-paths.yml if an external-storage override applies. A find-and-replace of ~/stacks/<stack>/<svc>/data to {{ nos_data_root }}/... would be a NEW confident-wrong value wherever the real path differs — and it does differ (named volumes, per-tenant trees, config-vs-data splits, services with no persistent data at all).',
  '',
  'WHAT IS AND IS NOT STALE — do not over-correct:',
  '- Config under ~/stacks/<stack>/ is CORRECT and current: stacks_dir really is ~/stacks and compose files really live there. Only the DATA row moved to nos_data_root. S1b verified this distinction; preserve it.',
  '- A Docker NAMED VOLUME (e.g. mariadb_data) is not a host path at all — say so, do not invent a bind mount.',
  '- Some services genuinely persist nothing (stateless BFF, an exporter with only a send-retry WAL). "none" is a true answer; do not manufacture a directory.',
  '- Data that lives in a DATABASE (a Postgres schema, not a volume) must say so.',
  '- The default. shown in parentheses should be the real default nos_data_root resolves to, not a guess.',
  '',
  'Fix what is wrong; leave what is right ALONE. A diff that touches a correct line is a regression, not a cleanup. If a value is already correct, say so and move on.',
].join('\n')

const GROUP = {
  type: 'object', additionalProperties: false, required: ['services'],
  properties: {
    services: { type: 'array', items: {
      type: 'object', additionalProperties: false, required: ['svc', 'rows'],
      properties: {
        svc: { type: 'string' },
        rows: { type: 'array', items: {
          type: 'object', additionalProperties: false, required: ['row', 'was', 'now', 'verdict', 'source'],
          properties: {
            row: { type: 'string', description: 'Quick Reference row: Data | URL | Port | Compose | Toggle | Image | other' },
            was: { type: 'string' }, now: { type: 'string' },
            verdict: { type: 'string', enum: ['stale-fixed', 'already-correct', 'unverifiable'] },
            source: { type: 'string', description: 'the file the true value was read from' },
          },
        } },
        otherFindings: { type: 'string', description: 'anything else wrong in the tree (dead endpoint, invented skill, stale SSO bucket)' },
      },
    } },
  },
}
const FINDINGS = {
  type: 'object', additionalProperties: false, required: ['findings'],
  properties: { findings: { type: 'array', items: {
    type: 'object', additionalProperties: false, required: ['svc', 'file', 'claim', 'truth', 'severity'],
    properties: { svc: { type: 'string' }, file: { type: 'string' }, claim: { type: 'string' }, truth: { type: 'string' }, severity: { type: 'string', enum: ['major', 'minor'] } },
  } } },
}
const VERDICT = { type: 'object', additionalProperties: false, required: ['real', 'why'], properties: { real: { type: 'boolean' }, why: { type: 'string' } } }

// The 22 pre-S1b trees + TEMPLATE. Sharded so each agent holds a coherent slice.
const SHARDS = [
  { key: 'infra-identity', svcs: ['authentik', 'infisical', 'portainer', 'bluesky-pds', 'vaultwarden'] },
  { key: 'iiab-media', svcs: ['calibre-web', 'jellyfin', 'kiwix', 'open-webui', 'home-assistant'] },
  { key: 'b2b-devops', svcs: ['erpnext', 'freescout', 'outline', 'gitea', 'wordpress'] },
  { key: 'data-obs', svcs: ['grafana', 'metabase', 'superset', 'rustfs', 'uptime-kuma'] },
  { key: 'core-template', svcs: ['n8n', 'nextcloud', 'TEMPLATE'] },
]

phase('Ground')

const grounded = await parallel(SHARDS.map((s) => () => agent([RULES, '',
  'RECONCILE these legacy doc trees against source: ' + s.svcs.join(', ') + '.',
  'These predate the nos_data_root scheme and were NOT touched by the S1b authoring pass, so their Quick Reference tables are the last place the stale scheme survives.',
  '',
  'For EACH service:',
  '1. Read docs/systems/<svc>/README.md (and AGENTS.md / SKILLS.md) and list every concrete claim in the Quick Reference table plus any path/endpoint/credential cited in prose.',
  '2. Establish the TRUE value of each from source: roles/pazny.<svc>/defaults/main.yml, roles/pazny.<svc>/templates/compose.yml.j2 (read the actual volumes: block), state/manifest.yml row (data_path_var, port_var, domain_var, image), files/anatomy/plugins/<svc>-base/plugin.yml (the authentik bucket + tier), and default.config.yml where the var is shadowed. Remember default.config.yml OUTRANKS a role default when both define the var.',
  '3. EDIT the file only where the claim and the truth disagree. Preserve the house format (the same table shape S1b matched). Where the service uses a named volume / a database / nothing, say exactly that.',
  '4. While you are in the file: flag (do not silently rewrite) any dead endpoint, invented skill, or SSO bucket that plugin.yml contradicts, and fix it if the true value is unambiguous from source.',
  '',
  (s.svcs.indexOf('TEMPLATE') >= 0
    ? 'NOTE on TEMPLATE: it is the pattern a future author copies. If it carries the stale scheme it reproduces this fee forever, so it matters more than any single service. Make it exemplary: the current data scheme, the config-vs-data distinction stated, and placeholders that are obviously placeholders rather than values that look real.'
    : ''),
  '',
  'Report every row you touched AND every row you verified as already-correct, each with the source file the truth came from. already-correct rows are evidence you checked rather than skipped.',
].join('\n'), { label: 'ground:' + s.key, phase: 'Ground', schema: GROUP, effort: 'high' })))

const recs = grounded.filter(Boolean).flatMap((g) => g.services || [])
const rows = recs.flatMap((r) => r.rows || [])
const fixed = rows.filter((r) => r.verdict === 'stale-fixed')
const ok = rows.filter((r) => r.verdict === 'already-correct')
const unver = rows.filter((r) => r.verdict === 'unverifiable')
log('ground: ' + recs.length + ' services, ' + fixed.length + ' rows fixed, ' + ok.length + ' already correct, ' + unver.length + ' unverifiable')

phase('Reconcile')

const sweep = await agent([RULES, '',
  'The five shard agents have reconciled the legacy trees. Their record:',
  JSON.stringify(recs, null, 1).slice(0, 8000),
  '',
  'Now do the cross-cutting pass no single shard could do:',
  '1. SWEEP the whole docs/systems tree for any REMAINING stale-scheme citation — grep for the pre-nos_data_root shapes across every README/AGENTS/SKILLS (all 63 services, not just the 22), and for any path that names a directory no role creates. Report what is left and fix what is unambiguous.',
  '2. RESOLVE the unverifiable rows if you can (' + unver.length + ' of them); if a value genuinely cannot be established from source, mark it explicitly in the doc rather than leaving a confident wrong value standing.',
  '3. CONSISTENCY: the same service must not be described one way in its README and another in its SKILLS/AGENTS. Check the trees the shards touched for internal contradictions.',
  '4. Confirm no correct line was collaterally rewritten: review git diff and justify any change to a row a shard marked already-correct.',
  '',
  'Then run keap_selfmodel_gen.py + keap_docs_gen.py into an ISOLATED temp store and report services_covered / services_missed by name / nodes-per-kind. Coverage must stay 63/63 — this stage changes doc CONTENT, not coverage; a drop means an edit broke a file.',
].join('\n'), { label: 'sweep', phase: 'Reconcile', effort: 'high' })

phase('Verify')

const VLENSES = [
  { key: 'wrongness', prompt: 'Attack the RECONCILED VALUES. Hunt a path/port/domain/image/toggle that still disagrees with roles/pazny.<svc>/defaults, the compose volumes: block, or the manifest row — in EITHER direction: a stale value left standing, OR a newly-written value that is wrong (the over-correction risk: a bind-mount path invented for a named volume; nos_data_root asserted for a service whose data really is elsewhere; a per-tenant tree flattened to platform/services; a config path rewritten as if it were data). Check the parenthesised default. actually matches what nos_data_root resolves to.' },
  { key: 'meaning', prompt: 'Attack the EDITS for changed meaning and collateral damage. Hunt: a row marked already-correct that the diff nonetheless rewrote; a true distinction destroyed (config-under-stacks vs data-under-nos_data_root collapsed into one; a named volume described as a host path; "no persistent data" replaced by an invented directory); a doc whose markdown structure the edit broke so a section no longer parses to its intended kind (Trigger/When/fence signals lost, headings renamed so node ids churn); TEMPLATE left carrying the stale pattern. Also verify coverage really is still 63/63 and no file was corrupted.' },
]

const verified = await pipeline(
  VLENSES,
  (l) => agent([RULES, '', 'Adversarial review of the legacy-reconciliation diff on ' + BRANCH + '. Real defects with concrete failure scenarios only.', l.prompt].join('\n'),
    { label: 'verify:' + l.key, phase: 'Verify', schema: FINDINGS, effort: 'high' }),
  (res, lens) => parallel(((res && res.findings) || [])
    .slice().sort((a, b) => (a.severity === b.severity ? 0 : a.severity === 'major' ? -1 : 1)).slice(0, 3)
    .map((f) => () => agent([RULES, '', 'READ-ONLY. Try to REFUTE. Default to real=false unless you can trace BOTH the doc claim and the true value in source.',
      'Service: ' + f.svc, 'File: ' + f.file, 'Claim: ' + f.claim, 'Alleged truth: ' + f.truth].join('\n'),
      { label: 'refute:' + lens.key, phase: 'Verify', schema: VERDICT })
      .then((v) => ({ ...f, lens: lens.key, verdict: v })))),
)
const confirmed = verified.flat().filter(Boolean).filter((f) => f.verdict && f.verdict.real)
log('verify: ' + verified.flat().filter(Boolean).length + ' claimed, ' + confirmed.length + ' confirmed')

phase('Finalise')

const final = await agent([RULES, '',
  (confirmed.length
    ? 'FIRST fix these confirmed defects:\n' + confirmed.map((f, i) => (i + 1) + '. [' + f.severity + '] ' + f.svc + '/' + f.file + ' claims "' + f.claim + '" — truth: ' + f.truth).join('\n')
    : 'No confirmed defects.'),
  '',
  'Then verify and report with numbers:',
  '- pytest tests/anatomy/ (baseline 1977 passed, 3 skipped — the count may legitimately rise if this stage added gates)',
  '- the organ vitest suite (baseline 199 passed)',
  '- node knowledge/onto1-conformance.mjs under files/anatomy/cortex/ (baseline 6/6)',
  '- both generators into a temp store: services_covered / services_missed BY NAME / nodes-per-kind',
  '',
  'CONSIDER adding a gate that keeps this closed: a pytest that greps docs/systems for the stale path shapes and fails if one reappears. Debt 2 existed because nothing pinned it. If you add it, make it precise enough not to fire on a legitimately-correct ~/stacks CONFIG reference.',
  '',
  'Then state plainly:',
  '- How many legacy trees carried a stale value, how many rows were corrected, how many were already right.',
  '- Is the S1 exit criterion "no card cites a path that does not exist" NOW met across all 63 services? If any card still cannot be verified, name it and say why.',
  '- Is the corpus safe to embed in S2 with respect to fee-04 confident-wrongness? Answer honestly; if there is residual risk, name it.',
  '',
  'Commit on ' + BRANCH + '. Report the sha and a clean tree. Do NOT merge to dev.',
].join('\n'), { label: 'finalise', phase: 'Finalise', effort: 'high' })

return {
  servicesTouched: recs.map((r) => ({ svc: r.svc, fixed: (r.rows || []).filter((x) => x.verdict === 'stale-fixed').length, ok: (r.rows || []).filter((x) => x.verdict === 'already-correct').length })),
  rowsFixed: fixed.length, rowsAlreadyCorrect: ok.length, rowsUnverifiable: unver.length,
  sweep: typeof sweep === 'string' ? sweep.slice(0, 1800) : sweep,
  confirmed: confirmed.map((f) => ({ svc: f.svc, severity: f.severity, claim: f.claim, truth: f.truth })),
  final: typeof final === 'string' ? final.slice(0, 3000) : final,
}
