export const meta = {
  name: 'cortex-s0-verify',
  description: 'S0 — re-measure the plan\'s facts and answer its three blocking research questions. READ-ONLY.',
  whenToUse: 'First. Every later cortex stage assumes docs/plans/cortex-self-core.md §2 is still true; this is what proves it. Blocking: if a fact moved, stop rather than adapt.',
  phases: [
    { title: 'Verify', detail: 're-measure §2 against the live estate' },
    { title: 'Research', detail: 'the three questions that gate S2 and S4' },
    { title: 'Report', detail: 'reproduced, moved, or unexplained' },
  ],
}

const NOS = '/Users/pazny/projects/nOS'
const KEAP = '/Users/pazny/projects/knowledge-explorer-and-preserver'
const PLAN = `${NOS}/docs/plans/cortex-self-core.md`

const RULES = `
HARD CONSTRAINTS — this workflow is READ-ONLY. It measures; it changes nothing.
- NO writes to either repo. No commits, no branches, no file edits outside a scratch dir.
- NO deploy: no ansible, no converge, no docker restart, no container writes.
- NEVER run host sqlite3 against the live KEAP database — it is a vector-indexed libSQL file
  and the host binary corrupts it. Probe IN-CONTAINER with node:
    docker exec iiab-keap-1 node -e "const D=require('/app/node_modules/libsql'); const db=new D('/data/keap.db',{readonly:true}); ..."
  Wing's own sqlite db (~/wing/app/data/wing.db) is plain SQLite and safe to read with sqlite3.
- Report NUMBERS with the command that produced them. An unsourced number is not a measurement.
- If something cannot be measured, say SO — do not estimate and present it as measured.
  A confident wrong number is worse here than a gap, because later stages act on these.
`

const FACTS = {
  type: 'object', additionalProperties: false, required: ['facts', 'allReproduced'],
  properties: {
    allReproduced: { type: 'boolean' },
    facts: {
      type: 'array',
      items: {
        type: 'object', additionalProperties: false,
        required: ['fact', 'planValue', 'measured', 'status', 'command'],
        properties: {
          fact: { type: 'string' },
          planValue: { type: 'string' },
          measured: { type: 'string' },
          status: { type: 'string', enum: ['reproduced', 'moved', 'unmeasurable'] },
          command: { type: 'string' },
          note: { type: 'string' },
        },
      },
    },
  },
}

const ANSWER = {
  type: 'object', additionalProperties: false, required: ['question', 'answer', 'confidence', 'evidence'],
  properties: {
    question: { type: 'string' },
    answer: { type: 'string' },
    confidence: { type: 'string', enum: ['verified-in-code', 'inferred', 'unknown'] },
    evidence: { type: 'array', items: { type: 'string' } },
    blocks: { type: 'string' },
  },
}

phase('Verify')

const GROUPS = [
  {
    key: 'corpus',
    prompt: `Re-measure the CORPUS half of ${PLAN} §2, in-container:
  - durable payload: summed byte lengths of knowledge_objects (body+description+frontmatter),
    api_taxonomy_metadata (metadata+description), taxonomy_metadata (data), embeddings (vector).
    Plan says ~11.5 MB total.
  - THE LOAD-BEARING ONE: how many corpus rows have NO source outside the container?
    Plan says ZERO and the whole plan rests on it. Check knowledge_objects ids (fs:* = fs-sync
    mirrored, table-* = converge-seeded) and api_taxonomy_metadata (source / user_id /
    json_extract(metadata,'$.origin')). If ANY row is hand-authored, device-captured, or otherwise
    unreproducible, that is a STOP condition — report it first and loudly.
  - embeddings count and total vector bytes.`,
  },
  {
    key: 'index',
    prompt: `Re-measure the INDEX half of ${PLAN} §2 and §5:
  - keap.db file size; embeddings_vec_idx_shadow row count and sum(length(data)).
    Plan says 565 MB file, 513.8 MB index, 3355 vectors.
  - derive bytes-per-vector and check it against the plan's arithmetic model
    (~50 neighbours x 768 dims x 4 B). If the model does not reproduce, the §5 projections to
    1M nodes are wrong and S3's whole premise needs revisiting — say so explicitly.
  - the ORGAN's index for contrast: it reports its own tuning on boot. Read
    ${NOS}/files/anatomy/cortex/server/cortex-store.ts for the parameters it applies.`,
  },
  {
    key: 'surface',
    prompt: `Re-measure the COUPLING half of ${PLAN} §2, statically in ${KEAP} (read-only):
  - the agent API: count endpoints in server/agent.ts + server/intake.ts and classify each as
    corpus-facing or product-facing. Plan says 49 total, ~40 corpus.
  - the UI API: count '/api/ routes in server/routes.ts, relations-routes.ts, topics-routes.ts and
    classify the same way. Plan says 54 total, ~33 corpus.
  - Produce the ACTUAL classified lists, not just counts — S4 is scoped from them.
  - server/db.ts line count (plan says 2966, "the single data chokepoint"): verify that framing by
    checking how many other modules issue SQL directly rather than going through it.`,
  },
  {
    key: 'estate',
    prompt: `Re-measure the ESTATE half of ${PLAN} §2:
  - organ health: is onto1:5d9bef3706a3c8ac still what it reports? The daemon may not be running —
    if not, start it on a SPARE port (not 8098) against a COPY of the store, or read the digest
    from the conformance fixtures. Do not disturb anything running.
  - KEAP repo size (git count-objects -vH) and whether .gitattributes/LFS exists. §4 assumes 3.46 MiB
    and no LFS.
  - fs-sync source path from roles/pazny.keap/templates/compose.yml.j2 — the plan says the organ can
    read it directly as a host daemon. Verify the path EXISTS on the host and is readable by the
    user the cortex daemon runs as. That is the assumption S2 is built on.
  - Pulse job health from ~/wing/app/data/wing.db (plain sqlite, safe): per-job ok/fail counts.
    keap-features-sync was fixed 2026-07-26 — confirm it now succeeds, or report that it has not
    fired since the fix.`,
  },
]

const measured = await parallel(GROUPS.map((g) => () =>
  agent(`${RULES}\n\nRead ${PLAN} §2 first, then:\n${g.prompt}`,
    { label: `verify:${g.key}`, phase: 'Verify', schema: FACTS, effort: 'high' })))

const facts = measured.filter(Boolean).flatMap((m) => m.facts)
const moved = facts.filter((f) => f.status !== 'reproduced')
log(`verify: ${facts.length} facts checked, ${moved.length} moved or unmeasurable`)

phase('Research')

const QUESTIONS = [
  {
    key: 'identity',
    prompt: `OPEN QUESTION 2 — does a caller identity actually unlock kg:/ent:?

KEAP ${KEAP}/docs/specs/cortex-full-scope-decision.md claims the single strongest argument for the
whole transplant: KEAP's agent surface has no caller identity and cannot get one where it lives
(agentAuth yields one scope bit from a process-wide secret; req.agentName is a self-asserted header),
whereas the organ behind Bone's loopback token + Authentik JWKS WOULD have one — and that identity is
the precondition for kg:/ent: to ever resolve.

NOBODY HAS VERIFIED THIS AGAINST BONE'S ACTUAL MIDDLEWARE. Do that now:
  - read ${NOS}/files/anatomy/cortex/server/index.ts agentAuth: does it today do anything more than
    KEAP's? (Expect: no — it was lifted verbatim.)
  - read Bone's auth middleware and Wing's Authentik JWKS handling. Is there a real path by which a
    call arriving at :8098 carries a verifiable caller identity, or is that aspirational?
  - what would actually have to be built? Name files.
  - and separately: object_type_definitions is empty and has no writer, so ent: needs one regardless.
A 2026-07-26 dry run already established: ZERO Bone/JWKS/Authentik references in the organ, agentAuth
lifted verbatim from KEAP, and the real capability sitting in files/anatomy/bone/auth.py (Python,
with JWKS caching + OAuth2 client_credentials + scopes). Do not re-derive that — CONFIRM or REFUTE
it, then go further than the dry run did: cost the graft in files and dependencies, and say which of
the two shapes is right (a JWT library in the organ, or a Bone hop the design rejected).

Answer "unknown" rather than reasoning your way to "yes". This claim justifies the plan's premise;
if it is aspirational, the plan should say so instead of promising it.`,
  },
  {
    key: 'fs-visibility',
    prompt: `OPEN QUESTION 3 — fs-sync per-user visibility and tenant scoping outside the container.

${KEAP}/server/fs-sync.ts (813 lines) mirrors a per-user host tree into knowledge_objects, today
reading a RO bind mount at /user-files with KEAP_FS_SHARED_UIDS and KEAP_FS_SYNC_DIRS. S2 has the
organ read the host path DIRECTLY instead.

Establish what breaks:
  - how are user_id, visibility ('private' / 'tier-users' / …) and tenant scope derived? From path
    segments, from uid ownership, from config?
  - what does the container's view give it that a host daemon would not — or vice versa? A host
    daemon runs as a real user with real filesystem permissions; the container ran as 'node' against
    a RO mount. Does anything depend on that difference?
  - the prune guards (a uid contributing 0 files must not mass-delete its mirrors) — do they still
    hold when the root is a live host path that can be unmounted?
This is named in the plan as "the likeliest source of hidden coupling". Look for what is IMPLIED by
the mount rather than stated in code.`,
  },
  {
    key: 'latency',
    prompt: `OPEN QUESTION 1 — what does crossing the API cost the explorer?

S4 turns ~33 KEAP UI routes into calls over /agent/v1. Some serve the three.js explorer, which issues
graph queries. Establish a BASELINE now, while everything is still in-process, so S4 has something to
regress against:
  - which UI routes does the explorer actually call on load and on interaction? Read the frontend
    (src/) for the fetch sites, do not guess from route names.
  - measure current server-side latency for the heaviest of them against the live container
    (read-only GETs only; never POST to the live system).
  - what is the payload size? A 5 ms route returning 2 MB behaves very differently over a hop.
  - state what a named cache in front of the API would have to do, if the numbers say one is needed.
Do NOT recommend a cache without numbers.`,
  },
]

const answers = await parallel(QUESTIONS.map((q) => () =>
  agent(`${RULES}\n\n${q.prompt}`,
    { label: `research:${q.key}`, phase: 'Research', schema: ANSWER, effort: 'high' })))

phase('Report')

const report = await agent(`${RULES}

Write the S0 verification report to ${NOS}/docs/plans/cortex-s0-report.md (this ONE file write is
permitted; nothing else).

Measured facts:
${JSON.stringify(facts, null, 1)}

Research answers:
${JSON.stringify(answers.filter(Boolean), null, 1)}

Structure it as: VERDICT first (may S1 proceed: yes / yes-with-amendments / no), then the fact table
with plan-value vs measured, then the three answers, then AMENDMENTS — a precise list of what
${PLAN} now says wrongly and what it should say instead. Do NOT edit the plan; propose the edits.

Rules for the verdict:
- ANY corpus row without an external source ⇒ verdict is "no". The plan's central claim would be
  false and S2's parallel-rebuild strategy would need a real migration instead.
- A moved number that does not change a decision is an amendment, not a blocker. Say which is which
  and why — the point of this report is to let a human skip re-deriving it.
- If open question 2 comes back "aspirational", that does not block S1, but it MUST be written into
  the plan as a promise not yet kept rather than left as a justification.`,
  { label: 'report:s0', phase: 'Report', effort: 'high' })

return {
  factsChecked: facts.length,
  moved: moved.map((f) => ({ fact: f.fact, plan: f.planValue, measured: f.measured, status: f.status })),
  answers: answers.filter(Boolean).map((a) => ({ q: a.question, confidence: a.confidence })),
  report,
}
