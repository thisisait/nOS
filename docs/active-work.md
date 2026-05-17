# Active work — what to do right now

> **Always-current pointer for the next session.** Read this BEFORE
> [`docs/roadmap-2026q2.md`](roadmap-2026q2.md) (long-form historical
> record) and [`docs/bones-and-wings-bulk-plan.md`](bones-and-wings-bulk-plan.md)
> (multi-lane coordination plan).
>
> Last updated: 2026-05-17 (evening) • Phase 5 ceremony CLOSED + Wing
> UI revision SHIPPED (W3+W1+W2+W4). 32 commits pushed to origin/master
> (`826c406..22600df`). 253/253 anatomy gates green.

---

## Current track: **steady-state — A1–A14 + Phase 5 + Wing UI revision all DONE**

A1–A14 are all **DONE**, including A9 fanout, A9.2 daily-digest mail,
A9.3 Remediator agent, and the **Phase 5 ceremony milestone — CLOSED
2026-05-17**: conductor-self-test-001 ran via `tools/run-phase5-ceremony.sh`,
exit 0, agent_run_start + agent_run_end with shared
`actor_action_id=b01de576-7498-4b3f-bd2a-9b155b3f1a8b`. First
non-operator-identity end-to-end write to `wing.db` proven.

**Wing UI revision — SHIPPED 2026-05-17** (`7f25f30..22600df`, 4 commits):
* **W3 template hygiene** — inline `<script>`/`<style>` extraction,
  `lang="cs"` → `"en"`, hardcoded `auth.dev.local` → `$authentikDomain`,
  stale subtitle refresh. 7 anatomy gates.
* **W1 Information Architecture** — 5 visual groups (Operate · Insights
  · Security · Platform · Help/Admin) replacing the 12-flat-tab soup.
  Fragment-anchor tabs retired; Migrations/Upgrades/Coexistence/GDPR
  promoted from "presenter-but-no-nav" to first-class entries. 5 gates.
* **W2 Design tokens** — `tokens.css` (loaded first across the layout +
  Homepage) carries the semantic --color-* / --space-* / --radius-* /
  --font-* / --shadow-* scales + utility classes (.text-muted, .flex,
  .empty-state, ...). Legacy aliases preserved for the 6 pre-W2 per-page
  CSS files. 7 gates.
* **W4 Operator UX** — live unread/pending badges (Inbox + Approvals
  tabs); keyboard navigation wired (digit keys walk the .tab-key chips
  → tab href); `countPendingApprovals()` helper for cheap badge counts;
  defensive try/catch around per-render badge queries. 7 gates.

Total: 26 new anatomy gates locking the Wing surface (253/253 green).

**Parallel pending work:**
* **Tier-2 aggregator path** — extend `run_aggregators` with
  `from: app_manifest` source so Tier-2 apps land in `inputs.clients`
  alongside Tier-1; retire the `authentik_oidc_apps: []` Tier-2 stub.
* **Linux port** (`docs/linux-port.md`) — Ubuntu LTS target; deferred.

### Last verified state (2026-05-17)

- **`git status`** clean, 0 commits ahead after the 27-commit batch
  pushed today (`826c406..3fec16b` on origin/master).
- **Anatomy gates:** 227/227 green.
- **ansible-playbook main.yml --syntax-check:** clean.
- **Smoke probe (post-playbook):** 32/32 OK (Nextcloud 500 was the
  duplicate-prefix drift class — closed by Nextcloud post.yml
  pre-bootstrap config.php sed-patch).
- **wing.db event lineage:** 7 agent-attributed rows from this session
  — 2× `agent_run_start` + 3× `agent_run_end` + 2× `conductor_report`,
  spanning the conductor + remediator identities with cryptographic
  `actor_id` + `actor_action_id` attribution (A10 audit trail proven
  end-to-end).
- **Per-minute Pulse jobs:** `wing:dispatch-notifications` exit 0
  every minute since 13:09 UTC (post args[] fix).
- **Bone HMAC POSTs:** working end-to-end after the canonical-JSON
  + openssl-NF + launchd bootout-not-kickstart fix bundle.

### What landed since 2026-05-07

| Area | Highlights |
|---|---|
| **Wing UI revision (2026-05-17)** | 4-phase consolidation: W3 hygiene (inline-script extraction, lang fixes, hardcoded-domain purge), W1 IA (5 grouped sections + fragment-tab retirement), W2 design tokens (semantic --color-* / --space-* / --radius-* scales + utility classes), W4 UX (live Inbox+Approvals badges + global keyboard nav). 26 new anatomy gates. |
| **Phase 5 ceremony (2026-05-17)** | First non-operator-identity e2e write to `wing.db` proven. Conductor self-test ran on demand via `tools/run-phase5-ceremony.sh`, exit 0, two events with shared `actor_action_id`. Active-work punch #1 CLOSED. |
| **Post-Phase-5 incident-driven fixes (2026-05-17)** | Live remediator surfaced 7 latent bugs in its first triage report: (1) Wing api_tokens missing `remediator` row; (2) discover-pulse-catalog.py substitution table missing `{{ remediator_wing_api_token }}` + `{{ wing_app_dir }}` + `{{ wing_home }}`; (3) wing-base dispatch jobs referenced `wing_home/bin/` but script lives in `wing_app_dir/bin/`; (4) Bone `events.py` VALID_TYPES whitelist missing `agent_run_start/end` + `conductor_report` + `remediator_report`; (5) bash printf-built JSON bodies non-canonical → Bone HMAC validation fails (fix: build via `jq --sort-keys -c`); (6) `awk '{print $2}'` extracts empty hash on openssl 3.x (fix: `$NF`); (7) `launchctl kickstart -k` doesn't re-read EnvironmentVariables — launchd caches them (fix: bootout + bootstrap in handlers for bone/openclaw/wing). Plus Nextcloud post.yml pre-bootstrap config.php sed-patch (self-heals dbpassword drift without `blank=true`). 5 new anatomy gates pin the canonical-JSON + openssl-NF + ApprovalsPresenter canonicalize contracts. |
| **Remediator agent (A9.3)** | Read-only security-finding triage agent. AgentKit profile at `files/anatomy/agents/remediator/`, Pulse profile at `files/anatomy/agents/remediator.yml`. Authentik `nos-remediator` client wired with READ-ONLY caps only (anatomy gate enforces no `write` / `scan`). `tools/run-remediator.sh` on-demand wrapper produces a markdown report with `GREEN/REVIEW/RED` verdict. Genericized `pulse-run-agent.sh` to `NOS_AGENT_*` env (backward-compat aliases). 17 anatomy gates + `docs/remediator-agent.md`. |
| **A9 daily-digest mail (A9.2)** | `mail_digest_window` schema column + ALTER sweep; dispatch worker has severity-floor (`DISPATCH_MAIL_DIGEST_FLOOR`, default `medium`) — at/below queues, above immediates; `DISPATCH_DIGEST_FLUSH=1` daily worker aggregates queue into ONE summary email grouped by severity; new `dispatch-notifications-digest` Pulse cron (default 09:00 UTC); `mail_digest_floor` + `mail_digest_cron` in default.config.yml. 5 new gates. |
| **Notification fanout (A9)** | New table `wing.db.notifications`; NotificationRepository; Bone POST/GET `/api/v1/notifications` (HMAC); InboxPresenter promoted to operator-attention surface with mark-read; PHP CLI dispatch worker (`bin/dispatch-notifications.php`) registered as per-minute Pulse subprocess job; aggregator harvests per-plugin `notification:` blocks into a routing JSON sidecar Bone reads at insert time; gitleaks plugin is first consumer; 13 anatomy gates + authoritative guide `files/anatomy/docs/notification-fanout.md`. |
| **D2 residual cleanup** | Promoted 12 vars (erpnext_data_dir, nodered runtime defaults, nodered+superset OIDC client_id/secret) to default.config.yml; dropped `\| default(...)` chains from 14 role tasks/templates so nos-smoke catalog auto-derive sees them. Closes punch #6. |
| **AgentKit (A14)** | Runtime shipped + 5 deferred follow-ups closed (multi-agent pool, dreams, webhook auto-fan-out, operator-trigger UI, Infisical vault refresh). RBAC gates A13.7 + A14.1 + A14.2 security review rounds. |
| **Approvals (A11)** | `/approvals` approve/reject flow promoted from stub to working presenter with HMAC audit trail. |
| **Platform halt (A12)** | "Big red button" — operator can halt all agent runs via Wing UI; Bone propagates the gate to Pulse runner. |
| **E2E (A13.x)** | A13.1 telemetry foundation + A13.5 three real journeys (plugin_contract, halt_resume, approval_flow) + A13.6 ephemeral SSO tester layer + A13.7 RBAC presenter gates. **Playwright suite migrated to ephemeral SSO (2026-05-16)**. |
| **Actor audit (A10/X-series)** | `actor_id` + `actor_action_id` columns on events + pulse_runs + agent_sessions; presenter `/audit` view; auto-attribution from callback plugin. |
| **Plugin system (Track Q complete)** | Q3–Q7 base manifests (12 substrates) + D2 batch (13 roles thinned). Loader discovers 63 plugins. |
| **SnappyMail** | New Tier-1 role — webmail frontend for Stalwart. |
| **Tooling** | `tools/fetch-authentik-bootstrap-token.py` (operator-side bootstrap closer); `tools/e2e-auth-helper.py` (Playwright globalSetup helper). |
| **Cleanup** | Mattermost vars + DB scaffolding purged (no ARM64 FOSS image after 3+ years); Infisical seed.yml ljust filter bug fixed. |

---

## Punch list

Numbered for the loop prompt; each line ≤ 2 sentences. Items 1–11 from
the previous snapshot all completed — see git log between `7e2026c` and
`5f9c0a7` for the trail.

1. ~~**Phase 5 ceremony** — `bash tools/run-phase5-ceremony.sh` fires the
   conductor self-test on demand. Pre-flight (Bone health + pulse_jobs
   row + Authentik probe) + env resolution from `pulse_jobs.env_json`
   (no secrets re-read) + post-flight `event_delta`/`notif_delta` +
   markdown report (`~/.nos/phase5-report-<ts>.md`). Pass = exit 0 AND
   ≥2 conductor events written.~~ DONE 2026-05-17: ceremony exit 0,
   `actor_action_id=b01de576-7498-4b3f-bd2a-9b155b3f1a8b`, both
   `agent_run_start` + `agent_run_end` events landed. Authoritative
   guide: `docs/phase5-ceremony.md`.
2. ~~**A9 — notification fanout** — bones-and-wings §Appendix B; follow
   inbox/approvals shape. Not started.~~ DONE 2026-05-16: A9.1
   (schema + NotificationRepository) → A9.6 (anatomy gates + doc). See
   `files/anatomy/docs/notification-fanout.md` and commits
   `95bba82..b6aa9e7`.
3. ~~**Tier-2 aggregator path** — extend `run_aggregators` with
   `from: app_manifest` source.~~ DONE in `cf69ead` (X.3) — Tier-1 and
   Tier-2 SSO flow through the same plugin aggregator now. The empty
   `authentik_oidc_apps: []` stub remains as defensive default.
   ~~Follow-up (deferred — needs wet smoke): `roles/pazny.apps_runner/tasks/post.yml`
   still mutates `authentik_oidc_apps` + `authentik_app_tiers` via
   `set_fact` (lines 91-125), which is duplicate work post-cf69ead.~~
   DONE 2026-05-17: legacy `set_fact` extensions deleted; aggregator's
   `from: app_manifest` branch now also reads tier from `nginx.rbac_tier`
   so blueprints get the correct per-app tier without a separate map.
   3 anatomy gates in `test_apps_runner_aggregator_cutover.py`.
4. ~~**INTEGRATION.md migration** — 9× role `INTEGRATION.md` files instructed
   adding rows to the retired central `authentik_oidc_apps` list. All
   roles are auto-wired via `files/anatomy/plugins/<svc>-base/plugin.yml`
   now, so the obsolete onboarding flows were deleted in commit
   following 2026-05-16. `TODO.md:40` + 3 role READMEs updated to point
   at the plugin manifest instead.~~ DONE.
5. ~~**Doc drift** — `bones-and-wings-refactor.md` Appendix B still marks
   A7/A8/A10 NOT STARTED (all shipped). `handoff-next-parallel-session.md`
   Track A says Q3-Q7 TODO (shipped). Update or replace.~~ DONE 2026-05-16:
   verified Appendix B already correct (A7/A8/A10 DONE; only A9 NOT
   STARTED, accurate); added inline ✅ DONE markers to Q3-Q7 lines in
   `handoff-next-parallel-session.md` body so the body matches its own
   header.
6. ~~**D2 residual** (nice-to-have, not blocking): freescout / erpnext /
   homeassistant / superset / nodered / paperclip role tasks still use
   `| default(...)` pattern on vars not in `default.config.yml`.~~
   DONE 2026-05-17 (`c64c397`).
7. ~~**One-shot migration scripts** — `tools/d12-annotate-plugins.py` +
   `tools/aggregator-dry-run.py` shipped D1.x.~~ Verified 2026-05-16:
   `aggregator-dry-run.py` is the active CI gate inside
   `tests/e2e/journeys/test_plugin_contract.py`; `d12-annotate-plugins.py`
   is idempotent and harmless — keep as utility.
8. **Security backlog** — 12 pending `remediation_items` rows; Phase A
   (CVE pins) → B (mem/cpu limits) → C (hardening) → D (architectural).
   Vendor-blocked: Open WebUI ZDI CVEs, RustFS gRPC sigverify.

---

## Snapshot table

| Surface | State |
|---|---|
| `git status` | clean (one floating `nos_tester_password` template change pending operator decision) |
| Last verified | 2026-05-16; Playwright + smoke + coexistence + syntax-check all green |
| Tier-1 services | smoke probe: 31/32 OK on pazny.eu (Nextcloud 500 separate) |
| Plugin loader | 63 plugins (Q1–Q7 + D1+D2 complete) |
| Authentik blueprints | rendered by `authentik-base` plugin aggregator; per-plugin `authentik:` blocks are SoT (post-D1.3) |
| Pulse | 4 endpoints live; conductor + gitleaks Pulse jobs registered |
| Wing OpenAPI | 70 paths, /inbox + /approvals + /audit + /halt + /agents live (notifications surfaces via Bone POST/GET, see `notification-fanout.md`) |
| Playwright e2e | 14 passed / 7 skipped (opt-in services) / 0 failed; ephemeral SSO identity per run |
| Conductor | pulse-run-agent.sh + conductor.yml profile; A9 emit on non-zero exit; on-demand via `tools/run-phase5-ceremony.sh` |
| AgentKit | runtime live at `files/anatomy/wing/app/AgentKit/`; first agent = conductor |
| Decision log | O1–O23 in `roadmap-2026q2.md` (append-only) |

---

## How to update this file

After every meaningful work session:

1. Update **Last verified state** + snapshot table.
2. Cross-strike completed punch-list items + add follow-ups.
3. If a phase landed, append a row to **What landed since …** + log the
   decision in `roadmap-2026q2.md` if it changed direction.
4. Commit `docs(roadmap): refresh active-work pointer`.
