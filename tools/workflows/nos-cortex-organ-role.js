export const meta = {
  name: 'nos-cortex-organ-role',
  description: 'P-4b — Ansible-ize the pazny.cortex organ (build sequence steps 9-12, blank verify trimmed): role, plugin, CI gate, one supervised --tags cortex converge, plus the cortex-specs consolidation ledger',
  whenToUse:
    'After nos-cortex-organ-port (P-4 steps 1-8) is green on feat/cortex-organ — the organ builds, pins onto1:76d1f3ad728b382b, serves validate on 127.0.0.1:8098, and the C1 self-model gap is closed (1841/1051/1841 parity). Runs in the nOS repo on feat/cortex-organ. Covers docs/plans/nos-cortex-organ-design.md §6 steps 9-11 fully and step 12 WITHOUT the blank run; step 13 (KEAP P-5 cutover) stays a separate supervised PR in the KEAP repo.',
  phases: [
    { title: 'Scout', detail: 'the bone-role anatomy conventions and the plugin/CI wiring precedents' },
    { title: 'Role', detail: 'roles/pazny.cortex — build step, plist/systemd, defaults+credentials, main.yml hook, manifest row' },
    { title: 'Plugin', detail: 'cortex-base plugin.yml + Pulse keap-embed-sync; keap-base gains cortex_backend_url (render only)' },
    { title: 'CI', detail: 'the cortex Node-22 job + tests/anatomy pytest shims + the onto1 conformance gate' },
    { title: 'Converge', detail: 'THE ONLY DEPLOY — ansible-playbook main.yml --tags cortex, then live verify (no blank)' },
    { title: 'Docs', detail: 'cortex-specs consolidation ledger; port still-live specs into nOS, KEAP untouched' },
    { title: 'Verify', detail: 'three adversarial lenses' },
    { title: 'Fix', detail: 'confirmed findings only' },
    { title: 'Report', detail: 'honest state, including what is deliberately NOT done' },
  ],
}

const KEAP = '/Users/pazny/projects/knowledge-explorer-and-preserver'
const NOS = '/Users/pazny/projects/nOS'
const DESIGN = `${NOS}/docs/plans/nos-cortex-organ-design.md`
const PLAN = `${NOS}/docs/plans/nos-cortex-organ-role.md`
const SCOPE = `${NOS}/files/anatomy/cortex/docs/specs/cortex-full-scope-decision.md`
const GAP = `${NOS}/files/anatomy/cortex/docs/C1-GAP-selfmodel.md`
const BRANCH = 'feat/cortex-organ'

const RULES = `
HARD CONSTRAINTS (violating any fails the stage):
- You work in the nOS repo at ${NOS}, on branch ${BRANCH} (it carries the P-4 organ under
  files/anatomy/cortex/). NEVER touch master/dev there, never tag.
- ${KEAP} is READ-ONLY to you. Read specs from it; never edit or delete anything in it —
  the KEAP docs cleanup happens post-transplant, not now.
- NO BLANK, NO WIPE, EVER. No \`nos --remove\`, no \`-e blank=true\`, no deletion under
  /Volumes/SSD1TB, no docker volume/image removal. The full blank verify (design §6 step 12
  as written) is an OPERATOR ceremony and is out of scope by decision.
- THE ONLY PERMITTED DEPLOY is \`ansible-playbook main.yml --tags cortex\` and it happens
  ONLY inside the Converge stage. Everywhere else: --syntax-check and tools/ci-local.sh only.
  Never run other tags, never converge the docker stacks.
- Two standing corrections from ${SCOPE} ("Two corrections") remain law: the organ mints its
  OWN db_identity (never KEAP's UUID), and it NEVER opens KEAP's keap.db — not read-only,
  not transitionally. The store is ~/cortex/data/cortex.db, materialised from git + the
  self-model generator (see ${GAP}).
- Step 13 (KEAP P-5: delete server/cortex-*.ts, flip the client to cortex_backend_url) is
  OUT OF SCOPE — a separate supervised PR in the KEAP repo. The keap-base env var here is
  render-only plumbing; KEAP's code must not be changed to read it yet.
- Node 22, npm (not pnpm). Any touched package-lock.json must pass \`npx npm@10 ci --dry-run\`
  before commit — npm 11 writes a lock npm 10 rejects.
- nOS commit convention (CLAUDE.md): Conventional Commits, subject ≤ 50 chars, body bullets
  ≤ 6 lines, surgeon tone, NO Co-Authored-By. Commit each stage on ${BRANCH}.
`

const SCOUT_SCHEMA = {
  type: 'object', additionalProperties: false, required: ['findings'],
  properties: {
    findings: { type: 'string' },
    anchors: { type: 'array', items: { type: 'object', additionalProperties: false, required: ['what', 'where'], properties: { what: { type: 'string' }, where: { type: 'string' }, note: { type: 'string' } } } },
    hazards: { type: 'array', items: { type: 'string' } },
  },
}
const FINDINGS_SCHEMA = {
  type: 'object', additionalProperties: false, required: ['findings'],
  properties: {
    findings: { type: 'array', items: { type: 'object', additionalProperties: false, required: ['title', 'file', 'severity', 'failure_scenario'], properties: { title: { type: 'string' }, file: { type: 'string' }, severity: { type: 'string', enum: ['major', 'minor'] }, failure_scenario: { type: 'string' } } } },
  },
}
const VERDICT_SCHEMA = {
  type: 'object', additionalProperties: false, required: ['real', 'why'],
  properties: { real: { type: 'boolean' }, why: { type: 'string' } },
}

phase('Scout')
const scouts = await parallel([
  () => agent(`${RULES}
READ-ONLY, no edits.
Scout how a HOST organ role is built so pazny.cortex clones the estate's shape instead of inventing one.
Read ${DESIGN} §2 (the anatomy-integration table) and §6 step 9 first. Then study:
- roles/pazny.bone/ in full (defaults, tasks/main+post, templates/bone.plist.j2, handlers, meta) — the
  host-daemon precedent: launchd label scheme (eu.thisisait.nos.*), state dir OUTSIDE the playbook tree,
  how the plist is loaded/reloaded, the handlers pattern;
- how Bone is imported in main.yml (the host block, import_role + tags) and where "right after pazny.bone,
  before Wing/Pulse" lands concretely;
- the Linux path: roles/pazny.linux.systemd_user tasks_from=ensure_unit and how Bone gates it on
  nos_service_manager == 'systemd-user';
- the Node build precedent: how files/anatomy/face is built (rsync excluding node_modules → npm ci →
  npm run build) and which role drives it;
- default.config.yml + default.credentials.yml naming ({{ global_password_prefix }}_pw_* pattern, where
  the "Knowledge / cortex" section already sits at default.config.yml:463);
- state/manifest.yml row shape (domain_var/port_var) and what makes a row loopback-only vs routed.
Report the concrete conventions, with file:line anchors, that pazny.cortex must copy.`,
    { label: 'scout:role', phase: 'Scout', schema: SCOUT_SCHEMA }),
  () => agent(`${RULES}
READ-ONLY, no edits.
Scout the plugin, Pulse, CI and test-shim conventions the later stages need.
- Plugins: files/anatomy/plugins/{bone-base,hermes-base,keap-base}/plugin.yml — the required keys
  (name/version/_NOS_PLUGIN/requires/gdpr/notification), how pulse_jobs: are declared and picked up by
  Pulse, how observability: blocks are shaped, and what keap-base currently renders into the KEAP
  container env (where cortex_backend_url would be added).
- Doctrine for a PURE-LOOPBACK organ: the design (${DESIGN} §5) says NO default Traefik route and no
  human /api surface — check how the manifest/traefik layer treats such rows (traefik_skip_ids?) so the
  plugin does not accidentally provision a router or an Authentik forward_auth provider it must not have.
- CI: .github/workflows/ci.yml — the face job (lines ~183-215) as the 1:1 model for a cortex job; which
  jobs gate merges; where a lockfile-sync check would live.
- tests/anatomy/: pick 2-3 shims that assert files/vars/templates for a role (e.g. test_agentkit_files_present.py)
  and report the conftest fixtures available.
- The organ itself: files/anatomy/cortex/package.json scripts (build/test/test:e2e), whether e2e needs a
  browser install step, and what scripts/ ships (recall-gate.mjs? ann-recall.mjs? keap_selfmodel_gen call path
  per ${GAP}).
Report with anchors; flag hazards (e.g. Playwright on CI, libsql native prebuilds on ubuntu-latest).`,
    { label: 'scout:wiring', phase: 'Scout', schema: SCOUT_SCHEMA }),
])
const brief = scouts.filter(Boolean).map((s, i) => `### Scout ${i + 1}\n${s.findings}\n\nANCHORS:\n${(s.anchors || []).map((a) => `- ${a.what} — ${a.where}${a.note ? ` (${a.note})` : ''}`).join('\n')}\n\nHAZARDS:\n${(s.hazards || []).join('\n')}`).join('\n\n')

phase('Role')
const role = await agent(`${RULES}
Build sequence step 9 — Ansible-ize the organ. NO deploy in this stage: gates are
\`ansible-playbook main.yml --syntax-check\` and \`tools/ci-local.sh\` (filter-load probe + syntax-check).

SCOUT REPORTS:
${brief}

Create roles/pazny.cortex/{defaults,tasks,templates,handlers,meta}/main.yml cloned from pazny.bone,
per ${DESIGN} §2:
- defaults: cortex_port: 8098 (loopback-only, beside Bone's 8099), cortex_runtime_dir (~/cortex),
  cortex_store_path (~/cortex/data/cortex.db — OUTSIDE the playbook tree, git clean must never reach it),
  cortex_ollama_url (default http://127.0.0.1:11434), cortex_launchd_label eu.thisisait.nos.cortex,
  node/nvm resolution matching how face's build finds Node 22.
- tasks: data dir → rsync files/anatomy/cortex/ into the runtime dir (exclude node_modules, exclude the
  store) → npm ci → npm run build → daemon runs the BUILT dist-server/index.js (tsx stays dev-only).
- templates/cortex.plist.j2 from bone.plist.j2: RunAtLoad + KeepAlive, ThrottleInterval 30,
  Soft/HardResourceLimits NumberOfFiles 8192 (libsql WAL holds db + -wal + -shm), env carrying the port,
  store path, ollama url and the two tokens.
- Linux: include_role pazny.linux.systemd_user tasks_from=ensure_unit (su_name=nos-cortex,
  su_exec_start=node dist-server/index.js), gated nos_service_manager == 'systemd-user'.
- default.credentials.yml: cortex_ro_token / cortex_rw_token as {{ global_password_prefix }}_pw_cortex_ro/rw;
  default.config.yml: install_cortex flag + the cortex_* vars in the existing "Knowledge / cortex" section.
- main.yml: import_role pazny.cortex in the host block right after pazny.bone, before Wing/Pulse, with the
  tag-inheritance pattern the estate uses (apply: tags + task tags) so --tags cortex reaches it.
- state/manifest.yml: a cortex row (domain_var/port_var) shaped so NO Traefik route is derived by default —
  follow whatever mechanism the scout found (skip list or row shape). Public route stays unbuilt.

Fail-closed invariants to preserve from the organ: no tokens configured ⇒ the daemon serves 503 on /agent —
the role must therefore ALWAYS provision both tokens. The store dir must be created by the role, never by git.

Commit (feat(cortex): ...). Report every file added/changed and both gate outputs.`,
  { label: 'role:ansible', phase: 'Role', effort: 'high' })

phase('Plugin')
const plugin = await agent(`${RULES}
Build sequence step 10 — plugin + Pulse + observability. Still NO deploy; gates: --syntax-check,
tools/ci-local.sh, and whatever plugin-loader validation the estate has (P0.12 loader tests in pytest).

ROLE REPORT:
${role}

Create files/anatomy/plugins/cortex-base/plugin.yml per ${DESIGN} §2 + §5, modeled on bone-base/hermes-base:
- requires: role pazny.cortex, feature_flag install_cortex, requires: [ollama] per the design;
- NO Traefik route, NO Authentik forward_auth provider — pure loopback (§5). If the plugin schema demands
  an authentik block, follow the loopback precedent the scout found rather than inventing one.
- pulse_jobs: keap-embed-sync — the pending → /api/embed → POST-back embed loop reaching host Ollama via
  cortex_ollama_url; the job calls the organ with the RW token. recall-gate.mjs exit codes stay
  0 pass / 1 fail / 4 SKIP (4 = no embedder, NEVER a pass).
- notification: routing block (A9 severity → channel) and observability: block per the estate shape;
- gdpr: Article 30 row — reasoning store, taxonomy + embeddings, operator-local, no EU transfer.
Then: keap-base plugin/role gains a cortex_backend_url env rendered into the KEAP container
(http://host.docker.internal:8098) — RENDER ONLY. KEAP's code does not read it yet; that is P-5.

Commit. Report the plugin.yml keys used, the Pulse job wiring, and the gate outputs.`,
  { label: 'plugin:cortex-base', phase: 'Plugin', effort: 'high' })

phase('CI')
const ci = await agent(`${RULES}
Build sequence step 11 — the CI gate.

PLUGIN REPORT:
${plugin}

1. Add a **cortex** job to .github/workflows/ci.yml modeled 1:1 on the face job: actions/setup-node@v4
   node-version 22, npm cache keyed on files/anatomy/cortex/package-lock.json, working-directory
   files/anatomy/cortex: npm ci → npm run build → npm test → node knowledge/onto1-conformance.mjs.
   Include npm run test:e2e ONLY if the scout confirmed Playwright browsers install cleanly on
   ubuntu-latest (npx playwright install --with-deps chromium); otherwise gate e2e behind the job with an
   honest comment, per design open-question 3 (Playwright rides CI, not host provisioning).
   Mind libsql: it is a native napi module — the linux-x64 prebuild must resolve in npm ci.
2. tests/anatomy/ pytest shims (test_cortex_*.py) following the estate's shim style: role files present
   (defaults/tasks/plist template), credentials pattern for the two tokens, plugin.yml loads + carries the
   required keys + declares keap-embed-sync, manifest row present and loopback-only, main.yml import site
   after pazny.bone, and package-lock.json in sync (validate with npx npm@10 ci --dry-run or the estate's
   existing lockfile-sync discipline).
3. Do NOT touch the retained KEAP repo's CI (it is read-only) — record in the report that the shared
   onto1-conformance gate on the KEAP side (design step 11, second half) is deferred to P-5.

Run the pytest shims + --syntax-check locally. Commit. Report job shape and real test counts.`,
  { label: 'ci:cortex-job', phase: 'CI', effort: 'high' })

phase('Converge')
const converge = await agent(`${RULES}
Build sequence step 12, TRIMMED BY DECISION: live converge + verify, NO blank run.
This is the ONLY stage allowed to deploy, and the only permitted command is:
    ansible-playbook main.yml --tags cortex
(from ${NOS}; the sudo vars_prompt may require interactivity — if the run cannot proceed
non-interactively, STOP, report the exact command for the operator, and verify against whatever the
operator then converges. Do NOT work around the prompt, do NOT run other tags.)

CI REPORT:
${ci}

After the converge, verify the LIVE organ:
1. launchctl reports eu.thisisait.nos.cortex loaded and running; the process is node dist-server/index.js.
2. GET http://127.0.0.1:8098/health — ontologyVersion is onto1:76d1f3ad728b382b, opcodeRegistryHash is the
   cx1: hash the repo pins, databaseId is non-empty AND is NOT KEAP's UUID (read KEAP's via the live
   container's /health or app_settings — READ-ONLY — and assert inequality; the organ minted its own).
3. Fail-closed: a tokenless request to POST /agent/v1/validate is refused (401/503 per the organ's
   contract), and the RO token authorizes it.
4. Coverage parity per ${GAP}: the composed tree carries 1841 nodes / 1051 ext / 1841 descriptions and the
   nos slug root exists — the self-model generator ran at materialisation.
5. A spot-check of nos.* operands resolves (not unknown_operand) — the 261-case failure mode stays dead.
6. The estate is untouched: docker ps container count and health before vs after the converge are equal;
   nothing under /Volumes/SSD1TB changed; KEAP's container still healthy on :8091.
7. Idempotence: a second --tags cortex run reports zero changed tasks (or explain every changed one).

Nothing to commit unless verification exposed a defect in the role — fix, re-converge, then commit the fix.
Report every check with its ACTUAL output, including any operator handoff.`,
  { label: 'converge:cortex', phase: 'Converge', effort: 'high' })

phase('Docs')
const docs = await agent(`${RULES}
Consolidate the cortex paper trail. KEAP is READ-ONLY — you copy FROM it and ledger the rest; the KEAP-side
deletion/cleanup happens post-transplant, explicitly not now.

1. Inventory every cortex-relevant spec:
   - KEAP ${KEAP}/docs/specs/: cortex-validate.md, cortex-full-scope-decision.md, onto1-composition-contract.md,
     cortex-backend-boundary-reply.md, nos-cortex-lang-review-02.md, recall-gate.md, ontology-anchoring.md,
     nos-selfmodel-keap-contract.md, nos-selfmodel-reply-01.md, durability-and-integrity.md,
     handoff-nos-agent-2026-07-24.md, conditional-relations.md (judge each; some are product-side and stay).
   - nOS docs/plans/: nos-cortex-organ-design.md, nos-cortex-lang.md, nos-cortex-lang-wing-executor.md,
     cortex-backend-boundary-{decision,rfc}.md, ${PLAN}.
   - Already vendored on ${BRANCH}: files/anatomy/cortex/docs/specs/ (5 specs) + C1-GAP-selfmodel.md.
2. For each: status ∈ {done, superseded (by what), live-here (organ runtime doctrine), live-keap (product),
   split (which parts move)}. The scope decision itself supersedes cortex-backend-boundary-reply.md §3 — say so.
3. COPY the still-live organ-side specs that are missing from files/anatomy/cortex/docs/specs/ (candidates:
   recall-gate.md, ontology-anchoring.md, nos-selfmodel-keap-contract.md — verify against the inventory,
   don't trust this list) with a one-line provenance header (source repo + commit).
4. Write the ledger to ${NOS}/docs/plans/cortex-specs-ledger.md — one table, the four statuses above, and a
   "post-transplant cleanup" column naming what gets deleted from KEAP once C4 lands.
5. Update ${PLAN} status to reflect this stage landing.

Commit (docs(cortex): ...). Report the ledger counts per status.`,
  { label: 'docs:ledger', phase: 'Docs', effort: 'high' })

phase('Verify')
const LENSES = [
  { key: 'converge-safety', prompt: `Attack the role's converge behavior. Hunt: non-idempotent tasks (rsync flags, npm ci triggers, plist rewrites causing restart loops); anything that could delete or shadow ~/cortex/data (the reasoning store must survive git clean AND a re-converge); ordering hazards (organ imported before Bone, or Wing/Pulse starting before the daemon is up); tag leaks (--tags cortex dragging other roles via always-tags, or --tags keap now touching cortex); and Linux-path breakage (systemd_user unit gated correctly).` },
  { key: 'security', prompt: `Attack the token and disclosure surface of the ROLE + PLUGIN layer (the daemon itself was audited in P-4). Verify: tokens land only via the plist/unit env and {{ global_password_prefix }}_pw_cortex_* credentials — never in logs, never in files/anatomy/cortex, never world-readable (plist file mode); no Traefik route or Authentik provider was accidentally derived from the manifest row; the daemon still binds 127.0.0.1 only after the role's env is applied; the Pulse job carries RW only where it upserts embeddings; the organ's db_identity is its own (no carry-over crept in via role vars).` },
  { key: 'ci-honesty', prompt: `Attack the CI gate's honesty. Would the cortex job actually FAIL on: a broken package-lock.json (npm-10 incompatibility), an onto1 digest drift, a deleted test, a libsql prebuild miss on linux-x64? Are the tests/anatomy shims asserting real invariants (import site, loopback-only row, token pattern) or mere file existence? Is anything continue-on-error or conditionally skipped in a way that can silently go green?` },
]
const verified = await pipeline(
  LENSES,
  (l) => agent(`${RULES}
You are an adversarial reviewer. Read the diff of this workflow's stages on ${BRANCH} (the role/plugin/CI/docs
commits — git log will show them on top of the P-4 series) and the files it touches. Find REAL defects with a
concrete failure scenario — an input or state producing a wrong result. "This could be risky" is not a
finding; an empty list is a fine answer.

${l.prompt}`,
    { label: `verify:${l.key}`, phase: 'Verify', schema: FINDINGS_SCHEMA, effort: 'high' }),
  (res, lens) => parallel(((res && res.findings) || [])
    .slice().sort((a, b) => (a.severity === b.severity ? 0 : a.severity === 'major' ? -1 : 1)).slice(0, 3)
    .map((f) => () => agent(`${RULES}
READ-ONLY. Try to REFUTE this claimed defect on ${BRANCH}:
  ${f.title} — ${f.file}
  scenario: ${f.failure_scenario}
Read the actual code. Default to real=false when you cannot trace the failure concretely.`,
      { label: `refute:${lens.key}`, phase: 'Verify', schema: VERDICT_SCHEMA })
      .then((v) => ({ ...f, lens: lens.key, verdict: v })))),
)
const confirmed = verified.flat().filter(Boolean).filter((f) => f.verdict && f.verdict.real)
log(`verify: ${verified.flat().filter(Boolean).length} claimed, ${confirmed.length} confirmed`)

phase('Fix')
let fixReport = 'no confirmed findings'
if (confirmed.length) {
  fixReport = await agent(`${RULES}
Fix these confirmed defects. No suppressions, no widened types, no deleted tests. If a fix touches the role,
re-run --syntax-check + the pytest shims; if it changes live behavior, the Converge stage's checks 1-7 must
be re-verified (re-converge with --tags cortex only if strictly required, and say so).

${confirmed.map((f, i) => `${i + 1}. [${f.severity}] (${f.lens}) ${f.title}\n   ${f.file}\n   ${f.failure_scenario}\n   refuter: ${f.verdict.why}`).join('\n\n')}

For each, add or extend a test/shim that fails without the fix. If a finding is wrong, say so with the code
reason instead of changing anything. Report real numbers.`,
    { label: 'fix:confirmed', phase: 'Fix', effort: 'high' })
}

phase('Report')
const report = await agent(`${RULES}
Final honest report for ${BRANCH}. Run every check and report ACTUAL numbers, not intentions:
  ansible-playbook main.yml --syntax-check · tools/ci-local.sh · the tests/anatomy cortex shims ·
  (in files/anatomy/cortex) npm run build + npm test + node knowledge/onto1-conformance.mjs ·
  curl the live /health and restate its ontologyVersion/databaseId/opcodeRegistryHash ·
  docker ps container count + health.
Confirm branch hygiene: nothing touched nOS master/dev, nothing under ${KEAP} was modified (git status there
must be clean), the only deploy that ran was --tags cortex.
Then state what is deliberately NOT done: the full blank verify (operator ceremony), step 13 / KEAP P-5
cutover (separate supervised PR), the KEAP-side conformance CI gate (rides P-5), the KEAP docs cleanup
(post-transplant), C2-C4, and design open questions still open (public route, backup of ~/cortex/data).
Update ${PLAN}'s status block accordingly and commit it (docs(cortex): ...).`,
  { label: 'report:final', phase: 'Report', effort: 'high' })

return { role: role.slice(0, 2500), plugin: plugin.slice(0, 2000), ci: ci.slice(0, 2000), converge: converge.slice(0, 3000), docs: docs.slice(0, 2000), claimed: verified.flat().filter(Boolean).length, confirmed: confirmed.map((f) => ({ lens: f.lens, severity: f.severity, title: f.title })), fixReport: String(fixReport).slice(0, 2500), report }
