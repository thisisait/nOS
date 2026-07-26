export const meta = {
  name: 'cortex-s3-index',
  description: 'S3 — decide the vector index on the recall gate, not on the size column. One corpus, two indexes, one measurement.',
  whenToUse: 'After S2 reaches its exit criterion. The parallel period IS the measurement — outside it, the comparison is not available.',
  phases: [
    { title: 'Baseline', detail: 'recall against the untuned index, recorded before anything changes' },
    { title: 'Measure', detail: 'the tuned variants on the same corpus' },
    { title: 'Scale', detail: 'what the numbers say at 10^5 and 10^6, and what they cannot say' },
    { title: 'Decide', detail: 'one recommendation, with what it costs' },
  ],
}

const NOS = '/Users/pazny/projects/nOS'
const KEAP = '/Users/pazny/projects/knowledge-explorer-and-preserver'
const PLAN = `${NOS}/docs/plans/cortex-self-core.md`
const FEE = `${NOS}/docs/hidden_fees/09-untuned-vector-index.md`
const BRANCH = 'feat/cortex-index'

const RULES = `
HARD CONSTRAINTS
- Work in ${NOS} on ${BRANCH}. ${KEAP} is READ-ONLY. Never main/dev, never tag.
- DO NOT change the LIVE index. Every experiment runs against a COPY of a store, on a spare port.
  The live KEAP container keeps its untuned index until a human applies the decision.
- NEVER host-sqlite3 a live libSQL store. In-container node for KEAP; the organ's own node for its.
- Host Ollama must be reachable for the gate. If it is not, the gate exits 4 = SKIPPED LOUDLY, which
  is NOT a pass — report it as a gap and do not proceed to Decide.
- Report every number with the command that produced it.
`

const MEASURE = {
  type: 'object', additionalProperties: false, required: ['variants', 'corpusSize', 'gateDenominator'],
  properties: {
    corpusSize: { type: 'number' },
    gateDenominator: { type: 'string' },
    variants: {
      type: 'array',
      items: {
        type: 'object', additionalProperties: false,
        required: ['params', 'shadowBytes', 'bytesPerVector', 'gateMeasured', 'gatePassing'],
        properties: {
          params: { type: 'string' },
          shadowBytes: { type: 'number' },
          bytesPerVector: { type: 'number' },
          gateMeasured: { type: 'number' },
          gatePassing: { type: 'number' },
          buildSeconds: { type: 'number' },
          regressions: { type: 'array', items: { type: 'string' } },
        },
      },
    },
  },
}

phase('Baseline')
const baseline = await agent(`${RULES}

Establish the BASELINE before anything is tuned. Read ${FEE} and ${PLAN} §5 first.

Run the recall gate against the corpus as it stands on the untuned index, and record:
  - measured/total and passing/measured, with the unmeasurable count BROKEN DOWN BY CAUSE. A bare
    percentage is the failure mode this repo already regrets once.
  - the exact set of passing cases, saved as the comparison baseline. S3's whole question is
    "did any case that passed stop passing", and that cannot be answered from a count.
  - index footprint: sum(length(data)) on the shadow table, and bytes-per-vector derived.

If the gate exits 4, STOP and report — a skipped gate is not a baseline.`,
  { label: 'baseline', phase: 'Baseline', effort: 'high' })

phase('Measure')
const VARIANTS = [
  { key: 'float8', params: "compress_neighbors=float8" },
  { key: 'mn20', params: "max_neighbors=20" },
  { key: 'both', params: "compress_neighbors=float8, max_neighbors=20" },
  { key: 'mn64', params: "compress_neighbors=float8, max_neighbors=64" },
]
const measured = await parallel(VARIANTS.map((v) => () =>
  agent(`${RULES}

Baseline:
${baseline.slice(0, 2500)}

Build a COPY of the store with the index created as libsql_vector_idx(vector, '${v.params}') and run
the SAME recall gate against it. Report per the schema, and name every case that passed at baseline
and fails here — those are the only numbers that decide anything.

Context you need to interpret your own result (${PLAN} §5): the two knobs do not cost the same.
  - compress_neighbors quantizes only the neighbour copies used for ROUTING; the final distance is
    computed from the stored full-precision vector. Its error changes which candidates get visited,
    not how they rank.
  - max_neighbors lowers graph connectivity, so greedy search can settle in a local minimum. This
    risk GROWS WITH CORPUS SIZE and is invisible at small N.
If your variant shows no regression, say plainly whether that is evidence it is safe, or evidence
that the corpus is too small for the failure mode to appear. Those are different claims.`,
    { label: `measure:${v.key}`, phase: 'Measure', schema: MEASURE, effort: 'high' })))

phase('Scale')
const scale = await agent(`${RULES}

Measurements:
${JSON.stringify(measured.filter(Boolean), null, 1)}

${PLAN} §5 projects these to 10^6 nodes with a simple model: per-vector cost is
(max_neighbors x dims x bytes_per_component) + the node's own full vector + overhead.

1. Does the model reproduce the MEASURED bytes-per-vector for every variant? If not, the projections
   are wrong and must be corrected before anyone plans storage on them.
2. Project each variant to 10^5 and 10^6 nodes.
3. Then the honest part: what do these measurements NOT tell us? Recall at 3-4k vectors is close to
   silent about recall at 10^6 for the max_neighbors knob specifically. State the smallest corpus at
   which the question could actually be settled, and whether generating a synthetic corpus of that
   size is feasible here.
4. The dimension lever: §5 argues a custom 128-dim embedding space turns ~20 GB into ~4.6 GB at 10^6,
   and that this makes the trained model the principal lever on index size rather than a nice-to-have.
   Check that arithmetic and say whether the argument holds.

Do not recommend anything in this phase. Measure and bound.`,
  { label: 'scale', phase: 'Scale', effort: 'high' })

phase('Decide')
const decision = await agent(`${RULES}

Baseline: ${baseline.slice(0, 1500)}
Variants: ${JSON.stringify(measured.filter(Boolean), null, 1)}
Scale: ${scale.slice(0, 3000)}

Write ONE recommendation to ${NOS}/docs/plans/cortex-index-decision.md and update ${FEE} to point at
it. Required content:

- The chosen parameters, and for EACH knob separately: is this a decision (settled, applies at any
  scale) or a scale-dependent parameter that must be re-measured at the next order of magnitude?
  The plan's position is that compress_neighbors is the former and max_neighbors the latter — agree
  or refute it with your numbers.
- The migration: a DDL change that rebuilds the index, applied to the ORGAN. KEAP's live index is not
  touched by this workflow; if the recommendation is that it should be, say so and leave it to a
  human — it is a live-store rebuild on the system the operator uses.
- What it costs. Not just size won: state the recall delta, name every case that changed, and say
  what you would need to have measured to be more confident.
- If NO variant holds, say so and recommend keeping the default. A cheaper index that answers
  slightly wrong questions is a bad trade for a knowledge system, and the size column must not decide
  this.

One recommendation. Not a menu.`,
  { label: 'decide', phase: 'Decide', effort: 'high' })

return { baseline: baseline.slice(0, 1500), variants: measured.filter(Boolean), scale: scale.slice(0, 2000), decision }
