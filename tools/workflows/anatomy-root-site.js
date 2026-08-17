export const meta = {
  name: 'anatomy-root-site',
  description: 'Decide and build the public anatomy site at the root domain, and the admin shell that absorbs Wing',
  whenToUse: 'When the operator approves the root-site plan. Phase 1 gates phase 2 — a red ruling stops the build.',
  phases: [
    { title: 'Rule', detail: 'four contested questions, answered with evidence before anything is built' },
    { title: 'Decide', detail: 'one record; it may REFUSE to open the build phase' },
    { title: 'Build', detail: 'the first increment, only on a green ruling' },
    { title: 'Verify', detail: 'adversarial check of what was built' },
  ],
}

const GROUND = `
You are working on nOS (repo /Users/pazny/projects/nOS, branch dev). Read CLAUDE.md first — authoritative and dense.

HARD CONSTRAINTS: do NOT push, merge, converge or deploy. Commit locally on dev only when your task says to build.
You may read the repo and the live estate (docker ps, sqlite ~/wing/app/data/wing.db read-only, curl loopback), and use web search.

THE OPERATOR'S REQUEST, in their words (translated):
"Today's goal could be a new web — 'anatomy' — so we are not burdened by nos-face (that gets only a lighter version). It could run directly on pazny.eu and be a signpost between the whole of nOS and wing, keap, pulse, agents and so on. Probably a module on the wing.pazny.eu Nette site with its own route (root — in my case pazny.eu). I want a modern admin dashboard there, not from scratch, find an open-source one. This root web should absorb most of the Wing presenters — they are sloppy anyway, a refactor is welcome. And the homepage should be the anatomy, reachable WITHOUT LOGIN, with the anatomy of our system visualised (probably SVG). Ideally in the style of KEAP explore: zoomed in, only the selected scope, no UI, just discreet navigation (about me, about the project, manifest — thisisait.eu, admin) — organs, organelles, vessels with real (anonymised) data: which systems power what, and click-through into the individual control centres."

MEASURED GROUND (verified 2026-08-16, rely on it):
- Wing has 20 top-level presenters plus an Api/ subtree. Its Traefik auth mode is 'proxy' (forward_auth) — the WHOLE app is gated at the edge, per-app not per-path.
- https://pazny.eu currently returns 404. The root domain is unclaimed.
- roles/pazny.traefik/vars/main.yml carries traefik_extra_routers, a verbatim escape hatch supporting auth: 'none' for routes that gate themselves.
- files/anatomy/face/src/lib/anatomy/{graph.ts,graphLayout.ts} is 642 lines of hand-rolled layout; the face has ONE runtime dependency (html-to-image). The anatomy artifact has 207 nodes / 235 edges; the DEFAULT view is 60 nodes / 71 connectors with 308 crossings. docs/idea/17-loop-split-refactor-graph.md recommends adding d3-force as a second layout mode (75 crossings on that view).
- KEAP's /explore is a "cosmology": stars, dataType facets, a side panel.
- nos-face doctrine (memory): its BFF is an allow-list PROJECTION, never a proxy.
- The estate is FOSS-only, all-local, offline-capable. A CDN-dependent, telemetry-carrying or non-FOSS dependency is disqualified — check, do not assume.

Separate what you VERIFIED from what you inferred. Say "I could not establish X". A recommendation without a cost is not a recommendation.
`

const RULING_SCHEMA = {
  type: 'object',
  required: ['question', 'answer', 'evidence', 'blocking'],
  properties: {
    question: { type: 'string' },
    answer: { type: 'string' },
    evidence: { type: 'array', items: { type: 'string' } },
    blocking: {
      type: 'boolean',
      description: 'true = the build phase MUST NOT proceed until an operator rules on this',
    },
    cost: { type: 'string' },
    unestablished: { type: 'array', items: { type: 'string' } },
  },
}

phase('Rule')

const QUESTIONS = [
  {
    key: 'what-may-be-public',
    prompt: `${GROUND}

QUESTION 1, and it gates everything else: WHAT MAY APPEAR ON AN UNAUTHENTICATED PAGE?

The operator wants the anatomy public, with "real (anonymised) data — which systems power what". An anatomy graph is, read adversarially, a topology map of a live estate: service names, versions, which organ feeds which, where the control centres are.

Enumerate, from the actual artifact (tools/anatomy-graph-gen.py output and files/anatomy/face/src/lib/anatomy/anatomy-graph.json), every FIELD a node or edge carries. For each, rule: PUBLIC, ANONYMISED (and say exactly what the transform is), or WITHHELD. Justify against this estate's own doctrine — the projection rule, the redaction gates (tests/anatomy/test_pulse_redact.py, the face's pulse projection), and the fact that a version number on a public page is a shopping list for the CVE the estate has not patched yet.

Then answer the one that decides the architecture: can a SAFE public projection be produced by an ALLOW-LIST (only named fields ever leave), or does it require a deny-list (everything leaves unless withheld)? Say which, and set blocking:true if you conclude the operator must personally approve the field list before any page is served.`,
  },
  {
    key: 'auth-boundary',
    prompt: `${GROUND}

QUESTION 2: where does the public/private boundary live?

The operator proposes a module on the Wing Nette app with its own route. Wing is the estate's AUDIT AND GOVERNANCE surface: wing.db holds the WORM hash-chained events, the agent sessions, the GDPR register, the breach deadlines. Its plist carries admin-level credentials for every connected service.

Compare, with evidence, three shapes:
 (a) a public route INSIDE Wing (traefik_extra_routers with auth:'none' pointing at a Wing path, or a per-path bypass in the forward-auth middleware);
 (b) a SEPARATE small app serving a published projection, with Wing unchanged and still fully gated;
 (c) a static build — the projection rendered to files at converge time, served by the edge with no application behind it at all.

For each: what an attacker reaches if they find an unlisted path; what breaks if the projection generator has a bug; what it costs to build; and how it interacts with the estate's existing forward-auth wiring (roles/pazny.traefik, the authentik outpost, tests/anatomy/test_forward_auth_does_not_stack.py).

Recommend one. Set blocking:true if you believe (a) cannot be made safe without a change the operator has not authorised.`,
  },
  {
    key: 'admin-shell',
    prompt: `${GROUND}

QUESTION 3: which open-source admin dashboard, and does it fit a Nette/Latte app?

The operator wants a modern admin dashboard, NOT written from scratch. Survey real candidates with current facts (versions, licences, dates, bundle size, whether they need a build step): AdminLTE, Tabler, CoreUI, Filament (Laravel-bound — check), Nette-specific admin kits, Alpine+Tailwind starter shells, shadcn-style component sets, and anything genuinely current in 2026.

The constraints are hard and specific: Latte templates, no Laravel, FOSS licence, NO CDN at runtime (this estate is offline-capable), no telemetry, and it must survive `composer install` + whatever asset step the Wing role already runs — read roles/pazny.wing/tasks/main.yml and files/anatomy/wing/composer.json before assuming an asset pipeline exists.

Also answer honestly: is adopting a dashboard the cheap part and re-templating 20 presenters the expensive part? Give the ratio with evidence.`,
  },
  {
    key: 'presenter-absorption',
    prompt: `${GROUND}

QUESTION 4: which Wing presenters may be absorbed, and which must not move?

Inventory all 20 top-level presenters in files/anatomy/wing/app/Presenters/. For each record: what it shows, its \`$minAccessTier\`, whether it WRITES anything, and whether any gate in tests/anatomy/ asserts its behaviour (grep for the presenter name).

Classify each: ABSORB (a view over data, safe to re-template), KEEP (it is a governance surface whose behaviour a gate pins — moving it risks the property), or RETIRE (superseded).

The operator called them "sloppy" and invited a refactor. Take that seriously AND carefully: BasePresenter carries the tiered RBAC (\`startup()\` enforcing \`$minAccessTier\`) that tests/anatomy/test_security_presenter_gates.py pins. Say plainly which presenters carry a security property that a re-template could silently drop, and what the re-template must preserve.

Give a count: how many are genuinely absorbable in a first increment.`,
  },
]

const rulings = await parallel(
  QUESTIONS.map((q) => () =>
    agent(q.prompt, { label: `rule:${q.key}`, phase: 'Rule', schema: RULING_SCHEMA })),
)

const kept = rulings.filter(Boolean)
const blockers = kept.filter((r) => r.blocking)
log(`${kept.length}/4 rulings; ${blockers.length} blocking`)

phase('Decide')

const decision = await agent(
  `${GROUND}

You are writing the DECISION RECORD for docs/idea/ that turns four rulings into a build plan — or refuses to.

The rulings:
${JSON.stringify(kept, null, 2)}

Produce:
1. THE SHAPE — public surface, auth boundary, admin shell, and how much of Wing moves. One paragraph each, decided, not surveyed.
2. THE FIELD LIST — exactly what appears on the unauthenticated page, as an allow-list a gate can read. If ruling 1 says the operator must approve it personally, present it AS a list for approval and say the build must stop here.
3. THE FIRST INCREMENT — the smallest thing that is independently useful and forecloses nothing. Name the files.
4. WHAT IS DEFERRED and why.
5. THE CHECKPOINT — where the operator must be asked again.

${blockers.length > 0
    ? 'AT LEAST ONE RULING IS BLOCKING. The build phase will NOT run. Say clearly what the operator must decide, and stop.'
    : 'No ruling is blocking. Write the plan so the build phase can execute it directly.'}

Return the text; do not write a file.`,
  { label: 'decide', phase: 'Decide' },
)

if (blockers.length > 0) {
  log('BLOCKED — a ruling requires the operator. Nothing will be built.')
  return { blocked: true, rulings: kept, decision }
}

phase('Build')

const BUILD = [
  {
    key: 'projection',
    prompt: `${GROUND}

BUILD: the public projection and its gate.

Per the decision:
${decision}

Implement ONLY the projection — the thing that turns the internal anatomy artifact into the allow-listed public shape. It is a pure transform with no route and no page: input the existing artifact, output the public document, and a gate that fails if any field outside the allow-list ever appears in the output.

The gate is the deliverable that matters. Write it so it cannot be satisfied by editing itself: derive the forbidden set from the INPUT artifact's fields minus the allow-list, so a new internal field is withheld by default and a new PUBLIC field is a deliberate act. Mutation-verify it.

Commit locally on dev. Do not wire any route.`,
  },
  {
    key: 'svg-view',
    prompt: `${GROUND}

BUILD: the anatomy view, offline and dependency-honest.

Per the decision:
${decision}

Implement the visual: organs, organelles, vessels, in the KEAP-explore manner — zoomed to a scope, discreet navigation only, click-through targets present but inert if the route does not exist yet. Read files/anatomy/face/src/lib/anatomy/graph.ts and graphLayout.ts first; docs/idea/17-loop-split-refactor-graph.md recommends d3-force as a second layout mode and that recommendation may serve here too.

Consume ONLY the public projection from the sibling task — never the internal artifact. If the projection is not ready, build against its documented shape and say so.

Any dependency you add must be FOSS, offline (no CDN at runtime), telemetry-free, and justified in the commit body against the estate's one-dependency posture. Commit locally on dev.`,
  },
]

const built = await pipeline(
  BUILD,
  (b) => agent(b.prompt, { label: `build:${b.key}`, phase: 'Build' }),
  (result, b) =>
    agent(
      `${GROUND}

ADVERSARIALLY REVIEW what was just built for "${b.key}". Try to break it, not to approve it.

Their report: ${result}

Check specifically: does any withheld field reach the public output by ANY path (including error messages, tooltips, ordering, node ids, and counts that disclose a count)? Does the gate actually fail on a violation — construct one and run it. Is every added dependency FOSS, offline and telemetry-free — verify the licence and check for network calls at runtime. Does the full suite still pass?

Report what you found and what you fixed. Do not push.`,
      { label: `verify:${b.key}`, phase: 'Verify' },
    ),
)

return { blocked: false, rulings: kept, decision, built: built.filter(Boolean) }
