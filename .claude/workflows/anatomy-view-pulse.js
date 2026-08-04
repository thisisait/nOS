export const meta = {
  name: 'anatomy-view-pulse',
  // TRIAGE GATE. This workflow implements roadmap row `face-anatomy`, and the fact
  // that this line is COMMITTED is the gate itself. Discovery writes roadmap
  // rows over HTTP and has no path into git, so it cannot promote its own
  // finding to implementable — see docs/doctrine/workflows.md.
  implements: 'face-anatomy',
  description:
    'The Pulse view of the face Anatomy app — every scheduled job, its run history, and an honest account of the ones that are not running',
  whenToUse:
    'First of the three Anatomy views. Read-only. Run before anatomy-view-bone and anatomy-view-wing so the shared shell, BFF auth path and empty-state conventions are settled once.',
  phases: [
    { title: 'Ground', detail: 'what the APIs ACTUALLY return, measured not assumed' },
    { title: 'Design', detail: 'one view, built only from fields that were observed' },
    { title: 'Build', detail: 'BFF route, Svelte view, Anatomy shell + tab' },
    { title: 'Verify', detail: 'adversarial: no invented fields, no writes, honest empties' },
  ],
}

// Paths below are written relative to the repo root so this definition
// survives the worktree it was authored in. Override with
// Workflow({name: '...', args: {repo: '/abs/path'}}) if agents need absolute
// paths; otherwise they resolve against the session's working directory.
const REPO = (typeof args !== 'undefined' && args && args.repo) || '.'

// ---------------------------------------------------------------------------
// The stance. This is the part that makes the workflow worth its cost.
// ---------------------------------------------------------------------------

const STANCE = `
YOU ARE BUILDING AN OBSERVABILITY SURFACE FOR AN OPERATOR WHO HAS BEEN LIED TO
BY ONE BEFORE. Read this before you read any code.

On 2026-08-04 this estate found an Uptime Kuma container that had reported
\`healthy\` to Docker and HTTP 200 on every route for TEN DAYS while serving its
own installer. It held no database and monitored nothing. Every signal the
operator owned was green. The security queue even recorded a verification —
"container healthy, http 200. Verified" — which checked the two things that
cannot distinguish success from the failure that had actually happened.

You are now building the screen that would have to catch the next one. So:

1. **"No data" and "healthy" are DIFFERENT STATES and must look different.**
   A panel that renders an empty list the same way it renders a list of
   successes is the same defect in CSS. If a job has never run, say never ran.
   If a query returned nothing, say returned nothing. Never let absence render
   as calm.

2. **A field you cannot point to in a real API response does not go in the UI.**
   Not "the presenter probably returns status". Call the endpoint, read the
   JSON, and build from what came back. Inventing plausible fields is the
   easiest way to produce a beautiful screen that shows fiction.

3. **Staleness is data.** A run that finished four days ago on a job scheduled
   hourly is the single most important thing on the screen, and it is invisible
   unless you compute it. Show when something last ran, and show when that is
   later than it should be.

4. **Read-only means read-only.** No POST, PUT, PATCH or DELETE reaches any
   organ from this view. Actions live in Wing UI, which already has the RBAC
   gates. If you find yourself wanting a button, write it down as a follow-up
   instead of building it.

5. **Say what you did not build.** A view that quietly omits a data source
   teaches the operator it does not exist. An explicit "not shown yet: X" line
   in your final report is worth more than one more panel.
`

const GROUNDING = `
WHERE THINGS ARE (verified 2026-08-04 — re-verify, do not trust this list)

  Pulse jobs + runs are served by Wing, not by Pulse itself:
    ${REPO}/files/anatomy/wing/app/Presenters/Api/PulsePresenter.php
      actionJobs, actionJobsDue, actionRuns, actionRunFinish

  The live store, for checking what the API is reading FROM:
    ~/wing/app/data/wing.db  ->  tables: pulse_jobs, pulse_runs
    pulse_runs columns: run_id job_id fired_at finished_at exit_code
                        duration_ms stdout_tail stderr_tail actor_id
                        actor_action_id acted_at created_at updated_at

  The face app shell and how a native app registers:
    ${REPO}/files/anatomy/face/src/lib/apps/native/registry.ts
    ${REPO}/files/anatomy/face/src/lib/apps/native/TablesApp.svelte   (closest prior art)

  Existing BFF routes to copy the auth/proxy pattern from:
    ${REPO}/files/anatomy/face/src/routes/bff/{tables,hub,userstate}/

  The BFF trusts X-Authentik-* identity headers only behind the face edge
  token; read ${REPO}/files/anatomy/face/src/hooks.server.ts before inventing
  an auth path. Wing's API is bearer-authenticated (wing_api_token).

DECIDED ALREADY, do not re-litigate:
  * ONE app called Anatomy with three views (Wing / Pulse / Bone), not three
    separate apps. Reason: a pulse run, a wing event and a bone action share an
    actor_action_id and are one story; three windows lose the thread.
  * Read-only for now.
  * This workflow builds the PULSE view AND the shared Anatomy shell, because
    it runs first. Keep the shell genuinely shared — the other two views will
    mount into it without modification.
`

// ---------------------------------------------------------------------------

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
          evidence: { type: 'string', description: 'How you know — a real response excerpt, or the reason you could not call it' },
        },
      },
    },
    observed_fields: {
      type: 'array',
      description: 'ONLY fields seen in an actual response or an actual DB row',
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
    gaps: {
      type: 'array',
      description: 'Things the view will want that NO endpoint currently provides',
      items: { type: 'string' },
    },
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

// ---------------------------------------------------------------------------

phase('Ground')

// TWO lenses, not three — and the merge is a gain, not a saving.
//
// The first draft split this into `api` (call the endpoints) and `store` (read
// wing.db). Both look at the same pulse data, so by the union test they were
// not disjoint. Worse: THE MOST VALUABLE FINDING IS THE DIVERGENCE BETWEEN
// THEM — where the API reports something the store does not support — and two
// separate agents structurally cannot see it. Only an agent holding both can.
//
// The second lens (face seams) reads an entirely different directory with no
// dependency on the first. That is what licenses running them in parallel.
const LENSES = [
  {
    key: 'pulse-truth',
    prompt: `${STANCE}\n${GROUNDING}\n\nYOUR JOB: establish what the Pulse API returns, what the store actually holds,
and — most importantly — WHERE THE TWO DISAGREE. You hold both halves precisely
so you can compare them; that comparison is the point of this lens.

First the API. Read PulsePresenter.php, then CALL the endpoints for real: Wing
listens on port 9000 and needs a bearer token plus forward-auth headers (recipe
in the operator's memory note "wing-live-verify-recipe"; tokens in
~/.nos/secrets.yml). If you cannot authenticate, say so plainly rather than
reporting 401 as "the endpoint is broken".

Then the store. Query ~/wing/app/data/wing.db directly — pulse_jobs, pulse_runs:
  * how many jobs exist, and how many have EVER run
  * per job: its schedule and its last run, and whether the gap exceeds the
    schedule (this is the staleness signal the view needs and NOTHING computes
    it today)
  * how "paused" is represented in the data
  * what exit_code, stdout_tail and stderr_tail actually contain for a failure

Then the comparison, which no other agent in this workflow can make:
  * does every field the API returns have a real column behind it?
  * does the store hold anything important the API does NOT expose? That is a
    gap the view will need and the design must be told about.

LABEL every field with which method produced it. Provenance is the product here.

Real measured example to check yourself against: on 2026-08-04, of the
claude-invoking jobs only 3 had run in 7 days and one had run exactly once. A
view showing "25 jobs" and nothing else would have hidden that completely.`,
  },
  {
    key: 'face',
    prompt: `${STANCE}\n${GROUNDING}\n\nYOUR JOB: establish how a native face app is actually built here, so the
Anatomy shell fits the existing seams instead of inventing new ones.

Read registry.ts, TablesApp.svelte, KeapExploreApp.svelte, hooks.server.ts, and
at least two existing routes under src/routes/bff/. Establish:
  * exactly how a native app registers and how its window body is resolved
  * how an existing BFF route authenticates outbound to a backend, and where
    its secret comes from
  * the project's Svelte conventions: runes or stores? how is loading state
    handled? is there an existing table/list component to reuse?
  * how tests are written for these (registry.test.ts, surfaces.test.ts)

Report the SEAMS, with file:line. Do not propose a design.`,
  },
]

// FAN-OUT: union. Each lens owns a different directory and a different
// question; the outputs are ADDED, none is discarded. That is what repays
// the per-agent context tax. docs/doctrine/workflow-standard.md §1.
const survey = (await parallel(LENSES.map(l => () =>
  agent(l.prompt, { label: `ground:${l.key}`, phase: 'Ground', schema: SURVEY_SCHEMA })
))).filter(Boolean)

log(`grounded: ${survey.reduce((n, s) => n + s.observed_fields.length, 0)} observed fields, ` +
    `${survey.reduce((n, s) => n + s.gaps.length, 0)} gaps`)

// A barrier is correct here: the designer needs ALL three lenses at once —
// it cannot choose what to render without knowing both what exists and what
// the shell can do.

phase('Design')

const design = await agent(
  `${STANCE}\n${GROUNDING}\n\nYOU ARE DESIGNING THE PULSE VIEW. Here is the measured ground truth from three
independent surveys:\n\n${JSON.stringify(survey, null, 2)}\n\n
Produce a design that uses ONLY the fields listed as observed. If a panel you
want needs something in "gaps", either drop the panel or specify the smallest
API addition that would provide it — and mark it clearly as an addition, not as
something you can assume.

The operator's stated need, verbatim: "abych měl naprostý přehled o tom, co se
se systémem děje" — total awareness of what the system is doing. They already
use Wing's timeline and like it because it shows relationships.

Answer these, concretely:
  1. What does the view show in its first screenful, before any interaction?
  2. How does a STALE job look different from a healthy one, and from one that
     has never run? Draw the three states.
  3. How does a failed run surface its reason without a click? (stderr_tail
     and exit_code exist — use them.)
  4. What is the refresh model? Polling interval, or manual? Justify it against
     the data's actual rate of change.
  5. What does the shared Anatomy shell own, versus this view? Be strict: the
     other two views must mount without editing the shell.

Also load the artifact-design skill's sensibility if available — this should be
a screen the operator WANTS to leave open, not a debug dump. But function
first: a beautiful panel that hides a stale job has failed.

Return a design document in markdown. No code.`,
  { label: 'design:pulse', phase: 'Design', effort: 'high' }
)

phase('Build')

// SEQUENTIAL, and this was a real defect in the first draft of this file.
//
// The first version ran bff / shell / view as three parallel agents. That is
// exactly the pattern the operator's 2026-08-04 measurement indicts: the view
// CANNOT be written without knowing the BFF's response shape and the shell's
// mount seam, so three parallel agents would each invent their own version of
// the other two and the reconciliation would cost more than the parallelism
// saved. Fan-out is for work whose outputs are a UNION or a VETO. Three steps
// of one construction are neither — they are a chain.
//
// Measured backdrop: across 34 subagent runs that day, only 7% of tool calls
// were duplicates, but 90% of the spend was CONTEXT rather than product. The
// waste is not agents repeating each other's commands; it is paying a full
// orientation tax per agent and then discarding, or having to reconcile, most
// of what comes back.
//
// Each step therefore receives what the previous one actually produced.

const WRITE_RULES = `Write real files into the repo. Follow the existing code's conventions —
match its idiom, comment density and naming. Add tests in the style the survey
found. Report the files you wrote AND the contract the next step needs from you
(exact route paths, response shape, exported names, mount seam).`

const bff = await agent(
  `${STANCE}\n${GROUNDING}\n\nSTEP 1 of 3 — the data contract. Nothing depends on it yet, so it goes first.

Implement the BFF route(s) for the Pulse view, following the auth and proxy
pattern the survey found in existing routes — do not invent a new one.

READ-ONLY: the route must refuse anything that is not a GET.

Design:\n${design}\n\nGround truth:\n${JSON.stringify(survey, null, 2)}\n\n${WRITE_RULES}`,
  { label: 'build:bff', phase: 'Build' }
)

const shell = await agent(
  `${STANCE}\n${GROUNDING}\n\nSTEP 2 of 3 — the mount seam, which the other two Anatomy views will inherit.

Implement the shared Anatomy app shell: the native-app registration, the
window, and the three-view tab structure (Wing / Pulse / Bone) with only Pulse
populated — the other two render an explicit "not built yet" state, NOT an
empty panel that could be mistaken for "nothing is happening".

anatomy-view-bone and anatomy-view-wing must mount into this WITHOUT editing
it, and both will check that they did not have to. Design the seam for that.

Design:\n${design}\n\nThe BFF step produced:\n${bff}\n\n${WRITE_RULES}`,
  { label: 'build:shell', phase: 'Build' }
)

const view = await agent(
  `${STANCE}\n${GROUNDING}\n\nSTEP 3 of 3 — the view, which consumes both of the above. You are not guessing
at either; they are given below.

Implement the Pulse view component against the real BFF route and mount it in
the real shell seam.

The three states from the design — healthy / stale / never-ran — must be
visually distinct. An empty response renders as "no runs recorded", never as a
blank success.

Design:\n${design}\n\nBFF step:\n${bff}\n\nShell step:\n${shell}\n\n${WRITE_RULES}`,
  { label: 'build:view', phase: 'Build' }
)

const built = [bff, shell, view]

phase('Verify')

const CHECKS = [
  {
    key: 'no-fiction',
    prompt: `ADVERSARIAL. Every field rendered by the new Pulse view must be traceable to a
field that the survey OBSERVED in a real response or a real DB row. Go through
the component field by field and try to find one that was invented — a
plausible-sounding property nobody ever saw come back from the API.

This is the highest-value check in the workflow. A UI that renders a field the
API never returns shows an empty cell forever and the operator reads it as
"nothing to report".

Observed fields:\n${JSON.stringify(survey.flatMap(s => s.observed_fields), null, 2)}`,
  },
  {
    key: 'read-only',
    prompt: `ADVERSARIAL. Prove the view cannot write. Grep every file the build phase
touched for POST, PUT, PATCH, DELETE, and for any BFF route handler that is not
a GET. Check the BFF route rejects non-GET rather than merely not using it.
Report anything that could mutate an organ.`,
  },
  {
    key: 'honest-empty',
    prompt: `ADVERSARIAL. Take the operator's actual situation on 2026-08-04: 25 pulse
jobs, of which several had not run in a week and some had never run at all.
Trace what this view would have shown. Would a stale job have been visible in
the first screenful, without interaction?

Then the harder version: simulate the API returning an empty list, and the API
returning an error. Does either render as something a tired operator would read
as "fine"? If yes, that is a blocker — it is the ten-days-healthy defect
rebuilt in the UI layer.`,
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
log(blockers.length ? `${blockers.length} BLOCKER(s) — the view is not trustworthy yet` : 'no blockers')

return {
  view: 'pulse',
  design,
  files: built.filter(Boolean),
  gaps: survey.flatMap(s => s.gaps),
  findings: verdicts.flatMap(v => v.findings),
  trustworthy: blockers.length === 0,
}
