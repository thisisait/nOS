export const meta = {
  name: 'cortex-s1-docs-as-knowledge',
  description: 'S1 — replicate repo documentation into cortex as typed nodes (hint/note/skill/snippet). The estate\'s own docs are the primary corpus.',
  whenToUse: 'After cortex-s0-verify returns a proceed verdict. This is the first stage that writes.',
  phases: [
    { title: 'Recheck', detail: 'the S0 facts this stage depends on' },
    { title: 'Survey', detail: 'what documentation exists, what it covers, where it lies' },
    { title: 'Design', detail: 'the node kinds and the ingestion contract' },
    { title: 'Build', detail: 'generator + ingestion into the organ store' },
    { title: 'Verify', detail: 'adversarial, and the recall gate with a stated denominator' },
  ],
}

const NOS = '/Users/pazny/projects/nOS'
const PLAN = `${NOS}/docs/archive/cortex-self-core.md`
const BRANCH = 'feat/cortex-docs-knowledge'

const RULES = `
HARD CONSTRAINTS
- Work in ${NOS} on branch ${BRANCH}. NEVER touch main/dev, never tag, never release.
- DO NOT DEPLOY: no ansible, no converge, no docker restart. The organ may be run LOCALLY on a spare
  port against a COPY of its store; never disturb a running daemon or the live KEAP container.
- NEVER host-sqlite3 the live KEAP db (vector-indexed libSQL). In-container node only, read-only.
- The organ's vendored package-lock.json stays lockfileVersion 3 (npm 11 writes locks npm 10 rejects).
  No new dependencies without stating why in the commit.
- tests/anatomy/ is pytest; the organ's own suite is vitest. Both stay green.
- Commit each stage with a real message that says WHY, not what.
`

const SURVEY = {
  type: 'object', additionalProperties: false, required: ['summary', 'sources', 'coverage'],
  properties: {
    summary: { type: 'string' },
    sources: { type: 'array', items: { type: 'object', additionalProperties: false, required: ['path', 'files', 'kind'], properties: { path: { type: 'string' }, files: { type: 'number' }, kind: { type: 'string' }, note: { type: 'string' } } } },
    coverage: { type: 'object', additionalProperties: false, required: ['servicesInstalled', 'servicesDocumented'], properties: { servicesInstalled: { type: 'number' }, servicesDocumented: { type: 'number' }, staleClaims: { type: 'number' }, example: { type: 'string' } } },
  },
}
const FINDINGS = {
  type: 'object', additionalProperties: false, required: ['findings'],
  properties: { findings: { type: 'array', items: { type: 'object', additionalProperties: false, required: ['title', 'file', 'severity', 'failure_scenario'], properties: { title: { type: 'string' }, file: { type: 'string' }, severity: { type: 'string', enum: ['major', 'minor'] }, failure_scenario: { type: 'string' } } } } },
}
const VERDICT = { type: 'object', additionalProperties: false, required: ['real', 'why'], properties: { real: { type: 'boolean' }, why: { type: 'string' } } }

phase('Recheck')
await agent(`${RULES}

Read ${NOS}/docs/archive/cortex-s0-report.md and confirm its verdict permits this stage. Then re-verify
ONLY the facts S1 depends on: docs/systems coverage (plan says 22 of ~60 services), the organ's store
materialises and reports its digest, and the recall gate still runs.

If the S0 report is absent, STOP and say so — S1 must not run on unverified ground.`,
  { label: 'recheck', phase: 'Recheck', effort: 'medium' })

phase('Survey')
const survey = await agent(`${RULES}

Inventory every documentation source in ${NOS} that should become knowledge, and be honest about what
is wrong with it:
  - docs/systems/<svc>/{README,SKILLS,AGENTS}.md — the intended routing corpus. SKILLS.md carries
    named actions with "Trigger:" phrases; the recall gate's 261 cases are generated from them.
  - docs/doctrine/, docs/hidden_fees/, docs/idea/ — decisions, debts, intentions.
  - files/anatomy/skills/, files/anatomy/agents/ — what the agents already know.
  - role README/defaults comments — often the only place a variable's WHY is written.

Then measure the two gaps named in docs/hidden_fees/04-systems-docs-drift.md:
  - COVERAGE: how many installed services have docs vs how many exist (state/manifest.yml is the
    roster). The fee says 22 of ~60.
  - ACCURACY: how many docs cite paths or domains that no longer exist (auth.dev.local,
    ~/stacks/<svc>/… predate nos_data_root). Count them, and give one concrete example.

The accuracy gap is the expensive one: a router that returns nothing is annoying, a router that
returns a confident wrong endpoint sends an agent to act on stale information.`,
  { label: 'survey', phase: 'Survey', schema: SURVEY, effort: 'high' })

phase('Design')
const design = await agent(`${RULES}

Design the node kinds and the ingestion contract. Survey:
${JSON.stringify(survey, null, 1)}

The operator named four kinds — hint, note, skill, snippet — and the intent is bigger than ingestion:
**this is the worked example we are showing future users and their LLMs of how to document an
application, a process, a day's work** so that it yields a navigable knowledge universe rather than a
pile of markdown. Design it as something a stranger would want to copy.

Decide and justify:
1. The kinds. Are four right? What is each FOR, and what is the test that tells them apart? A kind
   whose boundary you cannot state will be misused within a week.
2. How a kind is declared in a source file — frontmatter, heading convention, or a separate manifest.
   Prefer something already true of the docs over a new syntax nobody will follow.
3. Anchoring: every node needs a place in the taxonomy. Which subtree? The self-model already puts
   the estate under 'nos'. Do docs hang off their service's node, or a parallel doc tree?
4. Provenance: a node must carry where it came from (repo, path, commit) so staleness is detectable
   and a wrong card is traceable to a file. This is what makes the accuracy gap fixable rather than
   permanent.
5. Ids: KEAP node ids are ^[a-z][a-z0-9-]*$ per segment — first char must be a LETTER. See
   docs/hidden_fees/03-leading-digit-slugs.md; a service named after a number breaks this and the
   estate is clean today only because someone spelled around it. Whatever you design, ENFORCE the
   rule in code rather than documenting it, and close fee 03.
6. What the explorer will show. The operator's stated goal is zooming into one process with its
   conditional relations, real data, animated over time. You are not building that here — but the
   shape you choose either allows it later or forecloses it. Say which choices are load-bearing.

Write it to ${NOS}/docs/archive/cortex-docs-schema.md. Short and decisive; no options-list where a
decision belongs.`,
  { label: 'design', phase: 'Design', effort: 'high' })

phase('Build')
const build = await agent(`${RULES}

Implement the design at ${NOS}/docs/archive/cortex-docs-schema.md:
${design.slice(0, 3000)}

Build:
- a generator (host-side, alongside files/anatomy/scripts/keap_selfmodel_gen.py — same shape, same
  conventions) that walks the documentation sources and emits typed nodes with provenance;
- ingestion into the organ store, following the existing self-model path in
  files/anatomy/cortex/server/cortex-store.ts. Note the precedent set there: a materialise that
  produces no slug root THROWS. Do the same — docs that ingest to zero nodes must fail loudly, not
  log and continue. Absence is not emptiness.
- a coverage assertion reported as DATA (a field on the report), not only as a log line. The C1
  self-model gap survived a fully green P-4 precisely because coverage was logged and never asserted.

Then run it and report ACTUAL counts: nodes per kind, services covered, services missed by name.
Do NOT paper over the coverage gap — a service without docs must appear as missing, not be silently
absent. Silence is indistinguishable from "no such capability", which is the fee we are paying here.`,
  { label: 'build', phase: 'Build', effort: 'high' })

phase('Verify')
const LENSES = [
  { key: 'honesty', prompt: `Attack the coverage and accuracy REPORTING. Hunt: services silently absent rather than reported missing; a doc ingested despite citing a dead path; a count whose denominator is invisible; the recall gate reporting a percentage of a set it did not measure; a node with no provenance, or provenance that cannot be resolved back to a file+commit.` },
  { key: 'corpus', prompt: `Attack the INGESTION for corpus damage. Hunt: a doc node colliding with a self-model or taxonomy node id; the id charset rule unenforced somewhere; a re-run producing duplicates rather than upserting; a prune that could delete self-model nodes; ingestion that mutates the git-sourced tree rather than adding beside it. The organ's store must stay fully derivable — check nothing was introduced that has no source.` },
]
const verified = await pipeline(
  LENSES,
  (l) => agent(`${RULES}\nAdversarial review of ${BRANCH} (git diff dev...HEAD). Real defects with concrete failure scenarios only.\n${l.prompt}`,
    { label: `verify:${l.key}`, phase: 'Verify', schema: FINDINGS, effort: 'high' }),
  (res, lens) => parallel(((res && res.findings) || [])
    .slice().sort((a, b) => (a.severity === b.severity ? 0 : a.severity === 'major' ? -1 : 1)).slice(0, 3)
    .map((f) => () => agent(`${RULES}\nREAD-ONLY. Try to REFUTE: ${f.title} — ${f.file} — ${f.failure_scenario}\nDefault to real=false when you cannot trace it in the code.`,
      { label: `refute:${lens.key}`, phase: 'Verify', schema: VERDICT })
      .then((v) => ({ ...f, lens: lens.key, verdict: v })))),
)
const confirmed = verified.flat().filter(Boolean).filter((f) => f.verdict && f.verdict.real)
log(`verify: ${verified.flat().filter(Boolean).length} claimed, ${confirmed.length} confirmed`)

const final = await agent(`${RULES}
${confirmed.length ? `First FIX these, each with a test that fails without the fix:\n${confirmed.map((f, i) => `${i + 1}. [${f.severity}] ${f.title} — ${f.file}\n   ${f.failure_scenario}`).join('\n\n')}\n\nThen report.` : 'No confirmed defects. Report.'}

Run the recall gate against the estate's own documentation and report it the way the v2 semantics
require: measured/total, passing/measured, and the unmeasurable count BROKEN DOWN BY CAUSE. Never a
bare percentage — this repo has regretted that once already.

Then state the S1 exit criterion against reality: does every installed service have at least one
typed node, and does any card cite a path that does not exist? If not, say which services and how
many cards, and whether that is a blocker for S2 or a debt to carry.

Also run: pytest tests/anatomy/, the organ's vitest suite, and its onto1 conformance. Report numbers.`,
  { label: 'report', phase: 'Verify', effort: 'high' })

return { survey, design: design.slice(0, 2000), build: build.slice(0, 2000), confirmed: confirmed.map((f) => ({ lens: f.lens, title: f.title })), final }
