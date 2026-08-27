export const meta = {
  name: 'fable-loop-review',
  description: 'Fable: one large review of the whole agentic self-improvement loop — clock, roster, run record, proposal machine, gates',
  phases: [
    { title: 'Read', detail: 'five independent lenses over the loop as it actually runs', model: 'fable' },
    { title: 'Refute', detail: 'each lens\'s strongest claims attacked before they are believed', model: 'fable' },
    { title: 'Judge', detail: 'one synthesis: keep / change / stop, ending in a startable workflow', model: 'fable' },
  ],
}

const GROUND = `
YOU ARE REVIEWING THE nOS AGENTIC SELF-IMPROVEMENT LOOP. Repo: /Users/pazny/projects/nOS (branch dev, HEAD 8b3c165c).

READ THIS FIRST — it is the estate's own account of the loop and the thing you are judging:
  docs/doctrine/loops.md        (30k, the sequence doctrine: SERE state machine, the unattended
                                 night as a clock, identities, the evidence graph, missing edges,
                                 edge gates)
  docs/doctrine/operator-model.md, docs/doctrine/gates.md, docs/doctrine/security-floor.md

THE MACHINERY, as it exists on disk and in the live wing.db:
  files/anatomy/agents/<name>/{agent.yml,system.md,rubric.md}   10 profiles
  files/anatomy/scripts/pulse-run-agent.sh                      the runner
  tools/run-{scout,remediator,upgrade-architect,agent}.sh       operator launchers
  tools/loop-{propose,review,drive,status,diff,pr}.py           the SERE loop proper
  tools/{agent-status,agent-report,agent-token-status}.py       the readers
  tools/{roadmap-verify,roadmap-status,rem-status,red-status}.py
  files/anatomy/wing/app/AgentKit/                              the PHP runtime
  Live DB: ~/wing/app/data/wing.db  (read-only: sqlite3 file:...?mode=ro is safest)

MEASUREMENTS TAKEN 2026-08-25, which you should verify rather than trust:
  - 35 pulse_jobs rows. EVERY LLM-agent job is paused=1 (curator, librarian x3,
    migration-author, remediator, scout, surveyor, upgrade-advisor, upgrade-architect).
    The unpaused ones are scripts, not agents.
  - loop:propose 01:30 · loop:drive 06:10 · loop:review 06:50 — note the ORDER.
  - How runs ended in 14 days: run_end 7 · outcome_failed 6 · error 6 · ceiling 6 · interrupted 1.
    Over half of all runs did not end cleanly.
  - agent: events all-time: surveyor 408, librarian 189, devlog 30, e2e-mock-agent 29,
    conductor 2, upgrade-architect 1. Five profiles have emitted NOTHING in this DB epoch:
    scout, remediator, upgrade-advisor, curator, migration-author. CLAUDE.md nevertheless
    states "Scout, Remediator, Conductor are live".
  - tools/loop-status.py: 18 proposals, 17 from the rem source, 8 weaknesses, UNRESOLVED x4;
    detectors 'alert', 'fee', 'pulse' report weaknesses but have never once produced a proposal.

STANDING ESTATE DOCTRINE you are expected to apply, not restate:
  - A git ref answers "what is in the repo", never "what is running". Verify against the
    deployed artifact or the live DB.
  - Absence must never read as success. UNKNOWN is a legitimate verdict.
  - Detectors read artifacts, not prose. A gate matching TEXT reports the description as the fact.
  - A success marker must be written by a READER, not by the attempting code.
  - A gate you have not seen fail is not a gate.
  - pytest owns SHAPE, --tags verify owns EFFECT, nos-smoke --strict owns end-to-end truth.

THE OPERATOR'S OWN JUDGEMENT, which frames this pass: the system reads as
OVER-COMPLICATED FOR ITS THROUGHPUT. Ten agent profiles, a state machine, an evidence
graph and eleven readers have, in fourteen days, produced a handful of proposals and a
majority of runs that did not end cleanly. You are permitted — expected — to conclude that
a piece is already right and should be left alone. You are equally permitted to say that a
piece should be DELETED. "Add another gate" is the answer this estate reaches for by
reflex; treat it as the least likely correct answer, not the default.

READ-ONLY. Do not edit files, do not write to wing.db, do not run a converge, do not fire an
agent. Run readers and sqlite SELECTs freely. Your final text IS the return value.
`

const LENSES = [
  {
    key: 'clock',
    prompt: `LENS 1 — THE CLOCK. The loop is split across cron into three jobs (loop:propose 01:30,
loop:drive 06:10, loop:review 06:50) plus ~30 other scheduled rows.

Establish, from the code and the DB rather than from loops.md's prose:
 1. What each of the three actually does, and what state it hands to the next.
 2. THE ORDERING. drive runs 40 minutes BEFORE review. Is that a defect, a deliberate
    lag-by-a-day design, or an accident nobody has had cause to notice? Prove it either way
    by reading what drive consumes and what review produces.
 3. What the split across the clock BUYS. Would one sequential job — propose, review, drive,
    in that order, in one process — lose anything real? Name what it would lose concretely
    (isolation? blast radius? token ceiling? partial-failure recovery?) or say that it would
    lose nothing.
 4. Whether a job that fails at 01:30 leaves the 06:10 one running on stale or absent input,
    and whether anything NOTICES.
 5. Which of the ~30 other scheduled rows are load-bearing to the loop and which are
    independent tenants of the same clock.

Deliver findings with file:line evidence and the sqlite you ran.`,
  },
  {
    key: 'roster',
    prompt: `LENS 2 — THE ROSTER. Ten agent profiles exist; five have never emitted an event in this
DB epoch; every LLM job is paused=1.

Establish:
 1. Per profile: does it have a launcher, a pulse row, an Authentik client, a secret, a
    rubric — and has it EVER run? Build the table from disk + wing.db, not from docs.
 2. What each dormant profile costs to keep: enumerate the concrete carrying cost (files,
    rows, credentials, and every cross-cutting fix that must be applied N times).
 3. upgrade-advisor specifically: its task was "read the matrix, pick the recipe whose
    from_pattern matches". Since UpgradeRepository::compareVersions landed (b1e92005 /
    cab67496), is that task now a deterministic query? If so, say plainly whether an LLM
    belongs there at all.
 4. The doctrine contradiction: CLAUDE.md says "Scout, Remediator, Conductor are live" while
    the events table says otherwise. Which is true, and what should change — the sentence or
    the profiles?
 5. Is there a profile that is genuinely load-bearing and UNDER-used?

Retirement of an agent is a doctrinal decision for the operator — recommend, do not enact.`,
  },
  {
    key: 'runs',
    prompt: `LENS 3 — THE RUN RECORD. In 14 days: run_end 7, outcome_failed 6, error 6, ceiling 6,
interrupted 1. Fewer than a third of runs ended cleanly.

Establish:
 1. What each stop_reason MEANS mechanically (read pulse-run-agent.sh, the AgentKit runtime,
    and the rows themselves). 'ceiling' in particular — is it a real budget stop or a
    mis-scoped prompt?
 2. Read the actual failed rows. Are these one recurring cause wearing five names, or five causes?
 3. When a run ends dirty, WHAT DOES THE ESTATE LEARN? Is there a path from a failed run to
    anything a human or a later run reads? Or does a failure just… stop, and the next reader
    sees a gap that looks like "no work was needed"? (Absence reading as success is this
    estate's signature defect — check whether it lives here too.)
 4. The surveyor rows are the worst offenders (bound/ceiling/outcome_failed, one at 260k input
    tokens for 2.5k output). Diagnose that shape specifically.
 5. Whether tools/agent-status.py is telling the operator the truth about all this, or
    flattening it.`,
  },
  {
    key: 'machine',
    prompt: `LENS 4 — THE PROPOSAL STATE MACHINE (SERE). loops.md §2 describes a state machine from
weakness -> proposal -> judgement -> merge. tools/loop-status.py reports 18 proposals,
17 of them from a single source (rem), 8 weaknesses, UNRESOLVED x4, and three detectors
('alert', 'fee', 'pulse') that report weaknesses but have NEVER produced a proposal.

Establish, from tools/loop-{propose,review,drive}.py and the loop_* tables:
 1. The real state machine, as coded. Draw it. Where does a proposal actually die?
 2. Why one source produces 17 of 18. Is 'rem' the only detector that works, or the only one
    whose weaknesses happen to fit the proposal shape?
 3. The three silent detectors: is "finding nothing actionable" the truth, or is there a
    structural reason their weaknesses cannot become proposals? loop-status.py explicitly
    calls this "information, not a defect" — decide whether that reassurance is earned.
 4. UNRESOLVED x4 — what are they, how long have they sat, and what unblocks them?
 5. The end-to-end question: has this loop ever taken a weakness nobody named and carried it
    to a merged change WITHOUT a human being the missing edge? Find the instances or report
    that there are none. (Memory 'nos-loop-and-sere' records that propose->judge was never
    joined and a human was silently the edge.)`,
  },
  {
    key: 'gates',
    prompt: `LENS 5 — GATES, EVIDENCE, AND THE DOCTRINE'S OWN CLAIMS. loops.md §6 draws an evidence
graph, §7 ranks missing edges, §8 defines "edge gates".

Establish:
 1. Take the doctrine's specific claims about the loop (§2, §3, §6, §8) and CHECK THEM against
    the artifacts. Which are true today, which have rotted, which were aspirational when written?
 2. The edge gates named in §8: do they exist as files, do they run in CI, and — the real
    question — has anyone SEEN them fail? A gate nobody has watched fail is a gate that may be
    asserting a tautology. Sample two and try to reason about what mutation they would catch.
 3. tests/anatomy/ is large. How much of it gates the LOOP as opposed to the estate? Is the
    loop's own machinery under-gated relative to how much it is trusted?
 4. The eleven readers (red-status, loop-status, rem-status, agent-status, roadmap-status,
    night-watch, tls-uptake, agent-token-status, discovery-scan, estate-status, identity-status).
    Do they overlap? Is there a reading nobody takes? Is there a reader whose output nobody
    consumes on any schedule?
 5. Name the single most load-bearing UNGATED assumption in the whole loop.`,
  },
]

const FINDINGS = {
  type: 'object',
  required: ['lens', 'summary', 'findings'],
  properties: {
    lens: { type: 'string' },
    summary: { type: 'string', description: 'Three sentences at most: what this lens concluded.' },
    findings: {
      type: 'array',
      items: {
        type: 'object',
        required: ['claim', 'evidence', 'consequence', 'confidence'],
        properties: {
          claim: { type: 'string', description: 'One sentence, falsifiable.' },
          evidence: { type: 'string', description: 'file:line, sqlite output, or command run. Concrete.' },
          consequence: { type: 'string', description: 'What it costs the estate, concretely.' },
          recommendation: { type: 'string', description: 'keep / change / stop / delete — and what exactly.' },
          confidence: { type: 'string', enum: ['measured', 'inferred', 'suspected'] },
        },
      },
    },
    already_right: {
      type: 'array',
      description: 'Pieces this lens examined and judges to be CORRECT AS BUILT. Naming these is part of the job.',
      items: { type: 'string' },
    },
  },
}

const VERDICT = {
  type: 'object',
  required: ['upheld', 'notes'],
  properties: {
    upheld: { type: 'array', items: { type: 'string' }, description: 'claims that survived refutation, verbatim' },
    refuted: { type: 'array', items: { type: 'string' }, description: 'claims that did NOT survive, with why' },
    notes: { type: 'string' },
  },
}

phase('Read')
log('Five Fable lenses reading the loop as it actually runs.')

const read = await pipeline(
  LENSES,
  l => agent(GROUND + '\n\n' + l.prompt,
             { label: `lens:${l.key}`, phase: 'Read', model: 'fable', schema: FINDINGS }),
  (r, l) => {
    if (!r) return null
    const top = (r.findings || []).slice(0, 6)
    if (!top.length) return { lens: l.key, result: r, verdict: null }
    return agent(
      GROUND +
      `\n\nYOU ARE THE REFUTER for lens "${l.key}". Another Fable agent produced the claims below.
Your job is to TRY TO BREAK THEM, not to agree. For each claim: go to the artifact yourself and
check. Default to refuted when you cannot confirm it independently.

Refute especially hard on:
 - anything asserted from PROSE (a docstring, a comment, loops.md) rather than from an artifact;
 - anything where absence was read as a fact;
 - "this is over-complicated" claims that would be expensive and irreversible if wrong;
 - any recommendation to DELETE something — a deletion recommended on a misreading is the most
   costly error available in this pass.

CLAIMS:\n` + top.map((f, i) =>
        `${i + 1}. ${f.claim}\n   evidence: ${f.evidence}\n   consequence: ${f.consequence}\n   rec: ${f.recommendation || '-'} (${f.confidence})`
      ).join('\n\n'),
      { label: `refute:${l.key}`, phase: 'Refute', model: 'fable', schema: VERDICT })
      .then(v => ({ lens: l.key, result: r, verdict: v }))
  },
)

const surviving = read.filter(Boolean)
log(`${surviving.length}/5 lenses returned; synthesising.`)

phase('Judge')

const dossier = surviving.map(s => {
  const r = s.result
  const v = s.verdict
  return `### LENS ${s.lens}\n${r.summary}\n\n` +
    (r.findings || []).map(f =>
      `- CLAIM: ${f.claim}\n  evidence: ${f.evidence}\n  consequence: ${f.consequence}\n  rec: ${f.recommendation || '-'} [${f.confidence}]`
    ).join('\n') +
    (r.already_right?.length ? `\n\n  ALREADY RIGHT (leave alone): ${r.already_right.join(' | ')}` : '') +
    (v ? `\n\n  REFUTER — upheld: ${(v.upheld || []).length}, refuted: ${(v.refuted || []).length}\n` +
         ((v.refuted || []).length ? `  REFUTED:\n${(v.refuted || []).map(x => '   x ' + x).join('\n')}\n` : '') +
         `  refuter notes: ${v.notes}`
       : '\n\n  (no refutation ran)')
}).join('\n\n')

const judgement = await agent(
  GROUND +
  `\n\nYOU ARE THE JUDGE. Five lenses read the loop; each was then attacked by a refuter.
A claim the refuter broke is NOT evidence — weigh it accordingly, and say so where a lens's
headline died under refutation.

${dossier}

WRITE THE SYNTHESIS. It must answer the operator's actual question — is this system
over-complicated for its throughput, and if so, WHERE exactly — and it must end somewhere
the operator can start tomorrow morning.

Required shape:

1. THE VERDICT — three paragraphs at most. Is the loop over-built? Where is the complexity
   load-bearing and where is it downstream of an accident (the clock split, an agent that
   was easy to add, a doctrine written ahead of the code)?

2. KEEP — the pieces that are right as built. Be specific and be generous where it is earned;
   this estate's habit is to rebuild what already works.

3. CHANGE — ranked, each with: the defect, the artifact, the fix in one sentence, and what
   proves it. Rank by (harm x confidence), not by how interesting it is.

4. STOP — what should be deleted or retired outright, each with the carrying cost it removes
   and the risk of removing it. If the honest answer is "nothing", say that.

5. THE ONE THING — if the operator does exactly one thing tomorrow, what is it and why that one.

6. THE STARTABLE WORKFLOW — a concrete, ordered sequence of steps for the FIRST change, naming
   real files and real commands. Not a plan for a plan.

7. WHAT I COULD NOT ESTABLISH — the honest UNKNOWNs. Absence must not read as success here either.

Write it as prose an operator reads once and acts on. No tables of contents, no restating the
brief back. Roughly 1200-2000 words. This text IS the deliverable.`,
  { label: 'judge', phase: 'Judge', model: 'fable', effort: 'high' })

return {
  lenses: surviving.map(s => ({
    lens: s.lens,
    findings: (s.result.findings || []).length,
    upheld: (s.verdict?.upheld || []).length,
    refuted: (s.verdict?.refuted || []).length,
    already_right: s.result.already_right || [],
  })),
  judgement,
}
