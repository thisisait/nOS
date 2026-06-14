# Overnight review — v0.7 push (2026-06-13/14)

> Synthesis of the autonomous overnight review run (workflow
> `tools/workflows/v07-overnight-review.mjs`, run `wf_4d8e167f-579`). Everything
> below landed on branch **`feat/v0.7-overnight`** — nothing was pushed and the
> live system was only ever read. The morning brief for the operator.

**Headline:** the review audited 12 dimensions, surfaced **158 findings**,
adversarially confirmed **144**, shipped **41 mechanical code/test/CI fixes**
(each with a pinning gate), drafted **48 review-ready plans**, and produced a
**RAG-memory architecture** design. The suite is green on the branch
(`1466 passed, 3 skipped`). The big v0.7 features — RAG ingest, the closed-loop
conductor, the euro-office full-swap — are **planned, not yet implemented**;
that is the honest state and the next-steps section says how to land them.

---

## 1. Audit scope — 12 dimensions

Each dimension was audited by an independent agent, then every finding was
re-checked by a majority-vote adversarial verifier (a finding survives only if
≥½ of the skeptics confirm it AND all of them agree the fix is safe).

| # | Dimension | Focus |
|---|-----------|-------|
| 1 | **security** | remediation-queue vs running image tags, header-trust isolation, secrets hygiene |
| 2 | **sso** | all three buckets after today's fixes; remaining wired-but-broken SSO; missing loud verifies |
| 3 | **tofu** | post-blank desync (fixed), no auto-adopt, destroy-guard blind to dangerous UPDATEs |
| 4 | **backlog** | every open `docs/active-work.md` item triaged |
| 5 | **macos27** | Darwin-27 readiness — the operator upgrades soon |
| 6 | **docs** | post-devlog link integrity, card drift, bundle freshness, active-work ceiling |
| 7 | **tests** | gate-coverage gaps for the recent changes |
| 8 | **euro-office** | full-swap readiness (headline) |
| 9 | **rag** | RAG-memory MVP feasibility + build-ready design (headline) |
| 10 | **conductor** | closed-loop conductor activation (headline) |
| 11 | **ci-release** | dev lane, Integration wet-tests, release flow, Pages publish |
| 12 | **quality** | dead code, copy-paste drift, the silent-failure anti-pattern |

158 raw findings → **144 confirmed** after adversarial verification (14 refuted
or judged unsafe-to-touch and dropped). Confirmed findings split into
**41 safe-mechanical** (auto-fixed below) and the rest → **plans**.

---

## 2. Confirmed findings — distribution

The per-finding severity scores lived in the verifier agents' results and were
not all persisted to the branch, so the table below characterises the confirmed
set by **theme and committed evidence** rather than inventing a per-severity
tally. (The verifier's `fix_safe` + `fixClass` gates ARE durable — they drove
the auto-fix/plan split.)

- **Security (high-impact):** stale CVE pins vs running tags (postgres, open-webui,
  redis), the version-pin **shadow trap** (role-default bumped but `default.config.yml`
  wins — a dead pin), a real **secret leak** (mariadb test-db drop logged the
  password), header-trust isolation gaps. → 9 mechanical fixes + the
  `remediation-queue-pending-14` triage plan.
- **SSO (high-impact, operator-visible):** the `no_log: true` + `failed_when: false`
  **silent-failure anti-pattern** survives in several native_oidc post-setup
  paths (WordPress, Portainer, Home Assistant, Jellyfin) — a broken registration
  reads as success. → 3 loud-verify fixes landed + 8 SSO plans for the rest.
- **OpenTofu (correctness):** the destroy-guard was blind to dangerous in-place
  **UPDATEs** to the wrong pk (the exact failure mode behind the post-blank
  desync); no auto-adopt for an existing tenant. → 7 tofu fixes + 2 plans.
- **macOS 27 (forward-looking):** the largest plan cluster (14). Nothing is
  broken today, but `.python-version 3.13.13`, Homebrew formula pins,
  Docker-Desktop assumptions, launchd schema, VirtioFS/host-gateway, mkcert
  CAROOT and `interpreter_python` auto-discovery are all **untested against
  Darwin 27** and several are likely to bite on upgrade. → 14 plans, 0 premature
  fixes (correctly — these need the actual OS to verify).
- **Gov / GDPR (architectural):** retention is declared-but-not-enforced; ISDS +
  NIA/eIDAS federation is still greenfield. → 2 plans.
- **Docs / tests / quality (low-risk hygiene):** dead links, card drift, missing
  gates. → mechanical fixes + the devlog-epic + naming plans.

---

## 3. Mechanical fixes applied (41 commits, each gated)

All on `feat/v0.7-overnight`, oldest → newest. Every one carries a pytest gate
in `tests/anatomy/` and passed `--syntax-check` before commit.

**Security / CVE / secrets (9)**
- `79940d14` postgres pin `16.13 → 16.14-alpine` (REM-088)
- `1f2d7017` open-webui tool-call retry cap (REM-055)
- `715565c7` gate REM-047 X-Authentik header overwrite
- `8d2f3dc0` gate REM-048 nginx fail-closed locations
- `b4900f0b` gate REM-003 redis `requirepass` + client auth
- `de0ef3b0` pin the version-shadow source-of-truth comment
- `5f46a104` require-pin hedgedoc + paperclip postgres SSL
- `13b47ac2` **no_log the mariadb test-db drop (secret leak)**
- `fa0a1c17` sync mariadb CVE citation across 3 sites

**SSO loud-verify (3)**
- `8b0f1f54` verify WordPress OIDC plugin install
- `d260491c` make Portainer OAuth2 verify loud
- `ef798be8` diagnose role-side Portainer OAuth2 JWT failures headless

**OpenTofu robustness (7)**
- `d4647b49` **destroy guard now catches dangerous in-place UPDATEs**
- `4feb1f7e` adopt-path imports outpost attachments
- `cf704a23` gate registry `enabled` exprs vs `install_*` vars
- `1ecbbada` wipe timestamped tofu state backups on blank
- `b33e0eb9` name destroyed resources before the guard refuses
- `943baf35` pin forward_auth rows carry no oauth2 fields
- `f0f642ff` gate tofu state-reset on blank

**Blank-reset hardening (6)**
- `8b40a098` wipe snappymail + spacetimedb bind dirs
- `49248252` sync confirmation prompt with real wipe behavior
- `6fd9513f` sync DB auto-deps with main.yml
- `48ebd034` evict all anatomy LaunchAgent plists on reset
- `8a713bf1` gate post_blank hook order + tolerance
- `fe1be4f8` pin blank-safety of WP secret persistence

**Infra / handlers / CI / agents (16)**
- `2c3dc2f4` pin `creates:` guard on the pg16→17 dump
- `04ca93cb` guard dnsmasq restart handler with plist check
- `87bea0c7` pin frankenphp + version preflight gate (wing)
- `3f29793b` pin IPv6-disable sysctl block (nextcloud)
- `0f2c100c` pin mu-plugins blank-safety mount (wordpress)
- `91d22fef` parameterize onlyoffice compose service name for rename
- `992dfab9` restart handlers must fail loud
- `0531644a` guard `changed_when` on register defined
- `b07b02e0` dedupe Wait-for-API into a shared include
- `74a34801` hub: harvest `kind:backend`, drop hardcoded slugs
- `e5f9c46f` pin conductor closed-loop pulse jobs
- `d48ed37b` pin per-agent exit-code contract
- `172b4894` gate notification routing per agent
- `14e5dbb4` cap integration jobs at 45-min timeout
- `2bf636bc` gate Pages publish on release-artifact validation
- `b2232784` bump Pages shared actions to v6, gate the drift

---

## 4. Plans drafted (48 → `docs/plans/v07-*.md`)

Review-ready, NOT implemented. Each carries problem/why, exact files to touch,
approach, risks, the gates it needs, and a verification recipe.

- **macOS 27 horizon (14):** ansible-core 2.24 jump · defaults-write TCC sandbox ·
  Docker-Desktop version floor · Homebrew tap stability · `interpreter_python`
  hard-pin · launchd plist schema · mkcert CAROOT single-source · no-version
  testing matrix · Ollama MLX + llama-server preflight · pmset posture ·
  Python 3.14 incompat · softwareupdate report-only script · version-gate
  coverage · VirtioFS workaround consolidation.
- **SSO (9):** doctrine-test covers modes-not-wiring · Gitea OAuth CLI
  register+verify · HA config-block rendered-no-verify · HA auth_oidc runtime
  verify · Jellyfin SSO-Auth.xml order-vuln · Jellyfin XML silent-failure ·
  native_oidc missing post-setup hooks · Nextcloud OIDC verify · Superset/Metabase
  no-OIDC ceilings.
- **Security (8):** authentik version freshness · docker socket-proxy ·
  freepbx vendor-blocked risk-gate · log-rotation · n8n RCE regression-floor ·
  open-webui pyodide pin · uptime-kuma SSTI (REM-073) · WordPress unauth endpoints.
- **Tofu / state (4):** no-auto-adopt reconcile preflight · state observed-but-never-
  reconciled · adopt-path attachment import · D1 `{{ vars }}` retirement.
- **Euro-office (3):** onlyoffice→eurooffice first-class image toggle ·
  JWT-embed compatibility lock · euro-office blank-safe DB-seed gate.
- **Gov / GDPR (2):** ISDS + NIA/eIDAS greenfield scaffold · retention enforcement
  (metadata → action).
- **Blank-reset tests (2):** external-storage override contract · nginx-config
  removal (platform-aware).
- **Single (6):** Tier-2 update-semantics gate · devlog epic A/B/C residuals ·
  advisor/architect agent naming · WordPress RBAC demotion edge case ·
  repoint dead `agent-operable-nos.md` links · (RAG design, see §5).

---

## 5. RAG-memory MVP

`docs/rag-architecture.md` (236 lines) + gate `test_rag_architecture_doc.py`.

**What it is:** a build-ready architecture for the AIT house's memory substrate —
corpus (repo + devlog + docs + runbooks) → chunks → **local Ollama MLX
embeddings** → **Qdrant** (already installed, forward_auth-gated) → a query path
the Librarian agent + operator call, with a Bone API surface and GDPR posture
(legitimate-interests, 365-day retention, Art-17 redact+delete).

**Honest seam:** the **substrate is LIVE** (Qdrant + Bone + Wing exist); the
**ingest pipeline + Librarian runner are DEFERRED** — Bone today takes a
pre-computed vector, it does not embed. The overnight run produced the *design
doc*, not the flag-gated ingest role/plugin scaffold the RAG phase was scoped to
build (the implementation agents ran out of quota). So this is "operator can read
it, run the gate, and decide to wire it" — the design bar, not running code.

---

## 6. What to do next for v0.7 — prioritised

The headline trio, in build order:

1. **RAG memory (highest leverage, design done).** Land the flag-gated
   (`install_rag_memory` default-off) ingest role/plugin from
   `docs/rag-architecture.md`: chunker → Ollama MLX embed → Qdrant upsert, plus
   the query helper and the Librarian flip from contract-only to live. This is the
   one headline whose design is already build-ready — it's the cleanest first win.
2. **euro-office full-swap (waiting on upstream stable).** Mechanical prep is
   already safe and partly landed (`onlyoffice_service_name` var, blank-safe seed,
   JWT-embed lock plan). When upstream ships the first stable tag, execute the
   `pazny.onlyoffice → pazny.eurooffice` rename per
   `docs/plans/v07-euro-office-pilot-onlyoffice-toggle.md` — role, plugin manifest,
   manifest row, registry, gates, docs — without breaking the JWT embeds.
3. **Closed-loop conductor (needs the safety design first).** The conductor agent,
   Pulse, and Wing approvals exist; the scheduled scout→remediator→conductor loop
   is the gap. The pulse-jobs contract gate already landed (`e5f9c46f`); the
   activation plan must keep destructive actions operator-gated
   (manual-over-auto / dry-run-default doctrine — memory `feedback-destructive-op-safety`).

**Then drain the plan backlog by risk:** macOS 27 cluster **before** the operator
upgrades (14 plans — `interpreter_python` pin, Python 3.14, VirtioFS, launchd are
the likely breakers); the 8 security plans (uptime-kuma SSTI, socket-proxy,
authentik freshness); the SSO loud-verify plans to finish killing the
silent-failure pattern.

---

## 7. Operator decisions needed

- **Merge gate for this branch.** 101 commits (41 gated fixes + 48 plans + RAG
  design + supporting docs/synthesis). Suite is green (`1466 passed, 3 skipped`).
  The fixes are independently mergeable; the plans are inert docs. Recommend:
  review the 41 fixes, then `dev → master` PR per the release flow (memory
  `nos-release-flow`). Nothing is pushed.
- **macOS 27 timing.** The operator upgrades "soon" — the 14 Darwin-27 plans want
  landing *before* that, ideally on the current OS so the guards can be authored
  against a known-good baseline and verified to no-op there.
- **RAG embedding model.** The design assumes a local Ollama MLX embedding model —
  the operator picks the exact model (size vs quality) before the ingest role lands.
- **Gov P0s (ISDS / NIA / eIDAS).** Greenfield, large, and only matters for a gov
  deployment target. Decide whether v0.7 carries it or it stays deferred.

---

## What was NOT done (honest list)

- **No RAG ingest scaffold** — design doc only (§5). The role/plugin/query-helper
  the RAG phase was scoped to build did not land (quota).
- **48 plans are unimplemented** by definition — they are the *next* work.
- **macOS 27** got plans, zero code — correct, it needs the real OS.
- **No live-system change, no push, no merge** — the run was read-only on live by
  design (unsupervised-overnight safety).
- **Per-severity finding tally not reconstructable** from the branch alone (§2).

---

*Generated by the overnight review workflow's synthesis phase, completed
2026-06-14 after the Europe/Prague quota reset. Inputs: the 12-dimension audit,
the adversarial verifier, the 41 fix commits, the 48 plans, and
`docs/rag-architecture.md`.*
