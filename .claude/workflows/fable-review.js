export const meta = {
  name: 'fable-review',
  description:
    'One slow, careful pass over the agentic-loop engine and the doctrine built around it — four lenses, permitted to conclude that something is already right',
  whenToUse:
    'After nos-loop-engine completes. A judgement pass, not a defect hunt: the estate already ran three adversarial lenses with refutation, so finding more bugs is not the point.',
  phases: [
    { title: 'Read', detail: 'three independent lenses over what was built and why' },
    { title: 'Judge', detail: 'one synthesis — what to keep, what to change, what to stop' },
  ],
  model: 'fable',
}

const REPO = '/Users/pazny/projects/nOS/.claude/worktrees/fix-freescout-215'

/** The instruction that makes this pass worth its cost. */
const STANCE = `
HOW TO READ THIS CODEBASE

You are the slow, careful pass. Three adversarial lenses have already run over
this work WITH per-finding refutation, so hunting for more defects is the least
valuable thing you could do. Judgement is what is missing.

FOUR RULES:

1. **You may conclude that something is already right.** A previous fable pass on
   this estate blessed an ontology spine with zero edits, and that was the useful
   answer. A review that must find something produces noise, and noise here costs
   more than silence because the operator acts on it.

2. **Say what you would STOP.** Every review adds; almost none subtract. If a
   piece of this should not exist, that is the highest-value sentence you can
   write.

3. **Name the strongest objection to the design, then answer it or concede it.**
   Do not argue with a weak version.

4. **Distinguish "wrong" from "not yet".** Half of this is deliberately unbuilt.
   An unbuilt thing named as unbuilt is not a defect.

GROUND YOURSELF IN THE ACTUAL FILES. Cite paths and lines. A judgement without a
citation is a preference.
`

const READING = `
WHAT TO READ

  ${REPO}/docs/idea/11-agentic-loop.md            the parent plan
  ${REPO}/docs/idea/11-agentic-loop-contract.md   the contract the workflow committed to
  ${REPO}/docs/idea/12-state-surface.md           the state artefact every model reads first
  ${REPO}/files/anatomy/bone/{judges,ledger,weaknesses,budget,loopauth}.py
  ${REPO}/state/judge-sets.yml
  ${REPO}/.claude/plugins/nos-loop/
  ${REPO}/tests/anatomy/test_loop_*.py
  ${REPO}/docs/hidden_fees/14-a-long-run-cut-from-under.md

CONTEXT YOU NEED

The estate spent its last release (v0.10-beta) on one defect class: *a step
records its own outcome as the fact of having attempted, and the record is
written by the attempting code.* The loop engine is that lesson applied one level
up — in a self-improvement loop the verdict IS the reward signal for the next
modification, so a proposer able to influence its verdict optimises against the
lie rather than merely telling it.

The rule the whole design hangs on: **the judge is code, the proposer is a model,
and they never share an identity.**
`

const JUDGEMENT = {
  type: 'object',
  required: ['keep', 'change', 'stop', 'strongestObjection', 'verdict'],
  properties: {
    keep: { type: 'array', items: { type: 'string' }, description: 'what is already right — be specific, with a path' },
    change: {
      type: 'array',
      items: {
        type: 'object',
        required: ['what', 'why', 'file'],
        properties: { what: { type: 'string' }, why: { type: 'string' }, file: { type: 'string' } },
      },
    },
    stop: { type: 'array', items: { type: 'string' }, description: 'what should not exist. Empty is a valid answer.' },
    strongestObjection: { type: 'string', description: 'the best argument against this design, then answered or conceded' },
    verdict: { type: 'string', enum: ['sound', 'sound-with-changes', 'reconsider'] },
  },
}

// ── Read ────────────────────────────────────────────────────────────────────
phase('Read')
log('Three lenses, each permitted to say "this is already right"')

// FAN-OUT: union. Three lenses ask DIFFERENT questions of the same code and
// every finding set is kept and fed to the synthesis — nothing is chosen
// between. Shared input, disjoint output; see workflow-standard.md §1's
// refinement, which this call site is what forced.
const lenses = await parallel([
  () =>
    agent(
      `${STANCE}\n${READING}

**LENS 1 — WILL THE LOOP ACTUALLY IMPROVE ANYTHING?**

Ignore whether the code is correct; three lenses already checked that. Ask
whether the mechanism can produce improvement at all.

A loop needs: a signal worth chasing, a proposal space where a model can do
something useful, a verdict that discriminates, and memory so it does not circle.
Read the weakness sources and the gate sets and judge whether those four hold.

Specifically: are the weaknesses this mines the KIND of thing a bounded one-file
change can fix? If the top of the ranked list is always "the Linux estate does
not serve" or "38 plans were never implemented", the loop will propose nothing
useful and quietly do nothing — which is worse than not existing, because it will
look like it is working.`,
      { schema: JUDGEMENT, label: 'lens:will-it-work', phase: 'Read', effort: 'high' },
    ),
  () =>
    agent(
      `${STANCE}\n${READING}

**LENS 2 — DOES THIS FIT THE ESTATE, OR IS IT A GUEST?**

nOS has four host organs (Bone signals, Wing observes, Pulse keeps time, Cortex
remembers), 72 anatomy plugins, an AgentKit runtime with its own session/grader
loop, and a doctrine layer in docs/doctrine/.

The contract chose to put the engine INSIDE Bone rather than create a fifth
organ, and argued it. Judge that argument. Then judge the rest: does the ledger
duplicate agent_sessions/agent_iterations? Does the weakness reader duplicate the
remediation queue? Does the plugin duplicate the Hermes skill layer?

Duplication here is not a style problem. This estate has measured the cost — one
law restated in seven places produced a live shape mismatch; a scan and a queue
that disagreed produced 81 058 unattributed events.`,
      { schema: JUDGEMENT, label: 'lens:does-it-fit', phase: 'Read', effort: 'high' },
    ),
  () =>
    agent(
      `${STANCE}\n${READING}

**LENS 3 — WHAT IS THE HONEST FAILURE MODE?**

Not "what bug is there" — what happens when this is used for six months by
someone who trusts it?

Consider: the ledger fills with rejected proposals and nobody reads it; the gate
sets drift from what the estate actually cares about; the weakness ranking
optimises for what is easy to measure rather than what matters; the loop becomes
a ritual that runs nightly and improves nothing while looking healthy.

That last one is the estate's own recurring shape — a scan that stamped freshness
without scanning, a probe that passed an empty stack, a notification that
stamped delivery on failure. **What would this component's version of that look
like, and does anything currently prevent it?**`,
      { schema: JUDGEMENT, label: 'lens:six-months-later', phase: 'Read', effort: 'high' },
    ),
])

// ── Judge ───────────────────────────────────────────────────────────────────
phase('Judge')

const synthesis = await agent(
  `${STANCE}

Three lenses read the agentic-loop engine. Synthesise ONE judgement.

${JSON.stringify(lenses.filter(Boolean), null, 1).slice(0, 20000)}

Produce a short document — under 120 lines — and write it to
${REPO}/docs/idea/13-fable-review.md.

It must contain, in this order:

1. **The verdict in one sentence.** Sound / sound-with-changes / reconsider.
2. **What is already right.** Name it specifically. If the lenses agree something
   is well made, say so once and move on — do not pad it.
3. **The three changes worth making**, ranked by value per hour, each with a file.
   Three. Not eight. If the lenses raised more, the ranking is your job.
4. **What to stop.** If nothing, write "nothing" and defend it in one line.
5. **The strongest objection**, stated at its strongest, then answered or conceded.
6. **The one thing you are least sure about**, and what would settle it.

Where the lenses disagree, do not average them — pick, and say why the other
reading loses. An averaged review is one nobody can act on.`,
  { label: 'judge:synthesis', phase: 'Judge', effort: 'high' },
)

return {
  verdicts: lenses.filter(Boolean).map((l) => l.verdict),
  stopList: lenses.filter(Boolean).flatMap((l) => l.stop || []),
  synthesis,
  wrote: 'docs/idea/13-fable-review.md',
}
