export const meta = {
  name: 'anatomy-view-bone',
  description:
    'The Bone view of the face Anatomy app — estate state, aggregate health, the event stream, and the loop ledger, with absence rendered as absence',
  whenToUse:
    'Second of the three Anatomy views. Read-only. Requires the shared Anatomy shell built by anatomy-view-pulse; this workflow must mount into it WITHOUT editing it.',
  phases: [
    { title: 'Ground', detail: 'what Bone actually serves, called for real' },
    { title: 'Design', detail: 'one view, built only from observed fields' },
    { title: 'Build', detail: 'BFF route + Bone view mounted into the existing shell' },
    { title: 'Verify', detail: 'adversarial: no fiction, no writes, honest empties, shell untouched' },
  ],
}

// Paths below are written relative to the repo root so this definition
// survives the worktree it was authored in. Override with
// Workflow({name: '...', args: {repo: '/abs/path'}}) if agents need absolute
// paths; otherwise they resolve against the session's working directory.
const REPO = (typeof args !== 'undefined' && args && args.repo) || '.'

const STANCE = `
YOU ARE BUILDING AN OBSERVABILITY SURFACE FOR AN OPERATOR WHO HAS BEEN LIED TO
BY ONE BEFORE.

On 2026-08-04 this estate found an Uptime Kuma container reporting \`healthy\`
to Docker and HTTP 200 on every route for TEN DAYS while serving its own
installer — no database, no monitors, every signal green. The same day, a
backup was found to have written empty archives for six services for weeks
while reporting success, and a nightly drift check was found to have produced
no verdict at all, silently, at exit 0, since it was written.

The pattern is always the same: A SUCCESS MARKER WRITTEN BY THE CODE THAT
ATTEMPTED THE WORK. You are building the screen that has to catch the next one,
so the same discipline applies to the screen itself:

1. **"No data" and "healthy" are DIFFERENT STATES and must look different.**
   Bone's aggregate health is the sharpest case: if the probe cannot reach a
   service, that is NOT the service being fine, and it must not render the same.

2. **A field you cannot point to in a real response does not go in the UI.**
   Call the endpoint. Read the JSON. Build from what came back.

3. **Freshness is data.** An event stream that stopped an hour ago looks exactly
   like a quiet estate unless you show the timestamp of the newest event. Show
   it. Bone writes to a SQLite store with a jsonl fallback — if the fallback is
   in use, that itself is a finding worth surfacing.

4. **Read-only.** Bone has apply/rollback/cutover endpoints for migrations,
   upgrades, patches and coexistence. NONE of them are reachable from this view.
   Actions stay in Wing UI where the RBAC gates already are. This is the single
   most dangerous view of the three to get wrong.

5. **Say what you did not build.** Bone's surface is large; you will not cover
   it all. An explicit list of what is not shown is worth more than a panel.
`

const GROUNDING = `
WHERE THINGS ARE (verified 2026-08-04 — re-verify, do not trust this list)

  Bone is a local FastAPI daemon (launchd eu.thisisait.nos.bone), default port
  8099 — NEVER hardcode it; ${REPO}/tests/anatomy/test_bone_port_never_hardcoded.py
  exists because that mistake has been made three times.

  Route modules: ${REPO}/files/anatomy/bone/
    main.py state.py events.py health (in main) migrations.py upgrades.py
    patches.py coexistence.py looproutes.py weaknesses.py budget.py vfs.py
    ledger.py judges.py auth.py loopauth.py

  Read-shaped routes observed on 2026-08-04:
    GET /api/health          GET /api/health/aggregate
    GET /api/status          GET /api/services
    GET /api/state           GET /api/state/services   GET /api/state/services/{id}
    GET /api/events          GET /api/migrations       GET /api/upgrades
    GET /api/patches         GET /api/coexistence      /budget
  Write-shaped routes exist alongside them (apply, rollback, cutover,
  promote, cleanup). Those are OUT OF SCOPE and must stay unreachable.

  Auth: Bone verifies HMAC on some paths and uses scope-split bearer tokens on
  others (auth.py, loopauth.py). Read them before assuming. Secrets live in
  ~/.nos/secrets.yml.

  The loop ledger (a genuinely interesting panel) is in ledger.py — tables
  including loop_verdicts with a prev_hash chain. Judge runs live in wing.db as
  loop_judge_runs.

  The shared Anatomy shell was built by anatomy-view-pulse:
    ${REPO}/files/anatomy/face/src/lib/apps/native/   (registry.ts + the shell)
  MOUNT INTO IT. If you believe the shell must change, stop and report that as
  a finding instead — it means the shell was built too narrow, which is worth
  knowing before the third view repeats the problem.

DECIDED ALREADY, do not re-litigate:
  * ONE app called Anatomy with three views. Read-only. This is the Bone view.
`

const SURVEY_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: ['endpoints', 'observed_fields', 'gaps'],
  properties: {
    endpoints: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: false,
        required: ['path', 'method', 'reachable', 'evidence'],
        properties: {
          path: { type: 'string' },
          method: { type: 'string' },
          reachable: { type: 'boolean' },
          evidence: { type: 'string' },
        },
      },
    },
    observed_fields: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: false,
        required: ['field', 'source', 'example'],
        properties: {
          field: { type: 'string' },
          source: { type: 'string' },
          example: { type: 'string' },
        },
      },
    },
    gaps: { type: 'array', items: { type: 'string' } },
  },
}

const VERDICT_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: ['passes', 'findings'],
  properties: {
    passes: { type: 'boolean' },
    findings: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: false,
        required: ['severity', 'file', 'claim', 'evidence'],
        properties: {
          severity: { type: 'string', enum: ['blocker', 'major', 'minor'] },
          file: { type: 'string' },
          claim: { type: 'string' },
          evidence: { type: 'string' },
        },
      },
    },
  },
}

phase('Ground')

const LENSES = [
  {
    key: 'health',
    prompt: `${STANCE}\n${GROUNDING}\n\nYOUR JOB: establish what Bone's health and state surface ACTUALLY returns.

Call /api/health, /api/health/aggregate, /api/status, /api/services,
/api/state and /api/state/services for real against the running daemon. Read
auth.py first so you authenticate correctly rather than reporting 401 as "the
endpoint is broken".

Then the question that matters most: WHAT DOES AGGREGATE HEALTH DO WHEN A
PROBE FAILS? Does an unreachable service report unhealthy, or does it silently
drop out of the aggregate? Find the code path and say which. If an unreachable
service can vanish from the count, that is the ten-days-healthy defect living
inside the very API this view will render, and the view must compensate.

Return every endpoint probed and every field actually seen.`,
  },
  {
    key: 'events',
    prompt: `${STANCE}\n${GROUNDING}\n\nYOUR JOB: establish the event stream's real shape and its real rate.

Read events.py and ledger.py. Call /api/events. Then check the STORE: Bone
writes to Wing's SQLite and falls back to ~/.nos/events.jsonl when that fails.
Establish:
  * the actual event schema (source, actor_id, actor_action_id, type, payload)
  * how many events exist and how recent the newest one is
  * whether the jsonl fallback currently holds anything — if it does, the
    primary write path has been failing and nobody noticed
  * what actor_action_id lets you JOIN across organs (this is the thread the
    operator values in Wing's timeline)

Return observed fields with real example values.`,
  },
  {
    key: 'loop',
    prompt: `${STANCE}\n${GROUNDING}\n\nYOUR JOB: establish what the agentic loop ledger can show.

Read looproutes.py, ledger.py, judges.py and weaknesses.py. Establish the real
shape of loop_verdicts (including the prev_hash chain), loop_judge_runs in
wing.db, the budget surface, and what a verdict actually contains — pass, fail,
indeterminate, the reason a judge skipped, the stdout tail.

Measured context: as of 2026-08-03 the loop had reached only a handful of real
verdicts and one gate-set run sealed FAIL with a stdout excerpt that was
useless until the ledger was changed to keep the TAIL rather than the head.
A panel that shows a verdict without its reason repeats that mistake.

Return observed fields. Flag anything that exists in the schema but is always
empty in practice — those are traps for a UI designer.`,
  },
]

// FAN-OUT: union. Each lens owns a different directory and a different
// question; the outputs are ADDED, none is discarded. That is what repays
// the per-agent context tax. docs/doctrine/workflow-standard.md §1.
const survey = (await parallel(LENSES.map(l => () =>
  agent(l.prompt, { label: `ground:${l.key}`, phase: 'Ground', schema: SURVEY_SCHEMA })
))).filter(Boolean)

log(`grounded: ${survey.reduce((n, s) => n + s.observed_fields.length, 0)} observed fields`)

phase('Design')

const design = await agent(
  `${STANCE}\n${GROUNDING}\n\nYOU ARE DESIGNING THE BONE VIEW. Measured ground truth from three surveys:

${JSON.stringify(survey, null, 2)}

Use ONLY observed fields. If a panel needs something in "gaps", drop it or
specify the smallest API addition — marked clearly as an addition.

Answer concretely:
  1. First screenful, before any interaction: what does the operator learn?
  2. How does an UNREACHABLE service look different from a healthy one and from
     one that is not installed? Draw all three.
  3. How is event-stream freshness shown? What does the panel look like when
     the newest event is an hour old?
  4. If the jsonl fallback is in use, how does the operator find out?
  5. What does the loop panel show that is actually actionable, versus what is
     merely present in the schema?
  6. Refresh model, justified against the real rate of change you measured.

Mount into the EXISTING Anatomy shell. If the shell cannot host this without
modification, say so as a finding — do not silently widen it.

Return a design document in markdown. No code.`,
  { label: 'design:bone', phase: 'Design', effort: 'high' }
)

phase('Build')

// SEQUENTIAL. The view cannot be written without the BFF's real response shape;
// running them in parallel means the view invents one and the two are then
// reconciled at a cost higher than the parallelism saved. Fan-out is for
// outputs that form a UNION or a VETO — the two steps of one construction are
// a chain, and a chain run in parallel is just a guess followed by a rewrite.

const WRITE_RULES = `Write real files. Match the surrounding code's idiom, comment density and
naming. Add tests in the established style. Report the files you wrote AND the
contract the next step needs (exact route paths, response shape, exported names).`

const bff = await agent(
  `${STANCE}\n${GROUNDING}\n\nSTEP 1 of 2 — the data contract.

Implement the BFF route(s) for the Bone view. Follow the auth/proxy pattern
already established by the Pulse view's route — do not invent a second one.

READ-ONLY, and here it is load-bearing: Bone exposes apply/rollback/cutover.
The route must WHITELIST the specific read paths it proxies rather than
forwarding an arbitrary path, or a crafted request reaches a mutation endpoint.
A verifier will try exactly that against what you write.

Design:\n${design}\n\nGround truth:\n${JSON.stringify(survey, null, 2)}\n\n${WRITE_RULES}`,
  { label: 'build:bff', phase: 'Build' }
)

const view = await agent(
  `${STANCE}\n${GROUNDING}\n\nSTEP 2 of 2 — the view, against the real route below rather than an imagined one.

Implement the Bone view component and register it in the EXISTING Anatomy
shell's tab structure. Do not modify the shell's own logic; if you believe you
must, stop and report that instead — it means the seam was built too narrow and
the third view is about to hit the same wall.

Unreachable must not render like healthy. Stale must not render like quiet.

Design:\n${design}\n\nBFF step:\n${bff}\n\nGround truth:\n${JSON.stringify(survey, null, 2)}\n\n${WRITE_RULES}`,
  { label: 'build:view', phase: 'Build' }
)

const built = [bff, view]

phase('Verify')

const CHECKS = [
  {
    key: 'no-fiction',
    prompt: `ADVERSARIAL. Find a field the view renders that nobody ever observed coming
back from Bone. Go field by field.

Observed:\n${JSON.stringify(survey.flatMap(s => s.observed_fields), null, 2)}`,
  },
  {
    key: 'no-writes',
    prompt: `ADVERSARIAL, and the most important check here. Bone's write endpoints —
apply, rollback, cutover, promote, cleanup, provision — must be UNREACHABLE
from this view.

Do not merely check that the client code never calls them. Check the BFF route:
if it proxies a path parameter, try to construct a request that reaches
/api/upgrades/{s}/{r}/apply through it. A whitelist of read paths is the only
answer that survives this test; a "we only send GETs from the client" is not,
because the client is not the boundary.`,
  },
  {
    key: 'honest-empty',
    prompt: `ADVERSARIAL. Simulate: Bone is DOWN. Bone returns an empty service list. The
event stream's newest row is four hours old. The aggregate reports 61 healthy
out of 61 because two unreachable services dropped out of the count entirely.

For each, trace what the operator sees. Any state that a tired operator would
read as "fine" is a blocker — that is precisely the defect this whole view
exists to catch, rebuilt one layer up.`,
  },
  {
    key: 'shell-intact',
    prompt: `Check that the shared Anatomy shell was NOT modified to accommodate this view.
Diff it against what anatomy-view-pulse produced. If it changed, report exactly
what and why — the third view is about to hit the same wall, and a shell that
needs editing per view is a design defect worth naming now rather than after
the third edit.`,
  },
]

// FAN-OUT: veto. Each check tries to REFUTE the same artefact from a
// different angle; disagreement is the product and a single blocker is
// decisive. Cheap, bounded, and diversity is the whole point. §1.
const verdicts = (await parallel(CHECKS.map(c => () =>
  agent(`${STANCE}\n${GROUNDING}\n\n${c.prompt}\n\nFiles written:\n${built.filter(Boolean).join('\n\n')}`,
    { label: `verify:${c.key}`, phase: 'Verify', schema: VERDICT_SCHEMA, effort: 'high' })
))).filter(Boolean)

const blockers = verdicts.flatMap(v => v.findings).filter(f => f.severity === 'blocker')
log(blockers.length ? `${blockers.length} BLOCKER(s)` : 'no blockers')

return {
  view: 'bone',
  design,
  files: built.filter(Boolean),
  gaps: survey.flatMap(s => s.gaps),
  findings: verdicts.flatMap(v => v.findings),
  trustworthy: blockers.length === 0,
}
