export const meta = {
  name: 'cortex-s1b-docs-backfill',
  description: 'S1b — author docs/systems/ trees for the 40 undocumented services, grounded in ground truth, so docs-become-knowledge covers the estate.',
  whenToUse: 'After cortex-s1-docs-as-knowledge. S1 built the ingestion machinery and measured 22/62 coverage; this closes the 40-service gap that S1 left as debt. Writes on the same branch.',
  phases: [
    { title: 'Recheck', detail: 'confirm the branch, schema, generator and the real missed-by-name set' },
    { title: 'Author', detail: 'one agent per stack-group writes README/AGENTS/SKILLS from ground truth' },
    { title: 'Ingest', detail: 'run the generator, assert coverage rose, report new missed-by-name' },
    { title: 'Accuracy', detail: 'adversarial: hunt any card citing a path/port/domain that does not exist' },
    { title: 'Finalise', detail: 'fix confirmed wrong cards, re-run gen + tests, commit' },
  ],
}

const NOS = '/Users/pazny/projects/nOS'
const PLAN = NOS + '/docs/plans/cortex-self-core.md'
const SCHEMA = NOS + '/docs/plans/cortex-docs-schema.md'
const BRANCH = 'feat/cortex-docs-knowledge'

const RULES = [
  'HARD CONSTRAINTS',
  '- Work in ' + NOS + ' on branch ' + BRANCH + '. NEVER touch main/dev, never tag, never release.',
  '- DO NOT DEPLOY: no ansible, no converge, no docker restart, no container writes. Read the repo, not the live estate.',
  '- NEVER host-sqlite3 the live KEAP db. You do not need the organ running to author docs; if you must ingest, do it against a COPY/temp store only.',
  '- No new dependencies. The organ package-lock.json stays untouched. tests/anatomy is pytest; the organ suite is vitest; both stay green.',
  '- Commit each phase with a real message that says WHY.',
  '',
  'ACCURACY IS THE PRODUCT, NOT COVERAGE. The fee this pays down (docs/hidden_fees/04) is that a router returning a CONFIDENT WRONG endpoint sends an agent to act on stale information — strictly worse than a missing doc. Therefore:',
  '- Every fact you write (toggle/install flag, port, domain, data path, image tag, SSO bucket, admin user, health endpoint) MUST be read from the ACTUAL source: roles/pazny.<svc>/defaults/main.yml, roles/pazny.<svc>/templates/compose.yml.j2, files/anatomy/plugins/<svc>-base/plugin.yml, and the service row in state/manifest.yml. NEVER copy values from the existing docs/systems/grafana exemplar — its "grafana.dev.local" + "~/stacks/..." are the STALE scheme (fee 04). The current scheme is nos_data_root (default /Volumes/SSD1TB/nOS/data or the role default) and a derived tenant domain, NOT hardcoded dev.local.',
  '- If a service has NO invocable surface (a database, a cache, a library, a proxy with no user API), DO NOT invent skills or Triggers. Write an honest SKILLS.md that states there is no external skill surface and why. An invented endpoint is the exact failure we are removing.',
  '- If you cannot verify a fact from source, OMIT it or mark it TODO — never guess a value and present it as real.',
].join('\n')

// The schema contract the generator parses (docs/plans/cortex-docs-schema.md +
// files/anatomy/scripts/keap_docs_gen.py). Passed to every author so the docs ingest.
const CONTRACT = [
  'INGESTION CONTRACT (docs/plans/cortex-docs-schema.md; parsed by files/anatomy/scripts/keap_docs_gen.py):',
  '- Only three filenames ingest: README.md, AGENTS.md, SKILLS.md. Author exactly these under docs/systems/<svc>/.',
  '- Optional leading frontmatter (----fenced flat scalars) with type: skill|hint|note|snippet sets the file default; absent ⇒ note.',
  '- Block level, per heading section, priority Trigger > When/If > fenced-code > file-default:',
  '    a **Trigger:** bold-lead line ⇒ that section is a SKILL (invocable; the recall gate is built from Trigger phrases)',
  '    a **When ...** / **If ...** bold-lead line ⇒ HINT (true only under a condition)',
  '    a fenced code block ⇒ SNIPPET (correct only byte-for-byte; tag the language)',
  '    anything else under a heading ⇒ NOTE (a standing claim)',
  '- Every heading becomes a node id segment via slug_or_die: ascii, lowercase, must start with a LETTER (no leading digit), [a-z][a-z0-9-]*. A heading like "7-zip" dies loudly — spell it "sevenzip-...".',
  '- Do NOT repeat identical heading TEXT within one file gratuitously (the generator ordinal-namespaces repeats, but keep headings distinct for clean ids).',
  '- Match the STRUCTURE of docs/systems/grafana (README: a Quick Reference table + Authentication + API/Health + Dependencies; SKILLS: **Trigger:**-led action sections; AGENTS: a short agent definition) — but every VALUE must be the current, verified one.',
].join('\n')

const GROUP_RESULT = {
  type: 'object', additionalProperties: false, required: ['services'],
  properties: {
    services: { type: 'array', items: {
      type: 'object', additionalProperties: false, required: ['svc', 'anchored', 'files', 'skillSurface'],
      properties: {
        svc: { type: 'string' },
        anchored: { type: 'boolean', description: 'true if it has a real manifest node_id nos.<stack>.<system> to hang off' },
        anchorNote: { type: 'string', description: 'if not anchored, why (no manifest row / non-docker host organ / id-form mismatch) and what the real id is' },
        files: { type: 'array', items: { type: 'string' }, description: 'doc files written' },
        skillSurface: { type: 'string', enum: ['skills', 'none'], description: 'skills = has invocable actions; none = honestly no external skill surface' },
        keyFacts: { type: 'string', description: 'the verified port/domain/data-path/toggle/SSO you grounded on, with where each came from' },
      },
    } },
  },
}
const FINDINGS = {
  type: 'object', additionalProperties: false, required: ['findings'],
  properties: { findings: { type: 'array', items: {
    type: 'object', additionalProperties: false, required: ['svc', 'file', 'claim', 'truth', 'severity'],
    properties: {
      svc: { type: 'string' }, file: { type: 'string' },
      claim: { type: 'string', description: 'the exact wrong value the card asserts' },
      truth: { type: 'string', description: 'the real value, and the source file it is read from' },
      severity: { type: 'string', enum: ['major', 'minor'] },
    },
  } } },
}
const VERDICT = { type: 'object', additionalProperties: false, required: ['real', 'why'], properties: { real: { type: 'boolean' }, why: { type: 'string' } } }

phase('Recheck')
await agent([RULES, '',
  'Confirm the ground this stage stands on before any authoring:',
  '- You are on ' + BRANCH + ' and ' + SCHEMA + ' exists (S1 Design). Read it.',
  '- Read ' + NOS + '/docs/archive/cortex-s0-report.md and ' + NOS + '/docs/plans/cortex-s1-report.md (or the S1 workflow result) so you inherit S1 rather than re-derive it.',
  '- Regenerate the TRUE missed-by-name set: run files/anatomy/scripts/keap_docs_gen.py against state/manifest.yml (against a temp/throwaway store or its dry survey mode — do NOT disturb a running organ) and report services_covered / services_missed BY NAME. The plan says 22/62 covered.',
  '- For the six names that did not resolve to a manifest row earlier (code-server, iiab-terminal, mcp-gateway, offline-maps, qgis-server, smtp-stalwart): find their REAL manifest id (id-form may differ, e.g. mcpo, stalwart) OR confirm they are non-docker host organs with no manifest node. State, per name, whether a docs/systems tree will actually ingest, so Author does not write orphans.',
  'Report the corrected group list. If the branch or schema is absent, STOP.',
].join('\n'), { label: 'recheck', phase: 'Recheck', effort: 'medium' })

phase('Author')
// Stack-coherent groups covering all 40. Services in a group share infra facts.
const GROUPS = [
  { key: 'observability', svcs: ['alloy', 'loki', 'prometheus', 'tempo'] },
  { key: 'infra', svcs: ['mariadb', 'postgresql', 'redis', 'traefik'] },
  { key: 'organs-core', svcs: ['bone', 'wing', 'cortex'] },
  { key: 'organs-agents', svcs: ['openclaw', 'opencode', 'hermes', 'iiab-terminal'] },
  { key: 'b2b', svcs: ['bookstack', 'firefly', 'hedgedoc', 'onlyoffice'] },
  { key: 'devops', svcs: ['gitlab', 'woodpecker', 'paperclip', 'code-server'] },
  { key: 'iiab-a', svcs: ['face', 'keap', 'miniflux', 'nodered'] },
  { key: 'iiab-b', svcs: ['ntfy', 'snappymail', 'mailpit', 'watchtower'] },
  { key: 'data-voip-vpn', svcs: ['influxdb', 'freepbx', 'tailscale'] },
  { key: 'storage-misc', svcs: ['backrest', 'backup', 'offline-maps', 'qgis-server', 'mcp-gateway', 'smtp-stalwart'] },
]
const authored = await parallel(GROUPS.map((g) => () => agent([RULES, '', CONTRACT, '',
  'Author the docs/systems/<svc>/ trees for these services: ' + g.svcs.join(', ') + '.',
  'For EACH service, in this order:',
  '1. GATHER GROUND TRUTH from source only: roles/pazny.<svc>/defaults/main.yml (version, *_port, *_data_dir/data_path, mem_limit, admin user), roles/pazny.<svc>/templates/compose.yml.j2 (image, real published ports, real mounts), files/anatomy/plugins/<svc>-base/plugin.yml (authentik bucket+tier: native_oidc/header_oidc/forward_auth/none; notification; requires), and the row in state/manifest.yml (id, stack, install_flag, data_path_var, port_var, health_check). Host organs (bone, wing, cortex, hermes, openclaw, opencode, iiab-terminal) are NOT docker — ground them in their launchd plist / systemd unit and source under files/anatomy/<organ>/ or roles/pazny.<organ>/; they are loopback daemons, usually no domain and no SSO.',
  '2. VERIFY THE ANCHOR: the service needs a real manifest node_id nos.<stack>.<system> or the docs will not ingest. If it has no manifest row, say so in anchorNote and still author the tree (it is ready for when the row lands) but flag anchored=false.',
  '3. WRITE README.md, AGENTS.md, SKILLS.md following the CONTRACT and the grafana STRUCTURE — with VERIFIED values only. README carries the real toggle, port, data path (nos_data_root scheme, not ~/stacks), derived domain, image, SSO bucket, health endpoint. SKILLS.md: only real invocable actions with real endpoints/commands and honest **Trigger:** phrases; if the service has no external skill surface (redis/postgres/mariadb caches+DBs, a pure proxy, a library), write that plainly instead of inventing skills (skillSurface=none). AGENTS.md: a short, accurate agent definition.',
  '4. Do not fabricate. Omit or TODO any fact you cannot read from source.',
  'Return the per-service record. keyFacts must name where each grounded value came from so Accuracy can check you.',
].join('\n'), { label: 'author:' + g.key, phase: 'Author', schema: GROUP_RESULT, effort: 'high' })))

const recs = authored.filter(Boolean).flatMap((a) => a.services || [])
const wrote = recs.filter((r) => (r.files || []).length)
const orphans = recs.filter((r) => r.anchored === false)
log('author: ' + wrote.length + ' services written, ' + orphans.length + ' flagged not-anchored')

phase('Ingest')
const ingest = await agent([RULES, '',
  'All 40 doc trees are now authored on the branch. Run the ingestion the same way S1 did and report coverage AS DATA:',
  '- Run files/anatomy/scripts/keap_docs_gen.py against state/manifest.yml into an ISOLATED temp store (never the live organ). Report: services_covered (was 22), services_missed BY NAME (should shrink toward the non-docker set), nodes-per-kind (skill/hint/note/snippet), and services_empty / docs_ignored if the generator reports them.',
  '- Confirm no service that was authored is silently dropped: cross-check the written set against services_covered; any authored-but-not-covered service is a real defect — name it and diagnose (missing anchor? ingest error? filename typo?).',
  '- Confirm the generator does not crash and the S1 fixes (repeated-heading, ordinal, allowlist, provenance, coverage-from-store) still hold.',
  'Report the numbers plainly. Do NOT print a bare percentage; give measured/total and the named remainder.',
].join('\n'), { label: 'ingest', phase: 'Ingest', effort: 'high' })

phase('Accuracy')
// Split the authored services into 3 adversarial shards. Each hunts confident-wrong cards.
const shards = [[], [], []]
wrote.forEach((r, i) => shards[i % 3].push(r.svc))
const claimed = await parallel(shards.map((svcs, i) => () => agent([RULES, '',
  'ADVERSARIAL ACCURACY REVIEW (this is the fee we are paying down). For these authored services: ' + svcs.join(', ') + '.',
  'For each, open docs/systems/<svc>/{README,AGENTS,SKILLS}.md and check EVERY concrete value against source (roles/pazny.<svc>/defaults + compose.yml.j2 + plugin.yml + manifest row). Hunt specifically for:',
  '- a port, domain, image tag, data path, install flag, admin user, or health endpoint that does NOT match the role/compose/plugin (the confident-wrong endpoint);',
  '- the STALE scheme leaking in: any ~/stacks/<svc>/ path or a hardcoded *.dev.local domain that the current nos_data_root / derived-domain scheme contradicts;',
  '- an invented **Trigger:**/skill for a service that has no such API or command;',
  '- an SSO bucket claim (native_oidc/header_oidc/forward_auth/none) that disagrees with plugin.yml.',
  'Report real defects only, each with the exact claim, the true value, and the source file it is read from. Minor = cosmetic/stale-but-harmless; major = would send an agent to a wrong endpoint.',
].join('\n'), { label: 'accuracy:' + i, phase: 'Accuracy', schema: FINDINGS, effort: 'high' })))

const rawFindings = claimed.filter(Boolean).flatMap((c) => c.findings || [])
// refute the majors before spending a fix on them
const majors = rawFindings.filter((f) => f.severity === 'major').slice(0, 6)
const verified = await parallel(majors.map((f) => () => agent([RULES, '',
  'READ-ONLY. Try to REFUTE this accuracy defect. Default to real=false unless you can trace BOTH the wrong claim in the doc AND the true value in source.',
  'Service ' + f.svc + ', file ' + f.file + '. Claim: ' + f.claim + '. Alleged truth: ' + f.truth,
].join('\n'), { label: 'refute', phase: 'Accuracy', schema: VERDICT })
  .then((v) => ({ ...f, verdict: v }))))
const confirmed = verified.filter(Boolean).filter((f) => f.verdict && f.verdict.real)
const minors = rawFindings.filter((f) => f.severity === 'minor')
log('accuracy: ' + rawFindings.length + ' claimed, ' + confirmed.length + ' major confirmed, ' + minors.length + ' minor')

phase('Finalise')
const final = await agent([RULES, '',
  (confirmed.length
    ? 'FIRST fix these CONFIRMED wrong cards, each with the true value from source:\n' + confirmed.map((f, i) => (i + 1) + '. [' + f.svc + '/' + f.file + '] claims "' + f.claim + '" — truth: ' + f.truth).join('\n') + '\nAlso sweep the minor findings (' + minors.length + ') and fix the trivially-correctable stale values.'
    : 'No confirmed major accuracy defects. Sweep the ' + minors.length + ' minor findings and fix the stale ones.'),
  '',
  'Then:',
  '- Re-run keap_docs_gen.py into a temp store; report FINAL services_covered / missed-by-name / nodes-per-kind.',
  '- Run: pytest tests/anatomy/, the organ vitest suite, and node knowledge/onto1-conformance.mjs. Report numbers; all must stay green.',
  '- State the S1 exit criterion against reality now: how many of the 62 installed services have a doc-derived typed node, which remain missed and why (non-docker host organ / no manifest row), and whether any card still cites a path that does not exist.',
  '- Commit the authored trees + fixes on ' + BRANCH + ' with a WHY message. Report the commit shas and the clean tree.',
  'Be honest about residual debt: name every service still uncovered and the reason, rather than rounding up to "done".',
].join('\n'), { label: 'finalise', phase: 'Finalise', effort: 'high' })

return {
  authored: wrote.map((r) => ({ svc: r.svc, anchored: r.anchored, skillSurface: r.skillSurface, files: (r.files || []).length })),
  notAnchored: orphans.map((r) => ({ svc: r.svc, why: r.anchorNote })),
  ingest: typeof ingest === 'string' ? ingest.slice(0, 1500) : ingest,
  accuracyConfirmed: confirmed.map((f) => ({ svc: f.svc, file: f.file, claim: f.claim, truth: f.truth })),
  minorCount: minors.length,
  final: typeof final === 'string' ? final.slice(0, 3000) : final,
}
