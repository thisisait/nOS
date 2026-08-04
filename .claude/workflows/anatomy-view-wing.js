export const meta = {
  name: 'anatomy-view-wing',
  description:
    'The Wing view of the face Anatomy app — timeline, agent sessions, upgrades and the audit chain, with the cross-organ thread the operator actually values',
  whenToUse:
    'Third of the three Anatomy views, and the one to run LAST: it is the view that stitches the other two together via actor_action_id. Read-only. Mounts into the shell built by anatomy-view-pulse.',
  phases: [
    { title: 'Ground', detail: 'what Wing’s API actually returns, and what the existing UI already does well' },
    { title: 'Design', detail: 'the cross-organ thread, built only from observed fields' },
    { title: 'Build', detail: 'BFF route + Wing view mounted into the existing shell' },
    { title: 'Verify', detail: 'adversarial: no fiction, no writes, honest empties, no regression against Wing UI' },
  ],
}

// Paths below are written relative to the repo root so this definition
// survives the worktree it was authored in. Override with
// Workflow({name: '...', args: {repo: '/abs/path'}}) if agents need absolute
// paths; otherwise they resolve against the session's working directory.
const REPO = (typeof args !== 'undefined' && args && args.repo) || '.'

const STANCE = `
YOU ARE REBUILDING, IN THE FACE, THE ONE UI THIS OPERATOR ALREADY LIKES.

That is a harder brief than the other two views, and it carries a specific risk:
IT IS EASY TO SHIP SOMETHING PRETTIER AND WORSE. The operator's own words:
"aktuálně nejvíce využívám Wing UI (upgrades, agents, a timeline je skvělá)."
The timeline is good because it shows RELATIONSHIPS — a run, the event it
emitted, the action that caused it. Any redesign that loses the thread is a
downgrade no amount of styling repays.

So the first rule here is unusual: **you are permitted to conclude that a Wing
page should stay in Wing.** If a page's value is in an interaction the face
cannot reproduce read-only, say so and leave it. A link to Wing is an honest
answer; a degraded copy is not.

The rest is the estate's standing discipline, and it was earned the hard way.
On 2026-08-04 an Uptime Kuma container was found reporting healthy for ten days
while serving its own installer; the same day a backup was found writing empty
archives while reporting success. Every marker was written by the code that
attempted the work.

1. **"No data" and "healthy" are DIFFERENT STATES and must look different.**
   An agent session list that is empty because no agent ran must not look like
   one that is empty because the query failed.

2. **A field you cannot point to in a real response does not go in the UI.**

3. **Show the thread.** actor_action_id joins a Pulse run to a Wing event to a
   Bone action. This view is where that becomes visible. If you build three
   disconnected tables you have missed the entire point of putting the three
   organs in one app.

4. **Read-only.** Wing has apply, approve, invite and trigger endpoints. None
   are reachable here. Actions stay in Wing UI, which already carries the tier
   gates (BasePresenter \$minAccessTier).

5. **Say what you did not build,** and say what you deliberately left in Wing.
`

const GROUNDING = `
WHERE THINGS ARE (verified 2026-08-04 — re-verify, do not trust this list)

  Wing UI presenters (what already exists, and what you are NOT duplicating
  without a reason): ${REPO}/files/anatomy/wing/app/Presenters/
    Agents Approvals Audit Breaches Coexistence Dashboard Gdpr Hub Inbox
    Migrations Pentest Pulse Remediation Timeline Upgrades Users

  Wing API presenters (what the face can call):
    ${REPO}/files/anatomy/wing/app/Presenters/Api/
    Advisories AgentSessions Agents Audit Coexistence Components Dashboard
    DeployTrigger Events Gdpr Gitleaks Hub Metrics Migrations Notifications
    Patches Pentest Pulse Remediation Scan State Upgrades

  Wing listens on 9000, bearer-authenticated (wing_api_token), and the live
  verify recipe — edge token + forward-auth headers, clearing the Latte cache —
  is in the operator's memory note "wing-live-verify-recipe".

  RBAC: Authentik groups become Nette identity roles via
  app/Security/ForwardAuthUserStorage.php; presenters gate with \$minAccessTier.
  Whatever the face renders must not expose data above the caller's tier — the
  BFF forwards X-Authentik-* headers, so the tier is knowable. Read
  ${REPO}/tests/anatomy/test_security_presenter_gates.py for the contract.

  Audit lineage: events carry source, actor_id and actor_action_id. For an
  AgentKit run, actor_action_id == agent_sessions.uuid, so ONE select
  reconstructs a whole run. That is the thread.

  The shared Anatomy shell was built by anatomy-view-pulse. MOUNT INTO IT.

DECIDED ALREADY, do not re-litigate:
  * ONE app called Anatomy with three views. Read-only. This is the Wing view,
    and it runs last on purpose.
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
    key: 'timeline',
    prompt: `${STANCE}\n${GROUNDING}\n\nYOUR JOB: understand WHY the existing Wing timeline works, before anyone
redesigns it.

Read TimelinePresenter.php and its templates, and Api/EventsPresenter.php.
Then call the API for real and look at actual rows. Establish:
  * what the timeline groups by, and what it correlates
  * how actor_action_id is used today to stitch a run together
  * what an event's payload actually contains for the common sources
    (ansible callback, pulse, agent, backup, gitleaks)
  * the real volume and rate — how many events per day, so the view's paging
    and refresh model can be chosen from data rather than taste

Report the DESIGN INSIGHT, not just the schema: name the specific thing that
makes this page good, in one sentence, so the face view can preserve it.`,
  },
  {
    key: 'agents',
    prompt: `${STANCE}\n${GROUNDING}\n\nYOUR JOB: establish what the agent surface really contains.

Read Api/AgentsPresenter.php and Api/AgentSessionsPresenter.php, plus the
AgentKit tables (agent_sessions, agent_threads, agent_iterations,
agent_vaults, agent_memory_stores) in wing.db. Establish:
  * what a session row actually holds — tokens, trace_id, outcome, grader verdict
  * how many sessions exist and how recent; which agents have NEVER run
  * what an iteration/grader decision looks like for a real run
  * whether trace_id is populated in practice (it deep-links to Tempo — a link
    that 404s is worse than no link)

Measured context: several agent jobs are paused by deliberate on-demand
doctrine. A view that shows them as "0 runs" without saying "paused" would
misrepresent the estate. Find how paused is represented.`,
  },
  {
    key: 'upgrades',
    prompt: `${STANCE}\n${GROUNDING}\n\nYOUR JOB: establish the upgrades / migrations / remediation surface — the part
the operator names as one of their most-used.

Read Api/UpgradesPresenter.php, Api/MigrationsPresenter.php,
Api/RemediationPresenter.php and Api/AdvisoriesPresenter.php. Call them.
Establish what a recipe, a plan and an applied upgrade actually look like, and
what the remediation queue rows contain.

Then the judgement call this lens owns: WHICH OF THESE PAGES SHOULD STAY IN
WING? Upgrades are interactive — plan, choose, apply — and this view is
read-only. Say plainly which parts have real read-only value (status, history,
what is pending) and which are hollow without the actions.`,
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
  `${STANCE}\n${GROUNDING}\n\nYOU ARE DESIGNING THE WING VIEW — and deciding what NOT to move.

Measured ground truth:\n\n${JSON.stringify(survey, null, 2)}\n\n
Answer concretely:
  1. What is on the first screenful? The operator wants "naprostý přehled o tom,
     co se se systémem děje" — total awareness of what is happening.
  2. THE THREAD: show a concrete worked example. Take one real actor_action_id
     from the survey and draw how the view walks it from the Pulse run through
     the Wing event to the Bone action. If you cannot draw it with real data,
     the cross-organ promise of the Anatomy app is not yet real and you must
     say so.
  3. Which Wing pages stay in Wing, and why? Be specific and be willing to
     leave a lot behind.
  4. How does a paused agent look different from an idle one and from a failed
     one?
  5. Refresh model, justified against the measured event rate.
  6. Tier handling: what does a caller below Tier 1 see? Not "we hide it" —
     specify per panel.

Mount into the EXISTING shell. If it cannot host this, report that as a finding.

Return a design document in markdown. No code.`,
  { label: 'design:wing', phase: 'Design', effort: 'high' }
)

phase('Build')

// SEQUENTIAL — a chain, not a fan-out. See the note in anatomy-view-pulse.js.

const WRITE_RULES = `Write real files. Match the surrounding code's idiom, comment density and
naming. Add tests in the established style. Report the files you wrote AND the
contract the next step needs (exact route paths, response shape, exported names).`

const bff = await agent(
  `${STANCE}\n${GROUNDING}\n\nSTEP 1 of 2 — the data contract.

Implement the BFF route(s) for the Wing view, following the pattern the earlier
views established.

READ-ONLY via a WHITELIST of proxied read paths, not an arbitrary path
parameter — Wing exposes approve, invite, trigger and apply endpoints.

Tier: the route forwards X-Authentik-* identity; make sure it does not hand a
lower-tier caller data Wing's own presenters would have gated. The BFF is a NEW
door into the same data, and a verifier will test whether it forgot the lock the
front door has.

Design:\n${design}\n\nGround truth:\n${JSON.stringify(survey, null, 2)}\n\n${WRITE_RULES}`,
  { label: 'build:bff', phase: 'Build' }
)

const view = await agent(
  `${STANCE}\n${GROUNDING}\n\nSTEP 2 of 2 — the view, against the real route below.

Implement the Wing view component and register it in the EXISTING Anatomy
shell. Do not modify the shell's logic.

The thread (actor_action_id) is the centrepiece, not a detail panel.

Design:\n${design}\n\nBFF step:\n${bff}\n\nGround truth:\n${JSON.stringify(survey, null, 2)}\n\n${WRITE_RULES}`,
  { label: 'build:view', phase: 'Build' }
)

const built = [bff, view]

phase('Verify')

const CHECKS = [
  {
    key: 'no-fiction',
    prompt: `ADVERSARIAL. Find a rendered field nobody observed coming back from Wing.

Observed:\n${JSON.stringify(survey.flatMap(s => s.observed_fields), null, 2)}`,
  },
  {
    key: 'no-writes-no-leak',
    prompt: `ADVERSARIAL, two claims to break.

(a) WRITES: try to reach Wing's approve / invite / deploy-trigger / apply
    endpoints through the new BFF route. A path-parameter proxy fails this;
    only a read whitelist survives.

(b) TIER LEAK: construct a request as a Tier-3 caller and check whether any
    panel returns data that Wing's own presenter would have gated behind
    \$minAccessTier. The BFF is a NEW door into the same data — a door that
    forgot the lock the front door has.`,
  },
  {
    key: 'thread-is-real',
    prompt: `ADVERSARIAL, and specific to this view. The whole justification for one app
with three views was that a Pulse run, a Wing event and a Bone action are ONE
story joined by actor_action_id.

Take a real actor_action_id from the live store and walk it through the built
view. Does the thread actually resolve end to end, with real data, today? Or
does it only work for a subset of sources — and if so, which?

If the thread does not resolve, that is a blocker on the PREMISE, not the code,
and it should be reported as such: the operator chose this architecture for
this reason and deserves to know if it did not hold.`,
  },
  {
    key: 'not-worse-than-wing',
    prompt: `ADVERSARIAL, and the check this view exists to survive. Compare the new face
view against the Wing pages it covers — timeline, agents, upgrades — as an
operator who uses Wing daily.

For each: is the face version BETTER, EQUAL, or WORSE? Be blunt. "Prettier but
shows less" is WORSE. Anything worse should either be fixed or left in Wing
with a link, and saying so is a success of this workflow, not a failure.`,
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
  view: 'wing',
  design,
  files: built.filter(Boolean),
  gaps: survey.flatMap(s => s.gaps),
  findings: verdicts.flatMap(v => v.findings),
  trustworthy: blockers.length === 0,
}
