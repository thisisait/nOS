export const meta = {
  name: 'cortex-s2-corpus-parallel',
  description: 'S2 — the organ builds its corpus from the SAME host sources as KEAP, in parallel. No copy, no cutover, diffable at every point.',
  whenToUse: 'After S1. Requires S0 to have confirmed that zero corpus rows lack an external source — that finding is what makes rebuild-instead-of-migrate possible.',
  phases: [
    { title: 'Recheck', detail: 'the no-orphan-rows finding, and fs-sync coupling from S0' },
    { title: 'Design', detail: 'fs-sync as a host reader; the second write target' },
    { title: 'Build', detail: 'ingestion paths into the organ' },
    { title: 'Diff', detail: 'the harness that compares two independently built corpora' },
    { title: 'Verify', detail: 'adversarial, with the two-writer question front and centre' },
  ],
}

const NOS = '/Users/pazny/projects/nOS'
const KEAP = '/Users/pazny/projects/knowledge-explorer-and-preserver'
const PLAN = `${NOS}/docs/plans/cortex-self-core.md`
const BRANCH = 'feat/cortex-corpus-parallel'
// S2 branches off the S1 line, NOT off dev: the docs/pulse/generator work
// (S1, S1b, S1c, S1d) is unmerged, and the organ store this stage builds on
// materialises docs + the pulse node from it. Diff against this base, not dev,
// or every adversarial lens re-reviews all of S1.
const BASE = '3aa6c7d3'

const RULES = `
HARD CONSTRAINTS
- Work in ${NOS} on ${BRANCH}. ${KEAP} is READ-ONLY here. Never main/dev, never tag.
- DO NOT DEPLOY and DO NOT MUTATE THE LIVE SYSTEM. In particular: the organ must never write to
  KEAP's store, and nothing here may change what the live KEAP container ingests.
- The host user tree ({{ nos_data_root }}/tenants/<slug>/users) is REAL USER DATA. Read it; never
  write, move, or delete anything under it. A prune bug here destroys files that are not ours.
- NEVER host-sqlite3 the live KEAP db. In-container node, read-only.
- Run the organ LOCALLY on a spare port against a COPY of its store for anything experimental.
- No new dependencies without justification; lockfileVersion 3.
`

const DESIGN = {
  type: 'object', additionalProperties: false, required: ['summary', 'decisions', 'risks'],
  properties: {
    summary: { type: 'string' },
    decisions: { type: 'array', items: { type: 'object', additionalProperties: false, required: ['question', 'decision', 'because'], properties: { question: { type: 'string' }, decision: { type: 'string' }, because: { type: 'string' } } } },
    risks: { type: 'array', items: { type: 'object', additionalProperties: false, required: ['risk', 'mitigation'], properties: { risk: { type: 'string' }, mitigation: { type: 'string' } } } },
  },
}
const FINDINGS = {
  type: 'object', additionalProperties: false, required: ['findings'],
  properties: { findings: { type: 'array', items: { type: 'object', additionalProperties: false, required: ['title', 'file', 'severity', 'failure_scenario'], properties: { title: { type: 'string' }, file: { type: 'string' }, severity: { type: 'string', enum: ['major', 'minor'] }, failure_scenario: { type: 'string' } } } } },
}
const VERDICT = { type: 'object', additionalProperties: false, required: ['real', 'why'], properties: { real: { type: 'boolean' }, why: { type: 'string' } } }

phase('Recheck')
await agent(`${RULES}

Read ${NOS}/docs/plans/cortex-s0-report.md. Two things gate this stage and both must be re-confirmed
TODAY, not taken from the report:

1. ZERO corpus rows lack an external source. If that has changed — a device capture arrived, someone
   authored an object by hand — then rebuild-instead-of-migrate is invalid and this workflow must
   STOP. The whole strategy rests on this one property.

   S0 sharpened it and the sharpening matters: those external sources are USER FILES ON THE
   REMOVABLE VOLUME /Volumes/SSD1TB, NOT GIT. The corpus is reproducible only while that volume is
   mounted. Re-confirm the volume is mounted AND that the mount assertion S0 asked for exists before
   any walk runs — a host daemon reading an unmounted path sees an empty tree, and an empty tree is
   what the prune guards exist to survive.
2. The fs-sync coupling answer (S0 open question 3): how user_id, visibility and tenant scope are
   derived, and what the container's RO mount implies that a host daemon would not inherit.

Report both. Stop on 1.`,
  { label: 'recheck', phase: 'Recheck', effort: 'high' })

phase('Design')
const design = await agent(`${RULES}

Design the parallel corpus. Read ${PLAN} §6 S2 and ${KEAP}/server/fs-sync.ts (813 lines) in full.

Decide, with reasons:
1. **fs-sync as a host reader — and read this before scoping it.** S0 measured the tree fs-sync
   actually walks and it is nearly empty. /user-files is TWO mounts stacked at one path:

     {{ nos_data_root }}/tenants/<slug>/users            -> /user-files          (5 files)
     {{ keap_selfmodel_root }}                           -> /user-files/nos-docs (176 files)

   Of those 5, three are Bone's per-user .face/state.db files, one is .DS_Store, and exactly ONE is a
   real document. The 166 nos-docs objects all come from the second mount — the self-model — which
   **the organ already generates itself** (runSelfmodel() in cortex-store.ts, the C1 gap closure).

   So porting fs-sync moves, for today's data, ONE PDF. Scope accordingly and say so plainly in the
   report rather than implying a migration happened. The value of this stage is standing the
   ingestion path up and proving it BEFORE there is data to lose, not moving a corpus that does not
   exist yet. Note the consequence for stage 4: the diff harness will be comparing near-empty sets and
   therefore cannot validate much — design it to say that rather than to report a green it did not earn.

   The organ is a host daemon, so it reads the tree DIRECTLY and the bind mount disappears rather than
   being re-plumbed. Real filesystem permissions replace a container 'node' user against a RO mount;
   S0 established that fs-sync derives uid from the directory NAME and visibility from a config set,
   so neither depends on that difference. Keep the prune guards — a uid contributing 0 files must not
   mass-delete its mirrors, and an unreadable subtree must refuse the prune rather than treat absence
   as deletion. With a 1-file tree those guards are the only thing standing between a transient mount
   failure and the loss of the corpus, so they matter MORE here, not less.

   And flag, do not fix: Bone's per-user SQLite lives INSIDE the tree the knowledge system walks. It
   is skipped today only because .face is not in the KEAP_FS_SYNC_DIRS allowlist. Widening that
   allowlist would mirror Bone's user state into the knowledge corpus.
2. **Second write target, not a moved one.** The consolidator and embed-sync keep feeding KEAP AND
   start feeding the organ. Both must be idempotent against both targets. How is a partial failure
   handled — one target accepts, the other rejects?
3. **Is this two writers on one store?** No: two stores, each with its own writer, fed from one
   source. Say explicitly why that is NOT the corruption hazard the design docs warn about, or find
   that it is.
4. **Embeddings.** The organ embeds against the same host Ollama. That doubles the nightly cost
   (measured 17.7 s full pass — trivial). But the organ builds a TUNED index while KEAP's stays
   default, which is exactly the comparison S3 needs. Do not tune anything here; just make sure the
   two indexes are comparable — same corpus, same model, same dimension.
5. **How long does parallel run?** The exit criterion is three consecutive nights of agreement. What
   happens on night 2 if they disagree — halt, or log and continue? Decide now, not during.

Write to ${NOS}/docs/plans/cortex-corpus-parallel.md.`,
  { label: 'design', phase: 'Design', schema: DESIGN, effort: 'high' })

phase('Build')
const build = await agent(`${RULES}

Implement the design:
${JSON.stringify(design, null, 1)}

Port fs-sync into the organ as a host reader, and add the second write target for the feeders. Follow
the conventions already in files/anatomy/cortex/server/cortex-store.ts — especially: a materialise
that produces nothing THROWS, and coverage is reported as data rather than logged.

Report actual counts after a real run against the live host tree (READ-ONLY on that tree):
objects by kind and user, captures, embeddings pending vs done.`,
  { label: 'build', phase: 'Build', effort: 'high' })

phase('Diff')
const diff = await agent(`${RULES}

Build the diff harness — the thing that makes this strategy worth choosing over a migration.

Two corpora built independently from one source SHOULD converge. Compare them and report:
  - row counts per table, and the id sets: present-in-both / only-KEAP / only-organ;
  - for shared ids, whether the content digests agree;
  - embeddings: same refs embedded, same model, same dimension.

Design it so a DISAGREEMENT IS INFORMATIVE, not just a red light — the whole point is that a
difference tells you which side is wrong. An id only in KEAP means the organ's reader missed it; an
id only in the organ means KEAP's is stale or the organ invented something. Say which, per case.

Ship it as a script that can run nightly and a pytest shim that gates it. Report the FIRST real
comparison's numbers — expect disagreement on the first run and say what caused it.`,
  { label: 'diff', phase: 'Diff', effort: 'high' })

phase('Verify')
const LENSES = [
  { key: 'user-data', prompt: `Attack anything that touches the real host user tree. This is the highest-stakes lens: those are the operator's actual files. START HERE: the tree is on a REMOVABLE volume (nos_data_root = /Volumes/SSD1TB/nOS/data) and the estate's only mount preflight — tasks/stacks/docker-external-mount-preflight.yml — guards CONTAINERS, not host daemons. A host reader goes nowhere near it. Hunt every path where an unmounted or half-mounted volume is indistinguishable from an empty tree. Then: any write, move, rename, chmod or delete path; any prune that could fire on an unmounted or transiently-empty tree; any symlink-following walk that could escape the root; any path built by concatenation that a crafted filename could traverse. A false positive here is cheap and a false negative destroys data.` },
  { key: 'two-writer', prompt: `Attack the claim that two stores fed from one source is safe. Hunt: a shared file or lock either side could touch; a feeder that reports success after only one target accepted; ordering assumptions between the two ingests; the organ and KEAP racing on the same host file while it is being written; anything that would make the diff harness report agreement when the two stores actually diverged.` },
  { key: 'derivability', prompt: `Attack the property the organ store must keep: EVERYTHING in it is derivable from git or a host source. Hunt for any row this stage introduces that would not come back after a wipe-and-rebuild — a generated id that is not deterministic, a timestamp that becomes semantic, state accumulated across runs. If the store stops being derivable, docs/plans/nos-cortex-organ-design.md open question 6 (no backup, deliberately) becomes wrong and nobody will notice.` },
]
const verified = await pipeline(
  LENSES,
  (l) => agent(`${RULES}\nAdversarial review of ${BRANCH} (git diff ${BASE}...HEAD — the S1 line is the base, not dev). Concrete failure scenarios only.\n${l.prompt}`,
    { label: `verify:${l.key}`, phase: 'Verify', schema: FINDINGS, effort: 'high' }),
  (res, lens) => parallel(((res && res.findings) || [])
    .slice().sort((a, b) => (a.severity === b.severity ? 0 : a.severity === 'major' ? -1 : 1)).slice(0, 3)
    .map((f) => () => agent(`${RULES}\nREAD-ONLY. Try to REFUTE: ${f.title} — ${f.file} — ${f.failure_scenario}\nDefault to real=false when you cannot trace it. EXCEPTION: for the user-data lens, default to real=TRUE when uncertain — an unrefuted data-loss path must survive review.`,
      { label: `refute:${lens.key}`, phase: 'Verify', schema: VERDICT })
      .then((v) => ({ ...f, lens: lens.key, verdict: v })))),
)
const confirmed = verified.flat().filter(Boolean).filter((f) => f.verdict && f.verdict.real)
log(`verify: ${verified.flat().filter(Boolean).length} claimed, ${confirmed.length} confirmed`)

const final = await agent(`${RULES}
${confirmed.length ? `FIX these first, each with a test that fails without the fix:\n${confirmed.map((f, i) => `${i + 1}. [${f.severity}] ${f.title} — ${f.file}\n   ${f.failure_scenario}`).join('\n\n')}` : 'No confirmed defects.'}

Then state the S2 exit criterion against reality: do the two corpora agree on row counts and ids
within the tolerance the design set? Three consecutive nights is the bar — say how many nights of
evidence exist so far and do not claim the criterion met before it is.

Run pytest tests/anatomy/, the organ's vitest suite, onto1 conformance. Report numbers.
Confirm nothing under ${KEAP} was modified and nothing wrote to the host user tree.`,
  { label: 'report', phase: 'Verify', effort: 'high' })

return { design, build: build.slice(0, 2000), diff: diff.slice(0, 2000), confirmed: confirmed.map((f) => ({ lens: f.lens, title: f.title })), final }
