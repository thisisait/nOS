export const meta = {
  name: 'p1-hkdf-derivation',
  // TRIAGE GATE. This workflow implements roadmap row `sec-p1`, and the fact
  // that this line is COMMITTED is the gate itself. Discovery writes roadmap
  // rows over HTTP and has no path into git, so it cannot promote its own
  // finding to implementable — see docs/doctrine/workflows.md.
  implements: 'sec-p1',
  description:
    'Secrets P1 — replace {prefix}_pw_x concatenation with one-way HKDF derivation (estate + per-user scopes), so one leaked credential yields exactly one credential',
  whenToUse:
    'After P0/P2 landed (2026-08-02) and BEFORE the planned blank. Implements docs/archive/secret-blast-radius.md §P1 + §P1b. The change must be INERT on the live estate until the operator blanks — see the Freeze phase.',
  phases: [
    { title: 'Scout', detail: 'inventory the 86 runtime-derived credentials and, per credential, who consumes it and whether a reconcile path exists' },
    { title: 'Design', detail: 'settle the derivation module, the scheme-version switch, and the eager-resolve constraint — one committed spec before any code' },
    { title: 'Core', detail: 'the derivation module + its unit tests, pure, no playbook wiring yet' },
    { title: 'Wire', detail: 'retire the declarations, emit the map early in main.yml, keep scheme v1 for a converged host' },
    { title: 'Gate', detail: 'blast radius to 1, scheme-version gate, stock-Jinja gate, and the safe-to-not-run gate' },
    { title: 'Verify', detail: 'four adversarial lenses — does the master still leak, does a non-blank converge stay safe, does a blank actually work, is per-user isolation real' },
    { title: 'Fix', detail: 'apply the confirmed findings only' },
  ],
}

// ── Ground truth this workflow is not allowed to re-derive from memory ───────
const REPO = '/Users/pazny/projects/nOS'
const PLAN = `${REPO}/docs/archive/secret-blast-radius.md`
const GATE = `${REPO}/tests/anatomy/test_secret_blast_radius.py`

// Measured 2026-08-02, after P0+P2. The workflow must RE-MEASURE rather than
// trust these — they are here so a drifting number is visible, not authoritative.
const BASELINE = {
  declared: 101,
  runtime: 86,
  crownJewels: 0,
  lazyRescued: 17,
}

/** Constraints that are NOT negotiable. Every implementing agent gets these
 *  verbatim, because each one has already cost this repo a live incident. */
const CONSTRAINTS = `
HARD CONSTRAINTS — each of these has already broken this estate once.

1. STOCK JINJA ONLY IN VARS FILES. default.config.yml / default.credentials.yml
   are resolved eagerly by the plugin loader via \`template_vars: "{{ vars }}"\`,
   in a context where ansible filter plugins are NOT loaded. A custom filter
   (\`| nos_secret\`) used in a vars file throws "No filter named" and aborts the
   whole run. So HKDF CANNOT be a Jinja filter invoked from a vars file.
   Pinned by tests/anatomy/test_config_stock_jinja_only.py.

2. EVERY VAR MUST RESOLVE BEFORE core-up. A var referenced only through
   \`{{ foo | default(x) }}\` with no definition loading before the core-up
   loader aborts the run — \`default()\` does not save it. "Before core-up"
   means: a key in default.config.yml / default.credentials.yml, or a main.yml
   set_fact. A ROLE DEFAULT DOES NOT COUNT.

3. SAFE TO NOT RUN. The operator's estate is live and converged. This change
   must not alter a single service password until they blank. A converge with
   the change present must either keep scheme v1 values byte-identical, or fail
   LOUDLY before touching anything. A half-applied secret rotation locks the
   operator out of their own estate.

4. NO \${#array[@]} IN ANY .sh UNDER roles/*/files/. Those are Jinja templates;
   that sequence opens a Jinja comment and the RENDER fails. Writing it inside a
   shell comment does not help — that exact mistake was made on 2026-08-02.

5. THE READ-BACK RULE. A step may not record its own success. Assert on the
   effect (a value that is 64 hex and contains no '_pw_'), never on the fact
   that a task ran.
`

// ── Schemas ─────────────────────────────────────────────────────────────────
const INVENTORY = {
  type: 'object',
  required: ['credentials', 'measured'],
  properties: {
    measured: {
      type: 'object',
      required: ['declared', 'runtime', 'crownJewels'],
      properties: {
        declared: { type: 'number' },
        runtime: { type: 'number' },
        crownJewels: { type: 'number' },
      },
    },
    credentials: {
      type: 'array',
      items: {
        type: 'object',
        required: ['name', 'consumer', 'kind', 'reconcilePath', 'scope'],
        properties: {
          name: { type: 'string' },
          consumer: { type: 'string', description: 'the service/role that receives it' },
          kind: {
            type: 'string',
            enum: ['db-password', 'admin-password', 'oidc-client-secret', 'api-token', 'hmac', 'encryption-key', 'other'],
          },
          reconcilePath: {
            type: 'string',
            description: 'the task that can change it in the RUNNING service, or "none" — this decides whether rotation without a blank is even possible',
          },
          scope: { type: 'string', enum: ['estate', 'user'] },
          notes: { type: 'string' },
        },
      },
    },
  },
}

const FINDINGS = {
  type: 'object',
  required: ['findings'],
  properties: {
    findings: {
      type: 'array',
      items: {
        type: 'object',
        required: ['title', 'severity', 'file', 'failureScenario', 'confident'],
        properties: {
          title: { type: 'string' },
          severity: { type: 'string', enum: ['critical', 'high', 'medium', 'low'] },
          file: { type: 'string' },
          line: { type: 'number' },
          failureScenario: { type: 'string', description: 'concrete inputs/state -> what actually breaks' },
          confident: { type: 'boolean', description: 'false = suspected but not proven; say so rather than inflating' },
        },
      },
    },
  },
}

const VERDICT = {
  type: 'object',
  required: ['refuted', 'reasoning'],
  properties: {
    refuted: { type: 'boolean' },
    reasoning: { type: 'string' },
    evidence: { type: 'string', description: 'the command run and what it printed' },
  },
}

// ── Scout ───────────────────────────────────────────────────────────────────
phase('Scout')
log('Inventorying the derived credentials and, per credential, whether it can be rotated without a blank')

const inventory = await agent(
  `Read ${PLAN} (the whole file) and ${GATE}.

Then inventory EVERY credential currently derived from \`global_password_prefix\`
at RUNTIME — i.e. declared as \`{{ global_password_prefix }}_pw_x\` in
default.credentials.yml, default.config.yml or roles/*/defaults/main.yml, MINUS
the names in main.yml's "Lazy-regenerate placeholder" set_fact block (those are
replaced by openssl rand on first run and are already safe).

Re-measure the counts yourself; do not trust these, report them if they differ:
declared=${BASELINE.declared}, runtime=${BASELINE.runtime}, crownJewels=${BASELINE.crownJewels}.

For EACH credential answer the question that decides the whole design:
**is there a task anywhere in this repo that can change this credential inside
the RUNNING service?** Examples that exist: metabase PUT /api/user/1/password,
freescout tinker UPDATE, portainer admin reconcile, nextcloud occ. Most will be
"none" — a Postgres role password set at container init cannot be changed by
re-rendering an env var.

Classify scope as 'user' ONLY where the credential is genuinely per-person
(mail, personal vault). Everything infra-level is 'estate'. Today there is
exactly ONE user (akadmin), so 'user' will be nearly empty — that is expected
and is the point: the scope split is being built while it is cheap.

${CONSTRAINTS}`,
  { schema: INVENTORY, label: 'scout:inventory' },
)

// ── Design ──────────────────────────────────────────────────────────────────
phase('Design')

const design = await agent(
  `You are settling the design for secrets P1 BEFORE any code is written.
Read ${PLAN} §P1 and §P1b, and this inventory:

${JSON.stringify(inventory?.measured ?? {}, null, 1)}
${(inventory?.credentials ?? []).length} credentials, of which
${(inventory?.credentials ?? []).filter((c) => c.reconcilePath && c.reconcilePath !== 'none').length}
have a reconcile path that can change them in a running service.

Decide, and justify each against the constraints:

A. WHERE THE DERIVATION RUNS. Constraint 1 forbids a Jinja filter in a vars
   file. Candidates: (i) a custom Ansible module invoked once early in main.yml
   returning the whole map, then one set_fact; (ii) a lookup plugin; (iii) an
   action plugin. Pick one and say why the others lose. Whatever you pick must
   satisfy constraint 2 — the values must exist before core-up.

B. THE SCHEME VERSION SWITCH. A converged host must keep its v1 (concatenated)
   values byte-identical until it blanks; a fresh install gets v2 (HKDF). Decide
   where the scheme marker lives (~/.nos/state.yml is the runtime side-car), how
   a blank flips it, and what happens on the ILLEGAL transition — a converged v1
   host with v2 code and no blank. Failing loudly is acceptable; silently
   re-deriving is not.

C. THE HKDF PARAMETERS. ikm/salt/info per §P1b, including the per-user subtree.
   Be explicit about what \`uid\` is (slugifyUid(username), per
   face/src/lib/security/uid.ts) and what happens if it changes.

D. WHERE THE MASTER LIVES on a v2 host, given ~/.nos/secrets.yml is mode 0600
   and is itself inside the backup. Note that P5 (keychain) is out of scope here
   but must not be designed out.

E. WHAT ROTATION MEANS for the ${(inventory?.credentials ?? []).filter((c) => !c.reconcilePath || c.reconcilePath === 'none').length}
   credentials with NO reconcile path. Be honest: if the answer is "only a blank
   can rotate these", say so and do not invent a mechanism.

Output a committed spec as markdown. State every decision as a decision, and
list what you deliberately did NOT decide.

${CONSTRAINTS}`,
  { label: 'design:spec', effort: 'high' },
)

// ── Core ────────────────────────────────────────────────────────────────────
phase('Core')

const core = await agent(
  `Implement ONLY the derivation core from this spec — no playbook wiring yet.

SPEC:
${design}

Deliver:
1. The derivation itself, at the location the spec chose, in
   files/anatomy/ (module_utils or library, matching the repo's existing
   custom-module layout — nos_state.py / nos_migrate.py are the precedents;
   ansible.cfg already declares that path).
2. Unit tests that pin the PROPERTIES, not the implementation:
   - the same (master, scope, service, purpose) always yields the same secret;
   - a one-bit change in ANY input yields an unrelated secret;
   - a derived secret does not contain the master as a substring (the exact
     defect being fixed — assert it explicitly);
   - user A's subtree cannot be computed from user B's leaves;
   - the master cannot be recovered from any number of leaves.
3. No changes to default.credentials.yml, default.config.yml or main.yml in this
   phase. If you find you need one, that is a finding — report it, do not do it.

Run the tests. Report the exact command and its output.

${CONSTRAINTS}`,
  { label: 'core:derivation', effort: 'high' },
)

// ── Wire ────────────────────────────────────────────────────────────────────
phase('Wire')

const wire = await agent(
  `Wire the derivation into the playbook, preserving the live estate.

SPEC:
${design}

CORE (already implemented and unit-tested):
${core}

Do:
1. Retire the ${BASELINE.runtime} runtime-derived declarations to "" (or the
   spec's chosen sentinel), keeping every explanatory comment that says WHY a
   credential exists — those comments are load-bearing repo knowledge.
2. Emit the derived map early in main.yml per the spec, before core-up.
3. Implement the scheme-version switch so a converged v1 host is untouched.

Then PROVE, by running them, not by reasoning:
- \`ansible-playbook main.yml --syntax-check\`
- \`python3 -m pytest tests/anatomy -q\` (expect ~2172 passed)
- \`ansible-lint\` (expect 0 failures, production profile)
- the stock-Jinja gate specifically: tests/anatomy/test_config_stock_jinja_only.py
- a --check run against the live inventory IF it is non-destructive; if you
  cannot establish that it is, do NOT run it and say so.

${CONSTRAINTS}`,
  { label: 'wire:playbook', effort: 'high' },
)

// ── Gate ────────────────────────────────────────────────────────────────────
phase('Gate')

// FAN-OUT: union. Each agent lowers and RETRO-VERIFIES a different ratchet in
// a different file; all results are kept. §1.
const gates = await parallel([
  () =>
    agent(
      `Lower the ratchets in ${GATE} to the new reality and RETRO-VERIFY them.

The file already documents two mistakes it made. Do not make a third: after
changing a ceiling, put the OLD derivation back in one file, run the test, and
confirm it goes RED. A ceiling that cannot fail is decoration.

Report the measured numbers before and after, and the retro-check output.`,
      { label: 'gate:ratchet', phase: 'Gate' },
    ),
  () =>
    agent(
      `Write a NEW gate that pins the property this whole change exists for:

**no rendered artifact may contain the master.**

Scan the rendered surface — compose overrides under {{ stacks_dir }}, Traefik
dynamic files, nginx vhosts, launchd plists, systemd units — for the master's
value. It must appear ZERO times on a v2 host.

Retro-verify it: it must go RED against a v1 render, where the master appears
inside every derived credential. If you cannot produce a v1 render to test
against, construct a fixture rather than skipping the retro-check.`,
      { label: 'gate:no-master-in-renders', phase: 'Gate' },
    ),
  () =>
    agent(
      `Write the SAFE-TO-NOT-RUN gate, which is the one the operator actually
depends on right now.

Assert that with the P1 code present but scheme v1 recorded, every credential
resolves to its PRE-CHANGE value. Byte-identical. Build the assertion from the
v1 rule ({prefix}_pw_{name}) rather than from a captured snapshot, so it stays
true as credentials are added.

Then assert the illegal transition is loud: v1 state + v2 code + no blank must
FAIL with a message naming the blank, not silently re-derive.`,
      { label: 'gate:inert-until-blank', phase: 'Gate' },
    ),
])

// ── Verify ──────────────────────────────────────────────────────────────────
phase('Verify')
log('Four adversarial lenses, then per-finding refutation — a finding survives only if refutation fails')

const LENSES = [
  {
    key: 'leak',
    prompt: `Adversarial lens: DOES THE MASTER STILL LEAK?
Try to find any path by which the master, or enough of it to reconstruct a
sibling credential, reaches a rendered artifact, a log line, a container env, a
process argv, or an error message. Include: no_log coverage, debug tasks,
callback telemetry (callback_plugins/wing_telemetry.py), the events pipeline,
and anything writing to ~/.nos/. Assume the attacker has read access to one
rendered compose override — the REM-144 position.`,
  },
  {
    key: 'live',
    prompt: `Adversarial lens: WOULD A CONVERGE BREAK THE OPERATOR'S LIVE ESTATE?
The estate is converged, scheme v1, one user. Walk the playbook as if running it
with this change and no blank. Find anything that would change a credential a
running service already holds, or that would fail a service's own assert. Pay
particular attention to role defaults evaluated before the set_fact, and to
services whose password is set at container INIT and cannot be changed after.`,
  },
  {
    key: 'blank',
    prompt: `Adversarial lens: DOES A BLANK ACTUALLY PRODUCE A WORKING ESTATE?
Trace the blank path: prefix prompt -> scheme flip -> master minting -> the
derived map -> every consumer. Find anything that would produce a v2 estate
where a service and its client disagree about a credential — both halves of an
HMAC pair, both halves of an OIDC client secret, a DB password used by two
different roles. Name each pair you checked.`,
  },
  {
    key: 'user',
    prompt: `Adversarial lens: IS THE PER-USER ISOLATION REAL?
Per §P1b a compromised user container must yield that user and nothing else.
Assume an attacker holds everything inside one user's container. Show what they
can and cannot derive. Check whether anything hands a container the master or
another user's subtree — env vars, mounted files, an API that derives on
request. With one user today this is a design review, so judge the SHAPE, and
say plainly if the shape does not hold rather than passing it because it is
currently untestable.`,
  },
]

const verified = await pipeline(
  LENSES,
  (lens) =>
    agent(
      `${lens.prompt}

Context — the change under review:
${wire}

Gates in place:
${(gates ?? []).filter(Boolean).join('\n---\n')}

Report only defects you can point at a file and line for. An honest "I looked
for X and did not find it" is a valid and useful result — do not manufacture
findings to look thorough. Mark confident=false where you suspect but cannot
prove.`,
      { schema: FINDINGS, label: `verify:${lens.key}`, phase: 'Verify', effort: 'high' },
    ),
  (result, lens) =>
    // FAN-OUT: veto. One refuter per finding, default verdict 'wrong'. A single
    // successful refutation kills the finding — disagreement IS the product. §1.
    parallel(
      ((result && result.findings) || []).map((f) => () =>
        agent(
          `REFUTE this finding. Your default is that it is wrong.

  ${f.severity.toUpperCase()} — ${f.title}
  ${f.file}${f.line ? ':' + f.line : ''}
  Scenario: ${f.failureScenario}

Read the actual code. Try to show the scenario cannot occur — a guard exists,
the branch is unreachable, the var is defined earlier, the file is not rendered
on this platform. Run something if you can. Set refuted=true unless you can
demonstrate the failure is real.`,
          { schema: VERDICT, label: `refute:${lens.key}`, phase: 'Verify' },
        ).then((v) => ({ ...f, lens: lens.key, verdict: v })),
      ),
    ),
)

const survivors = verified
  .flat()
  .filter(Boolean)
  .filter((f) => f.verdict && f.verdict.refuted === false)

log(`${survivors.length} findings survived refutation`)

// ── Fix ─────────────────────────────────────────────────────────────────────
phase('Fix')

let fixes = 'no surviving findings — nothing to fix'
if (survivors.length) {
  fixes = await agent(
    `Fix ONLY these findings, which survived an adversarial refutation attempt:

${survivors
  .map(
    (f) =>
      `- [${f.severity}] ${f.title} (${f.lens})\n  ${f.file}${f.line ? ':' + f.line : ''}\n  ${f.failureScenario}\n  why it survived: ${f.verdict.reasoning}`,
  )
  .join('\n')}

Do not refactor anything else. After fixing, re-run:
  python3 -m pytest tests/anatomy -q
  ansible-lint
  ansible-playbook main.yml --syntax-check
and report the actual output.

${CONSTRAINTS}`,
    { label: 'fix:survivors', effort: 'high' },
  )
}

return {
  measured: inventory?.measured ?? null,
  credentialCount: (inventory?.credentials ?? []).length,
  withoutReconcilePath: (inventory?.credentials ?? []).filter(
    (c) => !c.reconcilePath || c.reconcilePath === 'none',
  ).length,
  design,
  gates,
  findingsRaised: verified.flat().filter(Boolean).length,
  findingsSurviving: survivors.length,
  survivors,
  fixes,
  // The operator blanks tomorrow. This is the handover line.
  operatorNote:
    'P1 is INERT until the scheme flips. Verify with the safe-to-not-run gate BEFORE the blank, and read the blank path in the design spec §B.',
}
