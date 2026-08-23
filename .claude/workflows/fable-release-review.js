export const meta = {
  name: 'fable-release-review',
  description:
    'A judgement pass before cutting v0.11-beta: four independent lenses over the transport work, the reader/probe doctrine, the gate corpus and the release itself — permitted to conclude that something is already right',
  whenToUse:
    'Before a release tag, when the operator asks "is it time". Not a defect hunt: 4038 gates and three adversarial passes already ran. What is missing is judgement about what to keep, what to stop, and whether the release notes are honest.',
  phases: [
    { title: 'Read', detail: 'four independent lenses, each grounded in files' },
    { title: 'Verify', detail: 'each claim checked against the artifact, not the prose' },
    { title: 'Judge', detail: 'one synthesis — ship or not, and what to stop' },
  ],
  model: 'fable',
}

const REPO = '/Users/pazny/projects/nOS'

/** The instruction that makes this pass worth its cost. */
const STANCE = `
HOW TO READ THIS CODEBASE

You are the slow, careful pass. This estate runs 4038 gates, keeps a corpus of
29 "hidden fee" post-mortems, and has already had three adversarial lenses over
its recent work WITH per-finding refutation. Hunting for more defects is the
least valuable thing you could do here. Judgement is what is missing.

FIVE RULES:

1. **You may conclude that something is already right.** A previous fable pass
   on this estate blessed an ontology spine with zero edits, and that was the
   useful answer. A review that must find something produces noise, and noise
   here costs more than silence because the operator acts on it.

2. **Say what you would STOP.** Every review adds; almost none subtract. If a
   piece of this should not exist, that is the highest-value sentence you can
   write. Be specific: name the file.

3. **Name the strongest objection to the design, then answer it or concede it.**
   Do not argue with a weak version.

4. **Distinguish "wrong" from "not yet".** Much of this is deliberately unbuilt
   and says so. An unbuilt thing named as unbuilt is not a defect.

5. **Ground yourself in the ACTUAL FILES.** Cite paths and line numbers. Read
   the artifact, not the comment describing it — this repository's most
   repeated defect is a detector that matched prose and reported the
   description as the fact. A judgement without a citation is a preference.

You have shell access. Run the readers. Run the probes. Read the git log.
Nothing in this repository asks you to trust its own summary of itself.
`

const CONTEXT = `
WHAT HAPPENED TODAY (2026-08-23), stated plainly and possibly wrongly

The estate closed REM-217, "datastore transport — encrypted, not merely
enabled". The finding behind it: PostgreSQL and MariaDB both had TLS *enabled*
for months while almost nothing negotiated it — 23 of 42 PostgreSQL backends in
cleartext including the secrets vault, and 72 TLS handshakes against 591,811
MariaDB connections.

Three pieces landed:

  1. HedgeDoc's PostgreSQL session. Its URL carried \`?sslmode=no-verify\`,
     which was correct for its driver family and was DISCARDED by an ORM
     allow-list that copies \`ssl\` and not \`sslmode\` into the driver. The
     control moved to a mounted config.json.
  2. MariaDB "rung 3" — five application clients, which turned out to read
     three DIFFERENT env var names across three forks of one framework, plus a
     sixth client (a metrics exporter) that no survey had listed.
  3. \`notify-supersede\` — a third notification state so that a successor
     retires its predecessors, because 60 of 76 unread inbox rows were
     repeating classes each made false by the next send.

And a fourth thing that is arguably the most important: the READERS changed
shape twice. Sampling \`pg_stat_ssl\` could not answer for a client whose
connection pool lives one millisecond (0 hits in 319 samples over 100s), and
MariaDB's aggregate ratio could not reach 1.0 because the server's own
healthcheck opens a unix socket every 10 seconds. Both now ask each client
about its OWN session, through the client's own config and driver.

THE OPERATOR'S QUESTION: "is it time for a release?" v0.11-beta is drafted in
RELEASE.md, 584 commits and 1577 files past v0.10-beta. CI on \`dev\` is RED.
`

const READING = `
WHERE TO LOOK

  ${REPO}/tools/tls-uptake.py                 the reader everything hangs on
  ${REPO}/state/roadmap-probes.yml            the probes that decide roadmap rows
  ${REPO}/docs/idea/21-mariadb-tls-ladder.md  the plan, and its two corrections
  ${REPO}/docs/doctrine/foreign-properties.md §5, §5.1, §5.2
  ${REPO}/docs/hidden_fees/{22,23,26,27,28,29}-*.md
  ${REPO}/tests/anatomy/test_postgresql_ssl.py
  ${REPO}/tests/anatomy/test_mariadb_client_tls.py
  ${REPO}/tests/anatomy/test_a_successor_retires_its_predecessors.py
  ${REPO}/tests/anatomy/test_the_tls_reader_only_reads.py
  ${REPO}/RELEASE.md                          the v0.11-beta draft
  ${REPO}/docs/active-work.md                 the NOW pointer
  ${REPO}/CLAUDE.md                           the estate's own doctrine

  git log --oneline --since=2026-08-23 | cat
`

const FINDING = {
  type: 'object',
  required: ['lens', 'verdict', 'judgements'],
  properties: {
    lens: { type: 'string' },
    verdict: {
      type: 'string',
      description: 'One paragraph. The single most useful thing you have to say.',
    },
    judgements: {
      type: 'array',
      maxItems: 6,
      items: {
        type: 'object',
        required: ['claim', 'kind', 'evidence', 'confidence'],
        properties: {
          claim: { type: 'string' },
          kind: {
            type: 'string',
            enum: ['keep', 'stop', 'change', 'already-right', 'not-yet', 'objection'],
          },
          evidence: {
            type: 'string',
            description: 'file:line, or a command you ran and its output. Not prose.',
          },
          confidence: { type: 'string', enum: ['high', 'medium', 'low'] },
          strongest_counter: {
            type: 'string',
            description: 'The best argument against this judgement, and whether it survives.',
          },
        },
      },
    },
  },
}

const LENSES = [
  {
    key: 'reader-doctrine',
    prompt: `
LENS 1 — THE READER/PROBE DOCTRINE.

Today the readers moved from SAMPLING a server's view of its clients to ASKING
each client about its own session. Judge that move.

Specifically:
  * Is "ask the client about itself" a sound general rule, or a special case
    being over-generalised from two awkward clients? Where does it break?
  * The self-test reproduces the option the app reads, in the app's container —
    but it is NOT the app's own connection. \`tools/tls-uptake.py\` says so in
    its docstring. Is that caveat load-bearing, or is it a fig leaf? What could
    make it false in practice?
  * The reader is gated to be read-only (test_the_tls_reader_only_reads.py). A
    self-test opens a database connection with the application's credentials
    inside the application's container. Is that still "reading"? Argue it.
  * \`state/roadmap-probes.yml\`: nine probes had their verdict swallowed by
    \`test "$(...)"\` and now echo it. Is the probe format itself the problem?

Read tools/tls-uptake.py end to end before judging any of it.`,
  },
  {
    key: 'transport-substance',
    prompt: `
LENS 2 — DID THE ESTATE ACTUALLY GET SAFER?

The rungs are green. Judge whether that means what it sounds like.

  * Threat model: these are containers on a shared Docker bridge on ONE Mac.
    Who is the adversary that TLS between mariadb and bookstack defends
    against? Is this security work or compliance work? Say which, plainly.
    (SEC-02 in CLAUDE.md isolated header-trust backends on their own network
    after proving a peer-container header forge — read that before answering.)
  * Self-signed certs used as their own CA. \`rejectUnauthorized: false\` for
    HedgeDoc, verification ON for the MariaDB Laravel clients. Is the estate
    getting authentication, or encryption with a decoration of authentication?
  * The sixth MariaDB client (mysqld-exporter) was found by sampling the
    server's connection list, not by the survey. What ELSE does that imply is
    unenumerated? Go and check — the estate has postgres, mariadb and redis.
  * Rung 4 (\`require_secure_transport\`) is deliberately not climbed. Is
    holding it correct, or is an unclimbed last rung just an unfinished job
    that will sit for a year?

Run \`tools/tls-uptake.py\` yourself. Run the probes in state/roadmap-probes.yml.`,
  },
  {
    key: 'gate-corpus',
    prompt: `
LENS 3 — IS THE GATE CORPUS COMPOUNDING OR ACCRETING?

4038 pytest gates, 29 hidden-fee post-mortems, and today added roughly six more
gates and two more fees. Judge the practice, not the individual gates.

  * Read three or four of docs/hidden_fees/*.md. Do they teach something a
    reader could not get from the gate alone, or are they narrative overhead?
  * Several gates today were proven to FAIL in the broken direction before
    being trusted. One (test_no_index_here_depends_on_a_swept_in_column) MISSED
    the exact bug it was written for on the first attempt and was fixed. What
    does that say about the estate's confidence in its own green suite?
  * \`KNOWN_LATENT\` in test_a_successor_retires_its_predecessors.py ratchets
    nine pre-existing instances rather than fixing them. Ratchets accumulate.
    Is this one earning its keep or deferring forever?
  * WHAT SHOULD BE DELETED? Name specific gates or docs that cost more than
    they return. This is the question nobody else will answer.
  * The docstrings are long — many gates carry 30+ lines of prose. Judge that
    deliberately: is it documentation that survives, or is it a habit?`,
  },
  {
    key: 'release',
    prompt: `
LENS 4 — IS IT TIME TO CUT v0.11-beta?

The operator asked. Answer with evidence, not encouragement.

  * Read the v0.11-beta section of RELEASE.md. Does it claim anything the
    estate cannot currently demonstrate? Check its claims against the probes
    and the readers. A release note that overstates is the same defect class
    this whole estate exists to refuse.
  * CI on \`dev\` is RED with three distinct failures:
      - Contracts drift on wing.db-schema.sql — FIXED today, verify it
      - Face vitest: graphLayout.test.ts pins a sha256 of layout positions and
        it mismatches (expected 07b25531..., got ba7345fc...)
      - Pytest: test_a_reader_survives_a_closed_ledger and
        test_the_control_centre_shows_state fail in CI, PASS locally
    Judge each: blocker, or noise? The two pytest ones look environment-shaped
    — but this estate's own memory says "CI red + local can't reproduce =>
    compare exact versions/error across passing-vs-failing jobs FIRST, don't
    hypothesise", because guessing cost it 21 cycles once. Say what you'd
    compare.
  * 584 commits and 1577 files is a large release. CLAUDE.md records that
    \`gh pr merge --rebase\` FAILS at that size and the documented path is a
    fast-forward push. Is that still sound? Is a release this large itself the
    problem?
  * RELEASE.md's own section "Why this is a beta, stated before anyone asks" —
    read it. Is it honest, or is it pre-emptive excuse-making?

Give a one-word answer first: SHIP or HOLD. Then the reasoning.`,
  },
]

phase('Read')
// FAN-OUT KIND: **union**. Each lens reads a DISJOINT space — the reader
// doctrine, the transport substance, the gate corpus, the release itself — and
// their outputs are added together, not compared. Nothing here is a second
// opinion on the same question, which is why a barrier is correct: the
// synthesis needs all four, and four is small enough that the slowest one is
// the cost either way.
const lenses = await parallel(
  LENSES.map((l) => () =>
    agent(`${STANCE}\n${CONTEXT}\n${READING}\n${l.prompt}`, {
      label: `lens:${l.key}`,
      phase: 'Read',
      schema: FINDING,
    })
  )
)

const found = lenses.filter(Boolean)
log(`${found.length}/${LENSES.length} lenses returned; ${found.reduce((n, f) => n + (f.judgements?.length || 0), 0)} judgements`)

// Verify only what is ACTIONABLE and confident. A judgement of "already-right"
// needs no adversary, and a low-confidence one is already labelled.
phase('Verify')
const actionable = found.flatMap((f) =>
  (f.judgements || [])
    .filter((j) => ['stop', 'change', 'objection'].includes(j.kind) && j.confidence !== 'low')
    .map((j) => ({ ...j, lens: f.lens }))
)

const VERDICT = {
  type: 'object',
  required: ['holds', 'why'],
  properties: {
    holds: { type: 'boolean' },
    why: { type: 'string' },
    correction: { type: 'string', description: 'If it does not hold, what is actually true.' },
  },
}

// FAN-OUT KIND: **union**, deliberately NOT veto. One verifier per DISTINCT
// claim; the claims are disjoint, so the outputs add. A veto — N refuters on
// ONE claim — is the right shape when a single finding would be expensive to
// act on wrongly, and it is not the shape here: these are review judgements the
// operator reads, not patches that land unattended, and the volume is low
// enough that a second refuter buys less than it costs (measured 2026-08-04:
// 90% of multi-agent spend is context). Escalate to veto if a judgement ever
// gates an automatic action.
const checked = await parallel(
  actionable.map((j) => () =>
    agent(
      `${STANCE}\n\nA reviewer of ${REPO} claims:\n\n  ${j.claim}\n\n  kind: ${j.kind}\n  evidence offered: ${j.evidence}\n\n` +
        `Go to the files and decide whether this HOLDS. You are not looking for ` +
        `reasons to agree. Check the evidence actually says what is claimed — ` +
        `the failure mode here is a claim about a comment rather than about code. ` +
        `If the claim is right, say so plainly; a confirmed finding is as useful ` +
        `as a refuted one.`,
      { label: `verify:${j.kind}`, phase: 'Verify', schema: VERDICT }
    ).then((v) => ({ ...j, verdict: v }))
  )
)

const survived = checked.filter(Boolean).filter((j) => j.verdict?.holds)
const refuted = checked.filter(Boolean).filter((j) => !j.verdict?.holds)
log(`verify: ${survived.length} held, ${refuted.length} refuted`)

phase('Judge')
const synthesis = await agent(
  `${STANCE}\n${CONTEXT}\n\n` +
    `Four lenses have reported and their actionable claims were adversarially ` +
    `verified. Here is everything:\n\n` +
    `LENS VERDICTS:\n${found.map((f) => `\n## ${f.lens}\n${f.verdict}\n` +
      (f.judgements || []).map((j) => `  - [${j.kind}/${j.confidence}] ${j.claim}\n    evidence: ${j.evidence}` +
        (j.strongest_counter ? `\n    counter: ${j.strongest_counter}` : '')).join('\n')).join('\n')}\n\n` +
    `HELD AFTER VERIFICATION:\n${survived.map((j) => `  - ${j.claim}\n    why: ${j.verdict.why}`).join('\n') || '  (none)'}\n\n` +
    `REFUTED:\n${refuted.map((j) => `  - ${j.claim}\n    actually: ${j.verdict.correction || j.verdict.why}`).join('\n') || '  (none)'}\n\n` +
    `Write the operator's report. It must:\n` +
    `  1. Open with SHIP or HOLD on v0.11-beta and the reason in two sentences.\n` +
    `  2. Say what to STOP — the section nobody else writes. If nothing, say so.\n` +
    `  3. Name what is ALREADY RIGHT and should not be touched.\n` +
    `  4. List concrete next actions, ordered, each with the file to open.\n` +
    `  5. Name the single strongest objection to the estate's current direction ` +
    `and either answer it or concede it.\n\n` +
    `Markdown. No preamble, no flattery, no restating the question. The operator ` +
    `reads fast and acts on what you write.`,
  { label: 'synthesis', phase: 'Judge' }
)

return {
  lenses: found.map((f) => ({ lens: f.lens, verdict: f.verdict, judgements: f.judgements })),
  held: survived.map((j) => ({ claim: j.claim, kind: j.kind, why: j.verdict.why })),
  refuted: refuted.map((j) => ({ claim: j.claim, actually: j.verdict.correction || j.verdict.why })),
  report: synthesis,
}
