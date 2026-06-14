export const meta = {
  name: 'v07-overnight-review',
  description: 'Overnight audit → adversarial verify → safe gated fixes + v0.7 plans + RAG-memory MVP scaffold',
  whenToUse: 'Unsupervised overnight push toward nOS v0.7. Nothing destructive; safe fixes commit to a branch, big items become plans.',
  phases: [
    { title: 'Audit' },
    { title: 'Verify' },
    { title: 'Implement' },
    { title: 'Plans' },
    { title: 'RAG-MVP' },
    { title: 'Synthesis' },
  ],
}

// ── Doctrine handed to every agent ───────────────────────────────────────────
const REPO = '/Users/pazny/projects/nOS'
const DOCTRINE = `
You are working in the nOS repo (${REPO}) — an Ansible playbook for a self-hosted
FOSS "AI house" (AIT). Read CLAUDE.md for architecture + doctrine. Hard rules,
NON-NEGOTIABLE because this runs UNSUPERVISED overnight:
- NEVER run anything destructive: no blank=true, no docker rm/prune, no service
  deletes, no DB drops, no git push, no force, no deleting operator data. No live
  mutation that isn't trivially reversible.
- Repo edits only. Live system = READ-ONLY (docker ps/inspect, curl, occ get, API
  GETs, psql SELECT). Never write to the live system.
- Every code fix MUST ship with a pytest anatomy gate (tests/anatomy/) AND keep
  the suite green + ansible-playbook main.yml --syntax-check clean. If you cannot
  gate it, it is a PLAN not a fix.
- Stock-Jinja vars trap: any new var in default.config.yml/default.credentials.yml
  must use stock filters + a real default (test_config_stock_jinja_only.py).
- Conventional Commits, subject ≤50 chars, surgeon-tone body ≤6 bullets, NO
  Co-Authored-By, NO --author. (Commits land on the branch only — never push.)
- Machinery doctrine: changes propagate via commits + the playbook, never a hack
  to the live system.
`.trim()

const FINDING_SCHEMA = {
  type: 'object',
  properties: {
    dimension: { type: 'string' },
    findings: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          id: { type: 'string', description: 'short-kebab-id' },
          title: { type: 'string' },
          severity: { type: 'string', enum: ['critical', 'high', 'medium', 'low', 'info'] },
          kind: { type: 'string', enum: ['bug', 'security', 'tech-debt', 'docs', 'gap', 'opportunity'] },
          evidence: { type: 'string', description: 'file:line or live-probe output proving it' },
          proposed_fix: { type: 'string' },
          fixClass: { type: 'string', enum: ['mechanical', 'moderate', 'architectural'], description: 'mechanical = safe to auto-implement with a gate; architectural = plan only' },
          risk: { type: 'string' },
        },
        required: ['id', 'title', 'severity', 'kind', 'evidence', 'proposed_fix', 'fixClass'],
      },
    },
  },
  required: ['dimension', 'findings'],
}

const VERDICT_SCHEMA = {
  type: 'object',
  properties: {
    id: { type: 'string' },
    real: { type: 'boolean', description: 'is the finding genuinely true + reproducible' },
    fix_safe: { type: 'boolean', description: 'is the proposed fix correct AND safe to apply unsupervised' },
    fixClass: { type: 'string', enum: ['mechanical', 'moderate', 'architectural'] },
    reason: { type: 'string' },
  },
  required: ['id', 'real', 'fix_safe', 'fixClass', 'reason'],
}

const DIMENSIONS = [
  { key: 'security', prompt: 'Security + the remediation backlog (docs/llm/security/remediation-queue.json). Image pins vs running tags, hardening gaps, header-trust isolation, secrets hygiene. Cross-check against what is ACTUALLY running (docker inspect image tags).' },
  { key: 'sso', prompt: 'SSO completeness across all three buckets (native_oidc / header_oidc / forward_auth) AFTER today\'s fixes (Gitea CLI register, Nextcloud user_oidc, HA auth_oidc, NC IPv6, onlyoffice connector). Live-probe each service the way docs/sso-and-attribution.md defines. Find any remaining service whose SSO is wired-but-broken. The silent-failure pattern (no_log+failed_when:false) needs a loud verify everywhere it is missing.' },
  { key: 'tofu', prompt: 'OpenTofu/Authentik robustness. The post-blank state desync was fixed (blank now rm-s the state) but two gaps remain: tofu has NO automatic adopt/reconcile for an existing tenant, and the destroy-guard does NOT catch dangerous UPDATEs to wrong pks. Design + (if mechanical) gate these. Read tasks/tofu-authentik.yml + docs/opentofu-authentik-cutover.md.' },
  { key: 'backlog', prompt: 'Triage every open item in docs/active-work.md (infisical MTI render, portainer SSO unverified, advisor/architect actor-id naming, PG 16->17, gov P0s, etc.). For each: still valid? mechanical fix available? evidence. Be concrete.' },
  { key: 'macos27', prompt: 'macOS 27 readiness — the operator upgrades soon. Audit Darwin version gates, Docker Desktop assumptions, Homebrew formula pins, Python pins (.python-version 3.13.13), launchd/launchctl usage, host-gateway/virtiofs assumptions, mkcert/dnsmasq. What is likely to break on macOS 27 and what guards/pins would harden it. This is high-value forward-looking work.' },
  { key: 'docs', prompt: 'Docs + devlog integrity AFTER the devlog epic. Broken intra-repo links, stale references to archived docs, docs/systems generated-card drift, the devlog bundle freshness, active-work ≤150 line ceiling. Any doc claiming something that the code no longer does.' },
  { key: 'tests', prompt: 'Test/gate coverage gaps. Which recent changes (devlog, WP RBAC, euro-office, the SSO fixes, the tofu blank-reset) lack a pinning anatomy gate or have a weak one. Where would a regression slip through. Propose concrete new gates.' },
  { key: 'euro-office', prompt: 'euro-office full-swap readiness (v0.7 headline). It runs as an onlyoffice_image flip today. What is needed to rename pazny.onlyoffice -> pazny.eurooffice cleanly (role, plugin manifest, manifest row, registry, gates, docs) once upstream ships stable, WITHOUT breaking the JWT embeds (Nextcloud/BookStack/Outline) or the blank-safe seed. Deepen the Nextcloud<->euro-office<->Documenso collaboration story. Output a concrete migration plan + any mechanical prep that is safe now.' },
  { key: 'rag', prompt: 'RAG memory feasibility (THE v0.7 MVP, build it later this run). Qdrant is installed (forward_auth gated). The Librarian agent is contract-only. Design a LOCAL ingest pipeline over the repo + devlog + docs + runbooks into Qdrant, with embeddings from a local model (Ollama MLX) and a query path the agents + operator use. Identify the exact files/roles to add, the schema, the embedding model, and the smallest working MVP. Output a build-ready design.' },
  { key: 'conductor', prompt: 'Closed-loop conductor readiness (v0.7 headline). The conductor agent + Pulse + Wing approvals exist; the SCHEDULED closed loop (scout->remediator->conductor on a cadence, operator approves) is queued. What exactly is missing to make it live + safe (manual-over-auto doctrine: destructive stays operator-gated). Output a concrete activation plan.' },
  { key: 'ci-release', prompt: 'CI + release pipeline health. The dev light lane, the Integration wet-tests, tools/ci-local.sh, the release flow (dev->master admin merge, tag, GH Pages devlog publish). Any gap, flake, or missing gate that would let a bad release through. Read .github/workflows/ci.yml + pages.yml.' },
  { key: 'quality', prompt: 'Code quality + consistency sweep: dead code, copy-paste drift across the pazny.* roles + anatomy plugins, inconsistent error handling, the failed_when:false+no_log silent-failure anti-pattern wherever it lacks a loud verify, TODO/FIXME debt. Prioritise the highest-leverage cleanups.' },
]

// ── Phase 1: Audit (parallel fan-out) ────────────────────────────────────────
phase('Audit')
log(`Auditing ${DIMENSIONS.length} dimensions in parallel`)
const audits = await parallel(
  DIMENSIONS.map((d) => () =>
    agent(
      `${DOCTRINE}\n\n## Your dimension: ${d.key}\n${d.prompt}\n\nBe exhaustive and CONCRETE — every finding needs file:line or live-probe evidence. Distinguish mechanical (safe to auto-fix with a gate) from architectural (plan only). Return the structured findings.`,
      { label: `audit:${d.key}`, phase: 'Audit', schema: FINDING_SCHEMA, agentType: 'Explore' }
    )
  )
)
const allFindings = audits.filter(Boolean).flatMap((a) => (a.findings || []).map((f) => ({ ...f, dimension: a.dimension })))
log(`Collected ${allFindings.length} findings across ${audits.filter(Boolean).length} dimensions`)

// ── Phase 2: Adversarial verify (parallel; majority-real + safe) ─────────────
phase('Verify')
const verified = await parallel(
  allFindings.map((f) => () =>
    parallel([
      () => agent(`${DOCTRINE}\n\nADVERSARIALLY verify this finding — default to real=false unless the evidence holds. Re-check the evidence yourself (read the file / re-probe). Also judge fix_safe: is the proposed fix correct AND safe to apply UNSUPERVISED tonight?\n\nFinding: ${JSON.stringify(f)}`, { label: `verify:${f.id}:a`, phase: 'Verify', schema: VERDICT_SCHEMA, agentType: 'Explore' }),
      () => agent(`${DOCTRINE}\n\nSecond independent reviewer. Verify this finding from a DIFFERENT angle (does it reproduce? does the fix have side effects? is it already handled elsewhere?). Default real=false if unsure.\n\nFinding: ${JSON.stringify(f)}`, { label: `verify:${f.id}:b`, phase: 'Verify', schema: VERDICT_SCHEMA, agentType: 'Explore' }),
    ]).then((votes) => {
      const v = votes.filter(Boolean)
      const real = v.filter((x) => x.real).length >= Math.ceil(v.length / 2) && v.length > 0
      const safe = real && v.every((x) => x.fix_safe)
      const fixClass = v.map((x) => x.fixClass).sort()[0] || f.fixClass
      return { ...f, confirmed: real, fix_safe: safe, fixClass, votes: v }
    })
  )
)
const confirmed = verified.filter(Boolean).filter((f) => f.confirmed)
const autoFixable = confirmed.filter((f) => f.fix_safe && f.fixClass === 'mechanical')
const planItems = confirmed.filter((f) => !autoFixable.includes(f))
log(`Confirmed ${confirmed.length} findings → ${autoFixable.length} safe-mechanical (auto-fix), ${planItems.length} → plans`)

// ── Phase 3: Safe implement (SEQUENTIAL on a branch, each gated + committed) ──
phase('Implement')
await agent(`${DOCTRINE}\n\nCreate a fresh work branch off dev WITHOUT switching away from any in-progress work: run \`cd ${REPO} && git fetch origin && git checkout -B feat/v0.7-overnight origin/dev\`. Confirm the branch is created and the tree is clean. Return the resulting \`git status -sb\` first line.`, { label: 'branch:setup', phase: 'Implement' })

const implResults = []
for (const f of autoFixable) {
  const r = await agent(
    `${DOCTRINE}\n\nYou are on branch feat/v0.7-overnight. Implement EXACTLY this one confirmed, mechanical, safe fix — nothing more:\n${JSON.stringify(f)}\n\nSteps: (1) make the minimal edit; (2) add/extend a pytest gate in tests/anatomy/ that pins it; (3) run \`python3 -m pytest tests/anatomy/<your-gate> -q\` AND \`ansible-playbook main.yml --syntax-check\` — both MUST pass; (4) if green, \`git add\` the touched files + \`git commit\` (Conventional, surgeon-tone, NO push); if NOT green, REVERT your edits (git checkout -- .) and report failure. Return: {applied:boolean, commit:string, gate:string, note:string}.`,
    { label: `fix:${f.id}`, phase: 'Implement' }
  )
  implResults.push({ id: f.id, title: f.title, result: r })
}
log(`Implement phase done: ${implResults.length} mechanical fixes attempted`)

// ── Phase 4: Plans for moderate/architectural items (parallel drafts) ────────
phase('Plans')
const plans = await parallel(
  planItems.map((f) => () =>
    agent(`${DOCTRINE}\n\nWrite a concrete, review-ready implementation PLAN (do NOT implement) for this confirmed item. Include: problem/why, the exact files/roles to touch, the approach, risks, the gates it needs, and a verification recipe. Write it to docs/plans/v07-${f.id}.md (create docs/plans/ if needed) and commit it to feat/v0.7-overnight. Return the file path + a 2-sentence summary.`, { label: `plan:${f.id}`, phase: 'Plans' })
  )
)
log(`Drafted ${plans.filter(Boolean).length} plans`)

// ── Phase 5: RAG-memory MVP scaffold (the v0.7 headline) ─────────────────────
phase('RAG-MVP')
const ragDesign = audits.filter(Boolean).find((a) => a.dimension === 'rag')
const ragMvp = await agent(
  `${DOCTRINE}\n\nBuild a REVIEWABLE MVP SCAFFOLD (not a live deployment) of the RAG-memory feature for the AIT house, on branch feat/v0.7-overnight. Use the audit design as your spec: ${JSON.stringify(ragDesign?.findings || []).slice(0, 4000)}.\n\nDeliver, all behind a feature flag DEFAULT-OFF (install_rag_memory / rag_memory_enabled), repo-only, never touching the live system:\n- a thin role or anatomy plugin for the ingest pipeline (repo+devlog+docs -> chunks -> embeddings via a LOCAL Ollama MLX embedding model -> Qdrant collection),\n- the query helper (a tool the Librarian agent + operator call),\n- wiring notes for flipping the Librarian agent from contract-only to live,\n- pytest anatomy gates pinning the contract (flag default off, schema, no-secrets),\n- a docs/plans/v07-rag-memory.md design doc + a devlog draft.\nMUST keep the suite green + syntax-check clean. Commit incrementally (NO push). The bar is "operator can read it, run the gates, and decide to wire it" — not a running service. Return what you built + the commits.`,
  { label: 'rag-mvp:build', phase: 'RAG-MVP' }
)

// ── Phase 6: Synthesis ───────────────────────────────────────────────────────
phase('Synthesis')
const applied = implResults.filter((r) => r.result && /applied|commit/i.test(JSON.stringify(r.result)))
const summary = await agent(
  `${DOCTRINE}\n\nWrite the overnight review report to docs/overnight-review-2026-06.md and commit it to feat/v0.7-overnight. Cover: (1) audit scope (${DIMENSIONS.length} dimensions), (2) confirmed findings by severity, (3) mechanical fixes applied (commits), (4) plans drafted (docs/plans/), (5) the RAG-memory MVP, (6) a prioritised "what to do next for v0.7" list aligned to the headline trio (RAG memory, closed-loop conductor, euro-office full-swap), (7) anything that needs operator decision. Be honest about what was NOT done. Data:\nFindings: ${JSON.stringify(confirmed).slice(0, 6000)}\nImplemented: ${JSON.stringify(applied).slice(0, 3000)}\nPlans: ${JSON.stringify(plans.filter(Boolean)).slice(0, 2000)}\nRAG: ${JSON.stringify(ragMvp).slice(0, 2000)}\nReturn the report path + a tight executive summary for the operator's morning.`,
  { label: 'synthesis', phase: 'Synthesis' }
)

return {
  branch: 'feat/v0.7-overnight',
  findings_total: allFindings.length,
  confirmed: confirmed.length,
  mechanical_fixes: autoFixable.length,
  plans: plans.filter(Boolean).length,
  report: summary,
}
