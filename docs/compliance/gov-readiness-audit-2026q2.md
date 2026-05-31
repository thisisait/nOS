# nOS — Czech Public-Administration Compliance Audit

> Generated 2026-05-31 by a code-grounded multi-agent audit (25 agents, 4 phases:
> inventory → assess → adversarial-verify → synthesize). Every finding cites a
> source file; every positive verdict was challenged by an independent skeptic.
> Scores are post-adversarial-review, not first-impression.

**Subject:** nOS (This is AIT — Agentic Home Lab), `dev` @ `2a3f02f`
**Scope:** Deployment readiness for a Czech public-administration body (*orgán veřejné moci*) acting as GDPR controller and a NIS2/ZKB *poskytovatel regulované služby*
**Frameworks assessed:** GDPR Art. 5, 17, 20, 25, 30, 32 · NIS2 / zákon o kybernetické bezpečnosti (ZKB) · eGovernment (ISDS, ISVS, WCAG) · Czech eIdentita / eIDAS (NIA, BankID, MojeID)
**Audience:** Government CISO + DPO

---

## 1. Executive summary

nOS is a genuinely above-FOSS-baseline self-hosted platform with real, code-pinned data-protection *scaffolding* — a CI-enforced GDPR Article 30 register (68 processing activities), a runnable dry-run-first Article 17 erasure workflow with a DSAR audit row, modern edge TLS 1.3, a mature vulnerability-management program, and a defensible 0-processor / 0-EU-transfer sovereign posture — but it does **not** clear the bar for a Czech public-administration controller. Four structural controls are absent rather than weak (no encryption at rest, no MFA anywhere, no operational breach-notification capability, no tamper-evident audit log), the entire Czech-specific eGovernment integration surface (datové schránky / ISDS, NIA / eIDAS federation) is greenfield, and the documentation makes at least three claims the code does not implement ("Nightly encrypted backup", a non-existent `pazny.audit_retention` role on a "Pulse schedule", and a Bone redaction control that writes payloads verbatim).

**Bottom-line verdict: nOS CANNOT be deployed to Czech public administration as-is.** It is blocked on five preconditions a CISO must gate on: (1) at-rest + backup encryption (today personal-data DB dumps land cleartext-after-gzip in object storage); (2) enforced MFA on privileged access; (3) an operational NÚKIB/NIS2 breach-notification capability (24h/72h/1-month); (4) a tamper-evident, append-only audit log; and (5) datové schránky (ISDS) connectivity plus NIA/eIDAS identity federation for any citizen-facing or statutory-delivery use. Until these land, nOS is a strong *internal SME / home-lab* platform, not a government-grade controller environment.

---

## 2. Corrections to the external pre-review

The external pre-review carried several incorrect premises. Verified findings:

- **(a) IAM is Authentik, not Keycloak.** There is zero Keycloak code in the tree; the IdP is Authentik (`ghcr.io/goauthentik/server`, server+worker) driven by declarative YAML blueprints (`roles/pazny.authentik/templates/compose.yml.j2`). This *matters* for the remediation path: MFA, password policy, SAML/OIDC identity **sources**, and NIA/eIDAS federation are all wired via Authentik blueprints (`authentik_stages_authenticator_validate`, `authentik_sources_saml`, `authentik_policies_password`) — none of which exist today, but all of which are a known, buildable Authentik surface rather than an architecture rewrite.

- **(b) PostHog / external telemetry does NOT exist — REFUTED.** Repo-wide grep for `posthog` and `sentry` returns zero hits. Every service shipping a phone-home toggle has it explicitly disabled in committed templates: Grafana (`GF_ANALYTICS_REPORTING_ENABLED=false`), Authentik (`AUTHENTIK_DISABLE_STARTUP_ANALYTICS=true`), Open WebUI (`ANONYMIZED_TELEMETRY=false`, `DO_NOT_TRACK=true`), Hermes, Home Assistant (opts out during onboarding). Cloud-AI keys ship empty (`default.credentials.yml:435-436`). The residual egress vectors are narrow and mostly opt-in: **Tailscale is ON by default** (`install_tailscale=true`, a real third-party control-plane egress to `login.tailscale.com` + DERP — the single material sovereignty default), ACME/Let's Encrypt only on public TLDs, and registry/Ollama/Homebrew pull-only metadata. The "all data stays local" claim is true for the offline profile (local TLD + Tailscale off + empty AI keys) but should be qualified for the default profile.

- **(c) The GDPR machinery the reviewer assumed absent DOES exist and is CI-pinned.** A single canonical mapper (`files/anatomy/module_utils/nos_gdpr.py`) renders every plugin/manifest `gdpr:` block into an Art-30 record — 64 Tier-1 plugins (0 without a block) + 4 Tier-2 apps = 68 activities — feeding both `state/dpa-register.md` and Wing's live `gdpr_processing` table. `tests/anatomy/test_gdpr_register_coverage.py` enforces coverage parity, 7-dimension Art-30 completeness, and byte-identical staleness. A real Art-17 erasure runner (`tasks/gdpr-forget.yml` + `state/gdpr-erasure-map.yml`, CI-pinned by `tests/anatomy/test_gdpr_erasure_map.py`), a DSAR recorder (`bin/record-dsar.php` → `gdpr_dsar` table), and a breach register (`gdpr_breaches`, Art 33-34) all exist. The Tier-2 parser hard-refuses any deploy lacking a complete `gdpr:` block (`nos_app_parser.py:181-186`). This is the platform's strongest leg.

- **(d) Vector-DB / AI-memory erasure reality.** The erasure machinery is real but does **not reach** the AI surfaces. There is no `svc_qdrant` entry in the erasure map and no delete capability at all — the Bone Qdrant client (`files/anatomy/bone/clients/qdrant_client.py`) exposes only `health/list/info/upsert/search`, zero `points/delete`. The `wing.db` `agent_*` tables (`agent_sessions/threads/iterations/memory_stores`) have no subject-keyed delete; the only deletion, `MemoryStore::forget($uuid)`, is uuid-keyed and driven solely by the autonomous Dreams loop. Worse, `qdrant-base/plugin.yml:252` declares `bone_redaction_required: true` ("Bone MUST strip operator email before upsert") but `main.py` embeddings-upsert passes `payload` verbatim — a declared control with zero implementing code.

- **(e) Audit-trail reality (who/what/when + before/after).** Against the six-element government bar the trail scores 4 of 6. **Present:** WHO (`actor_id` Authentik client_id + `actor_action_id` logical-action UUID + `source`), WHAT (`type` enum + task/role + `changed` flag + `result_json`), WHEN (triple-stamped `ts`/`acted_at`/`created_at`, ISO-8601 UTC). **Failing:** WHY is partial (no reason/justification/ticket field on ordinary task events); **BEFORE/AFTER state diff is entirely absent** (no schema field anywhere captures prior-vs-new value — only a `changed` 0/1 bit + opaque blob); and **immutability/tamper-evidence is actively violated** — `init-db.php` sets only `WAL`+`foreign_keys` (no triggers/WORM), `AgentSessionRepository.php:106,160-171` issues `UPDATE events` against already-written rows, and rows are unsigned (the repo's own `docs/sso-and-attribution.md` admits the signed-log layer is unbuilt).

---

## 3. Compliance matrix

(Adjusted status & score; "Score" is /100.)

| Area | Status | Score | Headline gap |
|------|--------|-------|--------------|
| **GDPR Art. 5** — principles of processing | ⚠️ partial | 40 | Storage limitation [5(1)(e)] unenforced for every application store; integrity/confidentiality [5(1)(f)] structurally fails (plaintext backups, mutable audit log) |
| **GDPR Art. 17** — right to erasure | ⚠️ partial | 26 | 19/22 services manual; backups, Redis, Qdrant, RustFS, `wing.db` uncovered; DSAR stamped `completed` regardless |
| **GDPR Art. 20** — data portability | ❌ missing | 12 | No per-subject export of any kind; intake-only DSAR; no structured/machine-readable subject bundle |
| **GDPR Art. 25** — by design & by default | ⚠️ partial | 42 | No DPIA; two egress-maximizing defaults (Tailscale on, agents cloud-primary); three doc-vs-code falsehoods |
| **GDPR Art. 30** — records of processing | ⚠️ partial | 58 | ~48% of Tier-1 purposes are boilerplate; 5 host services dark; no Art-30(1)(a) controller/DPO block |
| **GDPR Art. 32** — security of processing | ⚠️ partial | 38 | No encryption at rest; no MFA; plaintext internal DB legs; non-operational breach filing |
| **NIS2 / ZKB** — regulated-service provider | ⚠️ partial | 33 | No incident-notification tooling/IR plan; MFA un-wired; no at-rest crypto; mutable audit log |
| **eGovernment** — Czech public admin | ❌ missing | 22 | No ISDS / datové schránky; no ISVS alignment; no WCAG conformance / accessibility statement |
| **Czech eIdentita / eIDAS** — NIA federation | ❌ missing | 12 | No NIA/eIDAS/BankID/MojeID identity source; no LoA handling; MFA prerequisite un-wired |

---

## 4. Per-area findings

**GDPR Art. 5 — principles (⚠️ 40).** Accountability [5(2)] is the strong leg: a real CI-pinned Art-30 register (`nos_gdpr.py`, 68 records, `test_gdpr_register_coverage.py`) plus DSAR and breach registers. But storage limitation [5(1)(e)] **fails** — `tasks/audit-retention.yml` is tagged `['audit-retention','never']` (`main.yml:884-885`), dry-run-default, and purges only `wing.db` events; every application store accumulates indefinitely. Integrity/confidentiality [5(1)(f)] **fails**: `roles/pazny.backup/files/backup.sh` streams `gzip | aws s3 cp` with zero crypto, yet `docs/security-baseline.md:63` claims "Nightly encrypted backup". *Adversarial caveat:* the auditor could not refute the downgrade and found it understated — `security-baseline.md` references a `pazny.audit_retention` role "on a Pulse schedule" that **does not exist on disk**.

**GDPR Art. 17 — erasure (⚠️ 26).** A genuine, well-engineered skeleton exists: dry-run gate (`forget_confirm=true`), email validation, centralized audited map (`state/gdpr-erasure-map.yml`), DSAR row on every run, and a real automated Authentik anchor delete. But of 22 in-scope services only 3 auto-erase (Authentik + Gitea + WordPress); the other 19 are `method:manual` (report-only even on a confirmed run). Backups, Redis, Qdrant, RustFS, Loki/Tempo, and `wing.db` are entirely uncovered — an erased subject's PII survives in up to 7 daily + 4 weekly + 12 monthly RustFS dumps. *Adversarial caveat:* Vaultwarden — the one service flagged as holding third-party `end_users` PII (`breach_severity_default: critical`) — is `method:manual`; its advertised `dsar_endpoint: 'wing-cli vault-erase'` references a command that **does not exist** in `files/anatomy/wing/bin/`. The `gdpr_dsar` row is stamped `status='completed'` regardless.

**GDPR Art. 20 — portability (❌ 12).** No fulfilment machinery exists. `POST /api/v1/gdpr/dsar` recognizes `request_type='portability'` and persists a row, but no data is ever assembled or exported — there is no `gdpr-export.yml`, no per-service subject-export step, and no structured/machine-readable bundle. The two "export" artifacts in the tree are red herrings: `export.csv` exports the Art-30 *register* (operator metadata), and `tasks/export-state.yml` produces a whole-platform migration tarball. *Adversarial caveat:* none — no positive claim to refute. Art. 15 (right of access) shares the identical intake-only gap.

**GDPR Art. 25 — by design (⚠️ 42).** Real privacy-by-design machinery: the Tier-2 `nos_app_parser.validate()` makes a complete Art-30 block a **hard deploy gate** (`retention_days:0` rejected as a 5(1)(e) red flag), telemetry kill-switches ship on, cloud-AI keys ship empty, and enrollment is invitation-gated default-deny (`40-enrollment-flow.yaml.j2:54`). But there is **no DPIA / Art-35 artifact anywhere**, two privacy-hostile defaults (`install_tailscale=true`; all 7 AgentKit agents pin `model.primary` to `anthropic-claude-opus-4-7`), and three demonstrability falsehoods (false "encrypted backup", unimplemented Bone redaction, non-existent `audit_retention` role). *Adversarial caveat:* the refutation of the positive direction succeeded (machinery is real) but the score should move down, not up — a by-design claim the code does not implement is the inverse of Art-25 demonstrability.

**GDPR Art. 30 — records (⚠️ 58).** The strongest area structurally: single source-of-truth mapper, 68 records, all 7 dimensions CI-enforced, byte-compare staleness gate, Tier-2 hard-fail gate. Deficiencies are quality/depth, not absence: **31 of 64 Tier-1 records (~48%) carry auto-generated boilerplate purpose** (flagged † — including Authentik, Gitea, ERPNext, MariaDB, PostgreSQL, RustFS, Stalwart); five non-Docker host services that process personal data (Hermes, OpenCode, IIAB Terminal, the backup-to-RustFS job, the Bone bridge) have **no Art-30 record**; and Art-30(1)(a) controller/DPO identity is wholly absent. *Adversarial caveat:* Tier-1 EU-residency is an unvalidated assertion — `nos_gdpr` defaults `eu_residency=True`, so the headline "Transfers outside the EU: 0" is a tautology never checked against the actual image registry.

**GDPR Art. 32 — security of processing (⚠️ 38).** Verified passes: edge TLS 1.3 modern profile + cipher allowlist + `sniStrict` (`middlewares.yml.j2:80-96`), idempotent 4-tier Authentik RBAC, and a mature vuln-management program. Verified fails: **no encryption at rest of any kind** (no TDE, no RustFS SSE/KMS, plaintext backups, no `cryptsetup`/`fdesetup` enabling task); **no MFA wired anywhere** (Tier-1 admin is password-only); internal service-to-service traffic is plaintext (`sslmode=disable` hardcoded in Grafana/Miniflux/Outline; Infisical reaches PG/Redis over plain `postgresql://`/`redis://`); and breach notification is passive CRUD with no deadline/countdown. *Adversarial caveat:* worse than stated — internal TLS isn't merely absent, it's *affirmatively disabled*; supply chain carries 585 CRITICAL-fixable + 5002 HIGH-fixable CVEs and four non-resolved CRITICALs (incl. two permanently vendor-blocked FreePBX RCEs, REM-014 CVSS 10.0).

**NIS2 / ZKB (⚠️ 33).** Strong baseline (edge TLS, IAM/RBAC, vuln-mgmt, Linux host hardening, GDPR records) but four §21 load-bearing controls are structurally absent, each a blocker: incident notification not operationally supported (no 24h/72h/1-month deadline computation, no NÚKIB report tooling, no IR plan in the repo), MFA entirely un-wired, no at-rest encryption, and a mutable non-tamper-evident audit log. *Adversarial caveat:* the misleading "encrypted backup" claim + MFA being un-wired (not merely unenforced) erode the technical-credibility floor below what 38 implies → adjusted to 33.

**eGovernment (❌ 22).** Fails at the foundational integration layer: **no datové schránky / ISDS** (the legally mandatory statutory electronic-delivery channel for an *orgán veřejné moci*), no ISVS register alignment, no WCAG 2.1 AA conformance or *prohlášení o přístupnosti* (the operator dashboard is `lang="en"` with incidental ARIA only), and no NKOD open-data path. Partial credit only for the genuine sovereign-FOSS strengths and the GDPR record-keeping. *Adversarial caveat:* none — no positive claim to refute.

**Czech eIdentita / eIDAS (❌ 12).** Greenfield gap, not a config tweak. Zero `authentik_sources_saml`/`authentik_sources_oauth`, no source enrollment/login binding, no eIDAS attribute (PersonIdentifier / LoA / `AuthnContextClassRef`) property-mappings. Authentik is wired exclusively as an IdP issuing identity *down*; it never federates *up* to NIA. Compounded by the total absence of MFA — a platform that cannot enforce a second factor cannot assert eIDAS LoA substantial/high even after federation is wired. *Adversarial caveat:* none. Architectural feasibility (Authentik supports SAML/OIDC sources) earns the small non-zero score.

---

## 5. Readiness scores

- **NIS2 / ZKB (NÚKIB regulated-service provider): 33 / 100 — ⚠️ partial.** A real TLS-edge / IAM-RBAC / vuln-mgmt / GDPR-records baseline, but four §21 blockers (no incident-notification tooling or IR plan, MFA un-wired, no at-rest crypto, mutable audit log) plus a materially misleading "encrypted backup" claim make the platform-as-shipped unsuitable for a regulated-service provider without substantial new development.

- **eGovernment (Czech public administration): 22 / 100 — ❌ missing.** The Czech-specific integration surface that *defines* readiness (ISDS statutory delivery, ISVS registration, WCAG accessibility statement, NKOD open data) is entirely absent; the controls present are SME/home-lab-grade.

- **Czech eIdentita / eIDAS (NIA federation): 12 / 100 — ❌ missing.** No citizen-identity federation, no LoA handling, no MFA — nOS-as-shipped is an internal SME identity domain, not a citizen-facing eIDAS-bound government identity system. The score above zero reflects only that the Authentik substrate makes the build path feasible.

---

## 6. Remediation roadmap

Effort: **low** (hours–1 day) · **med** (days) · **high** (weeks / greenfield). Deduplicated across frameworks and ordered by priority. **P0 is the CISO deployment gate.**

### P0 — Government deployment blockers (gate go-live on all of these)

1. **Encrypt backups before upload + fix the false claim.** [low] `roles/pazny.backup/files/backup.sh` — pipe DB dumps + volume tarballs through `age`/`gpg` (or SSE-C/KMS) BEFORE `aws s3 cp`; correct the "Nightly encrypted backup" wording in `docs/security-baseline.md:63-65`. Personal-data dumps must never land in object storage cleartext-after-gzip.
2. **Enforce at-rest disk encryption as a playbook gate.** [med] Add a FileVault (`fdesetup status`) / LUKS (`cryptsetup`) pre-flight that hard-fails on a gov tenant if at-rest encryption is not active before any personal-data service starts.
3. **Wire mandatory MFA.** [med] `files/anatomy/plugins/authentik-base/blueprints/` — add an `authenticator_validate` stage (TOTP + WebAuthn/passkey) + authenticator-setup in enrollment, bind step-up MFA to Tier-1 admin apps, add a password-policy blueprint (length/complexity + HIBP).
4. **Build operational incident/breach notification + an IR plan.** [high] Wing `GdprPresenter` + `gdpr_breaches` — computed 24h-early-warning / 72h-notification / 1-month-final-report deadline counters off `detected_at`, escalating alarms, a breach-filing UI, and a NÚKIB/ZKB regulator-report export; commit a written IR + business-continuity playbook to `docs/`.
5. **Make storage limitation [5(1)(e)] enforced, not metadata.** [high] Add scheduled Pulse retention-purge jobs for application DBs, Qdrant, Redis, `agent_*` tables, and RustFS keyed to each record's `retention_days`; schedule `tasks/audit-retention.yml` (remove the `never` tag for a gated run).
6. **Make Art-17 erasure reach every PII store, and stop overstating completion.** [high] `state/gdpr-erasure-map.yml` + `tasks/gdpr-forget.yml` — add a per-subject backup-purge/re-dump path, Redis session flush on Authentik delete, a Bone Qdrant `points/delete` endpoint + map entry, and subject-keyed deletes across `wing.db agent_*`; record `status='partial'` with a per-service checklist instead of blanket `completed`.
7. **Build a per-data-subject consent registry; decouple consent from SSO.** [high] New consent table (subject, activity, lawful_basis, ToS-version-hash, `granted_at`, `withdrawn_at`) + withdrawal endpoint + consent-event audit type; stop treating `gate_sso_required` (`nos_app_parser.py:267-274`) as a consent proxy.
8. **Datové schránky (ISDS) integration.** [high] Greenfield module against the MoJ ISDS interface (send/receive datové zprávy, delivery confirmation, archival into the audit trail) — the single largest blocker for any statutory-delivery use by an *orgán veřejné moci*.
9. **Federate Authentik UP to NIA (Identita občana) with eIDAS LoA.** [high] `authentik_sources_saml`/OIDC source against the NIA SeP / eIDAS node, qualified signing/encryption certs, eIDAS minimum-dataset + LoA property-mappings, and LoA-gated step-up policies — required for any citizen-facing identity assurance.
10. **Disable VoIP/FreePBX for gov profiles.** [low] Pin `install_freepbx=false`; REM-014 (CVE-2025-57819, CVSS 10.0, actively exploited) and REM-046 are permanently unfixable in the abandoned tiredofit image. Document the carve-out.

### P1 — High-priority hardening (before broad rollout)

- **Make the audit log tamper-evident & append-only.** [high] HMAC/hash-chain each `events` row on insert; SQLite triggers blocking `UPDATE`/`DELETE`; remove the `AgentSessionRepository.php:106,160-171` post-write `UPDATE events` rewrites (use a side linkage table); add a WORM/legal-hold retention tier mapped to ISO 27001 A.12.4.2-3 / ZKB. [`files/anatomy/wing/db/`, `AgentSessionRepository.php`]
- **Enable internal encryption-in-transit (close REM-009).** [med] PostgreSQL SSL + `PGSSLMODE=require` / Redis TLS for Infisical, Outline, Metabase, Superset, Grafana, Miniflux — remove the hardcoded `sslmode=disable`.
- **Author the 31 boilerplate Art-30(1)(b) purposes** [med] (`plugin.yml gdpr.purpose`, start with Authentik/MariaDB/PostgreSQL/Gitea/ERPNext/RustFS/Stalwart) **+ add the Art-30(1)(a) controller/DPO identity block** [low] to the register generator.
- **Implement the declared Bone embeddings redaction** [med] (`qdrant-base/plugin.yml bone_redaction_required:true` → real strip-before-upsert in `main.py`), pin with a test; add a Qdrant `points/delete` path.
- **Burn down the supply-chain backlog** [high] — resolve REM-004 + the 2 non-blocked CRITICALs (REM-002 Woodpecker, REM-043 n8n SSRF), add SBOM generation + cosign/sigstore signature/provenance verification + registry-trust enforcement.
- **Add a coverage-completeness CI gate.** [med] Extend `tests/anatomy/test_gdpr_erasure_map.py` to assert every PII-holding store/plugin has an erasure entry (or a justified exclusion) — close the silent-green loophole.
- **Build Art-15 access + Art-20 portability export tooling.** [high] `tasks/gdpr-export.yml` mirroring the `gdpr-forget.yml` safety model + a `state/gdpr-export-map.yml`, emitting one structured per-subject JSON bundle, with the artifact path/checksum linked into the `gdpr_dsar` row.
- **WCAG 2.1 AA conformance + published accessibility statement** [high] for any citizen-facing surface (zákon 99/2019 Sb.); Czech localization + `lang` attributes; pin an a11y audit in CI.
- **Author a DPIA (Art-35)** [med] for the citizen-data activities + an explicit Art-25/Art-32 privacy-by-design statement and ZKB §-level control matrix.

### P2 — Coverage completeness & Czech-specific governance

- **Add Art-30 records for the 5 dark host services** (Hermes, OpenCode, IIAB Terminal, backup job, Bone bridge). [med]
- **Promote the 19 `method:manual` erasure entries to programmatic deletes** (Nextcloud `occ user:delete`, GitLab `hard_delete`, Open WebUI + `webui.db` content scrub, Vaultwarden, ERPNext, Infisical, Portainer). [high]
- **Cover forward_auth per-user state** (Calibre-Web, Puter, code-server, Firefly) instead of blanket-excluding it; document `wing.db` audit-trail retention as an Art-17(3)(b) exception. [med]
- **Add Czech accountability artifacts:** zákon č. 110/2019 Sb. mapping, ÚOOÚ notification fields, Art-28 processor/sub-processor register field, ISVS architecture documentation, NKOD open-data path. [med]
- **Add BankID / MojeID identity sources** alongside NIA. [high]
- **Internal in-transit + host audit hardening:** flip Linux `auditd` immutable mode on by default; add macOS host-level audit/IDS (osquery). [med]

### P3 — Sovereignty defaults & polish

- **Ship `profiles/gov-local.yml`:** [low] `install_tailscale=false` (or wire Headscale), pin all 7 AgentKit agents' `model.primary` to local openclaw/Ollama, commit an outbound-domain egress allowlist + offline registry-mirror path.
- **Replace the self-signed OIDC signing cert** with a properly issued cert + rotation policy for any external relying party; add Authentik brand/tenant hardening (session idle/absolute timeouts). [med]
- **Loki/Tempo subject-scoped erasure** or document time-based retention as the sole control for IP/email-bearing telemetry. [med]

---

## 7. Strengths to preserve

These are genuine, government-relevant properties that the remediation work must not regress:

- **Digital sovereignty / all-FOSS, local-first.** Self-hosted on operator hardware, fully air-gappable in the offline profile (local TLD = mkcert), no SaaS dependency. Directly serves the digital-independence agenda — preserve it by hardening the two egress defaults (Tailscale, agent cloud-primary) rather than adding cloud dependencies.
- **No external telemetry — verified.** Zero PostHog/Sentry; per-service phone-home kill-switches committed; internal telemetry bound to `127.0.0.1`. A defensible "0 transfers / 0 processors" posture.
- **Secrets-as-pointers.** Infisical-backed; `agent_credentials.secret_ref` is never plaintext (`env:` / `infisical:` pointers resolved at session-open). Plaintext lives only in function-local memory.
- **Mandatory GDPR Article 30 deploy gate.** `nos_app_parser.validate()` refuses `docker compose up` for any Tier-2 manifest lacking a complete `gdpr:` block (all 7 dimensions required, `retention_days:0` rejected) — data protection literally engineered into the deploy mechanism. This is rare and worth advertising.
- **Single source of truth in Ansible + CI-pinned GDPR machinery.** The canonical `nos_gdpr.py` mapper feeding both the static register and Wing's live DB, with byte-compare staleness and coverage-parity gates, prevents documentation drift — the right foundation to extend (consent registry, completeness gates, host-service records) rather than rebuild.
- **Edge TLS 1.3 + idempotent 4-tier RBAC + mature vuln-management.** Traefik modern profile with cipher allowlist and `sniStrict`; Authentik expression-policy RBAC bound per-application; trivy/grype scanning with a tracked 87-item remediation queue and drift-watch staleness alerting. Above-baseline controls that carry the floor up.

---

**Verified file anchors (all confirmed present on `dev`):** `state/dpa-register.md`, `state/gdpr-erasure-map.yml`, `tasks/gdpr-forget.yml`, `tasks/audit-retention.yml`, `roles/pazny.backup/files/backup.sh`, `docs/security-baseline.md`, `files/anatomy/module_utils/nos_gdpr.py`, `files/anatomy/module_utils/nos_app_parser.py`, `files/anatomy/wing/db/schema-extensions.sql`, `files/anatomy/wing/app/Model/AgentSessionRepository.php`, `files/anatomy/bone/clients/qdrant_client.py`, `files/anatomy/plugins/authentik-base/blueprints/40-enrollment-flow.yaml.j2`, `tests/anatomy/test_gdpr_erasure_map.py`.
