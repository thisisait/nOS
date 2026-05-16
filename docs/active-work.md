# Active work — what to do right now

> **Always-current pointer for the next session.** Read this BEFORE
> [`docs/roadmap-2026q2.md`](roadmap-2026q2.md) (long-form historical
> record) and [`docs/bones-and-wings-bulk-plan.md`](bones-and-wings-bulk-plan.md)
> (multi-lane coordination plan).
>
> Last updated: 2026-05-16 • doc-refresh after A10/A11/A12/A13.x/A14 all
> shipped + Mattermost purge + Playwright SSO e2e wiring + punch #5 doc
> drift cleanup + A9 notification fanout shipped.

---

## Current track: **Phase 5 ceremony**

A1–A8, A9, A10, A11, A12, A13.x, A14 are all **DONE**. The remaining
big milestone is **Phase 5** — first non-operator end-to-end write to
`wing.db` via the `conductor-self-test-001` Pulse job. Pre-requisites
(A10 actor audit, A8 conductor pipeline, A9 notification fanout, Pulse
jobs registered) all landed; the final gate is an operator-driven
ceremony run.

**Parallel pending work:**
* **Tier-2 aggregator path** — extend `run_aggregators` with
  `from: app_manifest` source so Tier-2 apps land in `inputs.clients`
  alongside Tier-1; retire the `authentik_oidc_apps: []` Tier-2 stub.
* **Linux port** (`docs/linux-port.md`) — Ubuntu LTS target; deferred
  until Phase 5 lands.

### Last verified state (2026-05-16)

- **`git status`** clean after current session's commits.
- Playwright e2e suite: 14 passed / 7 skipped / 0 failed against
  `pazny.eu` in 43s; ephemeral SSO tester provisioned + revoked per run.
- Smoke probe (post-playbook): 31/32 OK (Nextcloud 500 — separate issue).
- `ansible-playbook main.yml --syntax-check` clean.
- Coexistence tests 16/16 pass after Mattermost sentinel swap.
- `python3 tools/fetch-authentik-bootstrap-token.py` works (docker-exec
  primary path; auto-discovers `infra-authentik-server-1`).

### What landed since 2026-05-07

| Area | Highlights |
|---|---|
| **Notification fanout (A9)** | New table `wing.db.notifications`; NotificationRepository; Bone POST/GET `/api/v1/notifications` (HMAC); InboxPresenter promoted to operator-attention surface with mark-read; PHP CLI dispatch worker (`bin/dispatch-notifications.php`) registered as per-minute Pulse subprocess job; aggregator harvests per-plugin `notification:` blocks into a routing JSON sidecar Bone reads at insert time; gitleaks plugin is first consumer; 13 anatomy gates + authoritative guide `files/anatomy/docs/notification-fanout.md`. |
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

1. **Phase 5 ceremony** — operator runs `conductor-self-test-001` Pulse
   one-shot job (8-step e2e: health → trigger gitleaks → verify findings
   → events → contracts diff → wing tests → markdown report). Pass =
   first non-operator end-to-end write to `wing.db`. Pre-reqs all done.
2. ~~**A9 — notification fanout** — bones-and-wings §Appendix B; follow
   inbox/approvals shape. Not started.~~ DONE 2026-05-16: A9.1
   (schema + NotificationRepository) → A9.6 (anatomy gates + doc). See
   `files/anatomy/docs/notification-fanout.md` and commits
   `95bba82..b6aa9e7`.
3. ~~**Tier-2 aggregator path** — extend `run_aggregators` with
   `from: app_manifest` source.~~ DONE in `cf69ead` (X.3) — Tier-1 and
   Tier-2 SSO flow through the same plugin aggregator now. The empty
   `authentik_oidc_apps: []` stub remains as defensive default. Follow-up
   (deferred — needs wet smoke): `roles/pazny.apps_runner/tasks/post.yml`
   still mutates `authentik_oidc_apps` + `authentik_app_tiers` via
   `set_fact` (lines 91-125), which is duplicate work post-cf69ead.
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
6. **D2 residual** (nice-to-have, not blocking): freescout / erpnext /
   homeassistant / superset / nodered / paperclip role tasks still use
   `| default(...)` pattern on vars not in `default.config.yml`.
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
| Conductor | pulse-run-agent.sh + conductor.yml profile; awaits Phase 5 ceremony |
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
