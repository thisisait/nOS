export const meta = {
  name: 'release-readiness-v010',
  description: 'Production-readiness review of nOS and KEAP, scoped to what stands between today and nOS v0.10 cut from master.',
  whenToUse: 'Before planning the v0.10 release. Answers what must be true, not what would be nice — and separates release blockers from debt that can ship.',
  phases: [
    { title: 'Survey', detail: 'six dimensions, measured against the live repos' },
    { title: 'Judge', detail: 'blocker or debt, per finding, adversarially' },
    { title: 'Report', detail: 'one ordered path to v0.10' },
  ],
}

const NOS = '/Users/pazny/projects/nOS'
const KEAP = '/Users/pazny/projects/knowledge-explorer-and-preserver'

const RULES = [
  'HARD CONSTRAINTS — this review is READ-ONLY. It measures and judges; it changes nothing.',
  '- NO writes to either repo. No commits, no branches, no tags, no file edits outside a scratch dir.',
  '- NO deploy: no ansible-playbook run, no converge, no docker restart, no launchctl, no container writes.',
  '  A syntax-check or a --list-tasks is fine; anything that mutates the host or a store is not.',
  '- NEVER host-sqlite3 the live KEAP db (vector-indexed libSQL). Probe IN-CONTAINER with node, readonly:',
  '    docker exec iiab-keap-1 node -e "const D=require(\'/app/node_modules/libsql\'); const db=new D(\'/data/keap.db\',{readonly:true}); ..."',
  '  Wing\'s ~/wing/app/data/wing.db is plain SQLite and safe to read read-only.',
  '- NOTE a documented trap: KEAP server/agent.ts and server/intake.ts are detected as binary by file(1),',
  '  so GNU grep silently returns NOTHING on them. Use awk/sed. A zero count from grep on those two files',
  '  is not evidence of absence.',
  '',
  'REPORT NUMBERS WITH THE COMMAND THAT PRODUCED THEM. An unsourced number is not a measurement.',
  'If something cannot be measured, SAY SO. A confident wrong number is worse than a stated gap here,',
  'because the release plan will be built on these.',
  '',
  'THE STANDARD THIS REVIEW APPLIES — it is the estate\'s own, in docs/doctrine/gates.md:',
  '"a check that cannot fail is not a check". Three such were found by hand on 2026-07-27 alone:',
  'a doctrine guard keyed on an env var nothing sets; a coverage gate reading a generator\'s stdout',
  'instead of the store; and an id-diff that manufactured divergence from two truncated pages.',
  'Assume there are more. A green suite is evidence only about the checks that can go red.',
].join('\n')

const FINDINGS = {
  type: 'object', additionalProperties: false, required: ['summary', 'findings'],
  properties: {
    summary: { type: 'string' },
    findings: {
      type: 'array',
      items: {
        type: 'object', additionalProperties: false,
        required: ['title', 'evidence', 'severity', 'kind', 'where'],
        properties: {
          title: { type: 'string' },
          evidence: { type: 'string', description: 'the measurement + the command that produced it' },
          severity: { type: 'string', enum: ['blocker', 'should-fix', 'debt'] },
          kind: { type: 'string', enum: ['correctness', 'security', 'process', 'decorative-gate', 'incomplete-feature', 'doc-vs-code'] },
          where: { type: 'string', description: 'repo + path' },
          cost: { type: 'string', description: 'rough effort to close, in hours or days' },
        },
      },
    },
  },
}
const VERDICT = {
  type: 'object', additionalProperties: false, required: ['isBlocker', 'why'],
  properties: { isBlocker: { type: 'boolean' }, why: { type: 'string' }, downgradeTo: { type: 'string' } },
}

phase('Survey')

const DIMENSIONS = [
  {
    key: 'merge-to-master',
    prompt: [
      'DIMENSION 1 — the release is cut from master, and master is six releases behind.',
      '',
      'Measured: master is at v0.3-beta, dev is 791 commits ahead, dev has 52 commits unpushed to origin.',
      'The tag v0.9-beta is an ancestor of dev, not of master. CLAUDE.md describes a three-tier flow',
      '(feat -> dev -> master, master PR-only and fast-forward-only) revived 2026-05-17.',
      '',
      'Establish, from the repo rather than from the doctrine:',
      '- Has ANY dev -> master merge happened since the three-tier flow was revived? Date the last one.',
      '  If none, the flow is aspirational and the release plan cannot assume it works.',
      '- Is master a fast-forward from dev today, or have they diverged? If diverged, what is on master',
      '  that is not on dev, and does it matter?',
      '- Is the server-side branch protection CLAUDE.md describes actually configured? It says to verify',
      '  with `gh api repos/:owner/:repo/branches/master/protection` and that a 404 means unprotected.',
      '  Run the read-only check; do NOT change any setting.',
      '- What does the merge actually require — a PR with admin bypass (memory nos-release-flow says a',
      '  sole operator cannot self-approve), a green CI, or both? Name the exact commands.',
      '- What is the risk of a 791-commit merge landing at once, and what would reduce it?',
      'This dimension decides whether v0.10 is one afternoon or one week.',
    ].join('\n'),
  },
  {
    key: 'the-named-red',
    prompt: [
      'DIMENSION 2 — v0.9-beta shipped with a named red, and v0.10 drops the -beta.',
      '',
      'RELEASE.md section "Known red at cut time — the Linux wet-test" states that',
      'Integration (ubuntu-24.04) is RED and the tag shipped anyway: stacks/infra/docker-compose.yml',
      'is not rendered on Linux, docker compose up infra returns rc=1, and the STRICT health probe',
      'passed the resulting EMPTY stack as 0/0 ready. CLAUDE.md repeats it and points at',
      'docs/hidden_fees/08. That last part is the worst of it — the gate did not merely fail to catch',
      'the defect, it reported success over nothing.',
      '',
      'Establish:',
      '- Is it still red? Read .github/workflows/ci.yml and the most recent run status you can reach',
      '  WITHOUT triggering one (gh run list is read-only and fine).',
      '- What exactly does it take to make the Linux job PROVE the playbook: what does not render, why,',
      '  and is that a Linux port gap or a test-harness gap?',
      '- The 0/0-ready hole: has the STRICT probe been fixed so an empty stack fails? Read',
      '  files/anatomy/scripts/stack-health-probe.py and say whether a zero-container stack can still',
      '  pass. If it can, that is a decorative gate on the critical path.',
      '- Can a release drop -beta while its only cross-platform wet-test does not prove the playbook?',
      '  Answer it as a judgement with reasons, not a preference.',
    ].join('\n'),
  },
  {
    key: 'decorative-gates',
    prompt: [
      'DIMENSION 3 — hunt gates that cannot fail. This is the highest-yield dimension.',
      '',
      'The estate has ~2075 pytest tests, an organ vitest suite, and KEAP\'s own. A green suite is',
      'evidence only about checks that CAN go red. Three decorative ones were found by hand in a single',
      'day (see the standard quoted above), which is not a rate that suggests they are rare.',
      '',
      'Hunt in both repos for:',
      '- assertions over a value the test itself computed, or over a constant;',
      '- a gate that greps for a string that would still be present if the behaviour were reverted;',
      '- a probe whose failure path is swallowed (failed_when: false, try/except pass, || true) on a',
      '  path where the failure is the thing being tested;',
      '- a coverage/parity number read from a producer\'s own output rather than from the store or the',
      '  live system it claims to describe;',
      '- a test skipped by a condition that is always true in CI (network absent, docker absent, a file',
      '  that never exists), so it has never actually run;',
      '- an Ansible task whose changed_when/failed_when makes it structurally incapable of reporting a',
      '  problem.',
      'For each, state what would have to break for it to go red — if the answer is "nothing", it is a',
      'finding. Pick the ones that guard something that matters; do not pad the list with trivia.',
    ].join('\n'),
  },
  {
    key: 'security-and-fees',
    prompt: [
      'DIMENSION 4 — what in the security queue and the fee ledger blocks a non-beta release.',
      '',
      'Measured: docs/llm/security/remediation-queue.json holds 114 resolved, 10 pending,',
      '5 vendor-blocked, 3 wontfix, 1 obsolete. docs/hidden_fees/ holds 14 entries.',
      '',
      'Establish:',
      '- The 10 pending: name each, its CVSS/severity, whether it is reachable in the default profile',
      '  (not the all-on profile), and whether it blocks a release or ships as documented risk.',
      '- The 5 vendor-blocked: is the risk still accepted, and is the acceptance written down where a',
      '  user would see it rather than only in the queue?',
      '- The 14 fees: which are release-blocking, which are honest debt. docs/hidden_fees/README.md',
      '  states the entry test; apply it rather than inventing one.',
      '- Is the drift baseline stale? CLAUDE.md flags docs/llm/security/scan-state.json last_full_scan',
      '  drifting past 14 days as a known issue. Read the date and say.',
      '- A non-beta release makes an implicit promise a beta does not. Say plainly which of these items',
      '  breaks that promise.',
    ].join('\n'),
  },
  {
    key: 'cortex-completion',
    prompt: [
      'DIMENSION 5 — the operator has made cortex completion a RELEASE GATE: v0.10 waits until the',
      'cortex organ is genuinely finished, "including cortex-lang".',
      '',
      'Measured by hand: the organ ships cortex-lang.ts, cortex-opcodes.ts (18 opcodes),',
      'cortex-validate.ts, cortex-resolve.ts — the TYPECHECKER. There is no Wing executor:',
      'files/anatomy/wing/app/Cortex/ does not exist and AgentKit carries no cortex references.',
      'So a program can be validated and nothing can dispatch it. The executor was designed in',
      'docs/archive/nos-cortex-lang-wing-executor.md and PR-1 was deliberately HELD.',
      '',
      'Establish, precisely, what "finished" has to mean:',
      '- Inventory what is built vs specified across BOTH repos: lexer/parser/AST, opcode registry,',
      '  the validate route, resolution of each operand namespace (tax:, rel:, kg:, ent:, db:, svc:, doc:),',
      '  the emitter (structured tool-schema AST), the executor, the kNN replay/confidence gate.',
      '  docs/archive/nos-cortex-lang.md is the spec; measure the code against it.',
      '- ent: and kg: are REFUSED today. docs/archive/cortex-self-core.md 8.1 says caller identity is',
      '  aspirational and the organ contains zero Bone/JWKS/Authentik references — and that S0 did NOT',
      '  re-verify it. Confirm or refute against the code NOW, and say whether identity is a v0.10 gate',
      '  or a later one.',
      '- The S2 stage left an exit criterion of three consecutive nights of corpus agreement, with zero',
      '  nights elapsed and the captures clause capped until a KEAP release lands. State how that',
      '  interacts with a v0.10 date.',
      '- Then answer the question the operator actually asked: what is the SHORTEST honest definition of',
      '  "the cortex organ is done" that a release can stand on — and what is merely desirable after it.',
    ].join('\n'),
  },
  {
    key: 'keap-v2-and-contracts',
    prompt: [
      'DIMENSION 6 — KEAP v2 is "KEAP as data only", and it is explicitly NOT urgent. Interim tags are',
      'welcome, mainly so the two systems can be shown to work together for the nOS release.',
      '',
      'Establish:',
      '- What data-only concretely means, measured: docs/archive/cortex-self-core.md S5 says KEAP\'s server',
      '  and UI are deleted and its release train becomes dataset versioning. Count what would have to',
      '  move: server routes still corpus-facing, the UI\'s corpus routes, and server/cortex-*.ts, which',
      '  hidden_fees/11 says is duplicated between the repos today.',
      '- The cross-repo contracts that must hold for ANY interim tag: server/db.ts is byte-identical',
      '  between the repos (verify it still is), the onto1 digest agreement, the opcode registry hash,',
      '  and the keap_repo_ref pin. What breaks a tag silently?',
      '- v1.36.0 is tagged LOCALLY only and the pin was rolled back to v1.35.0 because the role clones',
      '  from the public GitHub remote. Say what the publish path is and what it costs, without',
      '  recommending that anything be pushed — that decision is the operator\'s.',
      '- Propose a MINIMAL interim-tag cadence that de-risks the nOS release: what each tag must prove',
      '  about interop, and what test proves it. Small and provable beats comprehensive.',
    ].join('\n'),
  },
]

const surveyed = await parallel(DIMENSIONS.map((d) => () =>
  agent([RULES, '', d.prompt].join('\n'),
    { label: 'survey:' + d.key, phase: 'Survey', schema: FINDINGS, effort: 'high' })))

const all = surveyed.filter(Boolean)
const findings = all.flatMap((s) => (s.findings || []).map((f) => ({ ...f })))
const claimed = findings.filter((f) => f.severity === 'blocker')
log('survey: ' + findings.length + ' findings, ' + claimed.length + ' claimed as blockers')

phase('Judge')

// Only blockers get adversarial review: a wrongly-claimed blocker costs the
// release a week, and a wrongly-demoted one ships a defect. Both directions are
// argued, so the verdict is not a rubber stamp on the surveyor's own framing.
const judged = await parallel(claimed.slice(0, 10).map((f) => () =>
  agent([RULES, '',
    'ADVERSARIAL JUDGEMENT of one claimed RELEASE BLOCKER for nOS v0.10 (a NON-beta release cut from master).',
    '',
    'Claim  : ' + f.title,
    'Where  : ' + f.where,
    'Evidence: ' + f.evidence,
    'Kind   : ' + f.kind,
    '',
    'Argue BOTH sides against the code, then decide:',
    '- For: what breaks for a user, or what promise a non-beta release makes that this defeats?',
    '- Against: is it pre-existing and already shipped in a beta, is it out of the default profile,',
    '  is it documented risk the operator has already accepted, is it debt rather than breakage?',
    'Return isBlocker=false unless you can name the concrete failure a v0.10 user would hit. When you',
    'downgrade, say to what (should-fix or debt). Verify the evidence yourself — a claim you could not',
    'reproduce is not a blocker no matter how plausible it reads.',
  ].join('\n'),
    { label: 'judge', phase: 'Judge', schema: VERDICT, effort: 'high' })
    .then((v) => ({ ...f, verdict: v }))))

const confirmed = judged.filter(Boolean).filter((j) => j.verdict && j.verdict.isBlocker)
const demoted = judged.filter(Boolean).filter((j) => j.verdict && !j.verdict.isBlocker)
log('judge: ' + confirmed.length + ' blockers survived, ' + demoted.length + ' demoted')

phase('Report')

const report = await agent([RULES, '',
  'Write the readiness review to ' + NOS + '/docs/archive/release-readiness-v010.md.',
  'This ONE file write is permitted; nothing else.',
  '',
  'Survey (six dimensions):',
  JSON.stringify(all, null, 1).slice(0, 14000),
  '',
  'Blockers that survived adversarial judgement:',
  JSON.stringify(confirmed.map((c) => ({ title: c.title, where: c.where, why: c.verdict.why, cost: c.cost })), null, 1).slice(0, 5000),
  '',
  'Claims that were DEMOTED, with the reason:',
  JSON.stringify(demoted.map((d) => ({ title: d.title, to: d.verdict.downgradeTo, why: d.verdict.why })), null, 1).slice(0, 4000),
  '',
  'THE TARGET, stated by the operator and not to be re-negotiated:',
  '- nOS v0.10, NO beta suffix, cut from MASTER after the full dev->master merge passes.',
  '- The release waits until the cortex organ is genuinely finished, INCLUDING cortex-lang.',
  '- KEAP v2 = data-only, explicitly NOT urgent. Interim KEAP tags are welcome to prove interop.',
  '- A separate docs review runs before the release (~the next day). Do NOT do that review here;',
  '  instead, end with a short list of what it will need to check, so it starts warm.',
  '',
  'Structure:',
  '1. VERDICT — one paragraph: how far is v0.10, and what is the single thing most likely to slip it.',
  '2. THE ORDERED PATH — a numbered sequence to v0.10 where each step states what must be TRUE at its',
  '   end, not what to do. Put the merge and the cortex gate in their real order and say which parts',
  '   can run in parallel.',
  '3. BLOCKERS — each with evidence, cost, and the test that will prove it closed.',
  '4. SHIPS AS DEBT — what a non-beta release can honestly carry, and the one line each needs in',
  '   RELEASE.md so it is disclosed rather than hidden. v0.9-beta named its red; v0.10 must too.',
  '5. KEAP — the interim-tag cadence, and what v2 means later.',
  '6. WHAT THE DOCS REVIEW WILL NEED.',
  '',
  'Rules for the verdict: do not round up. If the honest answer is that v0.10 is a week away, say a',
  'week. An optimistic plan that slips is worse than a plan that was right. Where the survey and the',
  'judgement disagreed, say so rather than silently taking one side.',
].join('\n'), { label: 'report', phase: 'Report', effort: 'high' })

return {
  dimensions: DIMENSIONS.map((d) => d.key),
  findingCount: findings.length,
  bySeverity: findings.reduce((a, f) => ({ ...a, [f.severity]: (a[f.severity] || 0) + 1 }), {}),
  blockers: confirmed.map((c) => ({ title: c.title, where: c.where, cost: c.cost })),
  demoted: demoted.map((d) => ({ title: d.title, to: d.verdict.downgradeTo })),
  report,
}
