# Active work — what to do right now

> **Always-current pointer for the next session.** Read this BEFORE
> [`docs/roadmap-2026q2.md`](roadmap-2026q2.md) (long-form historical
> record) and [`docs/bones-and-wings-bulk-plan.md`](bones-and-wings-bulk-plan.md)
> (multi-lane coordination plan).
>
> Last updated: 2026-06-10 • **post-v0.5-beta serial review → v0.6 prep.**
> v0.5-beta tagged 2026-06-06 (SSO/MFA coherence + SEC-02/REM-043/MTI security
> cluster). Since the tag, 22 commits landed on `dev` in 5 clusters: **backup/
> restore overhaul** (3-2-1 split, restore contract repaired + gated; operator
> to-dos #5/#6 + 4 known gaps in `docs/backup-architecture.md`), **GitLab/Gitea
> agent forge T32.2** (GitLab = MR review surface, recipe-PR + trunk-sync tools),
> **Hermes opt-in launchd daemon** (forward-auth gated route), **frozen 1:1
> local+CI toolchain** (`tools/ci-local.sh` + `ci-freeze.env` +
> `requirements.lock.yml` — run BEFORE any release push), **upgrade-engine
> hardening** (dry-run validation, version-pin shadow gate).
>
> **2026-06-10 full serial review** (playbook + security + anatomy + Wing +
> CI/docs) found & fixed: Nextcloud version-pin shadow (config `"stable"` was
> shadowing the C2 `"33"` major-lock → live container floated; pinned + allowlist
> entry removed), `docker-socket-proxy:latest` pinned to 0.4.2 + new base-stack
> pin gate, `scan-runner.sh` non-executable in git (pulse vulnerability-scan
> exit 255), `run-gitleaks.sh` GNU `head -n -1` (BSD head dies; → `sed '$d'`),
> Wing layout cache-buster `?v={$basePath}` → `$assetVer`, `.gitleaks.toml`
> allowlist (4 verified FPs; scan now clean), `apps/_template.yml` loopback port
> example, remediation queue reconciled **14 pending / 71 resolved / 2
> vendor-blocked** (REM-077 + REM-006 verified-done). All suites green after:
> 1674 passed / 5 skipped, ansible-lint production clean, syntax-check clean.
> **NEXT: v0.6 plan — see "v0.6 punch list" below.** Wing UI rapid-improvement
> track is the headline; CI gap: pushes to `dev` don't trigger Integration
> (covered only by `tools/ci-local.sh` discipline).
> **Still deferred:** OpenClaw (Ollama/CUDA) + Hermes Linux runtimes, host-nginx
> vhost templates on Linux, fleet provisioning (p2p/server-client/mesh).

---

## v0.6 punch list (drafted by the 2026-06-10 review; operator to re-prioritize)

**Headline: Track W6 — Wing UI rapid improvement.** Foundation is healthy
(tokens.css, burger nav, RBAC tiers, SEC-6 edge trust; all 20 presenters render
200 live). The gap is **dead/stale data surfaces**, not chrome:

1. **W6.1 — Inbox comes alive (A9 emitters).** `notifications` has 0 rows ever;
   the per-minute dispatch worker runs on empty. Wire the missing *emitters* —
   agent run verdicts (conductor/remediator reports), playbook-run failure
   summary (callback plugin → Bone), backup success/failure (backup.sh already
   has the A9 hook point), breach-deadline warnings — through the existing
   Bone `POST /api/v1/notifications` HMAC path. Severity floors per A9.
2. **W6.2 — Dashboard data honesty.** It claims "Scan cycle 16 hourly" while
   scans are on-demand (4 agent pulse jobs paused by doctrine) and advisories
   shown are from April. Add stale-data recency badges ("last scan N days ago",
   warn > 14d), drop the false "hourly", re-ingest the reconciled remediation
   queue (`bin/ingest-remediation.php`).
3. **W6.3 — /agents run-lifecycle UI** (operator-requested, parked 2026-05-30):
   token-consumption progress bar (`tokens_*` columns already on
   `agent_sessions`), elapsed + countdown vs the ~30-min cap, admin-only
   manual-kill (status=interrupted), server-side auto-terminate past-cap runs.
4. **W6.4 — Hub health coverage:** 21/57 systems "unchecked" — extend
   `health_check` plugin blocks to the remaining services.
5. **W6.5 (nicety) — lucide tree-shake:** 402 KB → ~5 KB for the ~15 used glyphs
   (#61).

**Track S — security follow-through:**

6. **S1 — refresh the full security scan** (last 2026-05-31; drift hook warns at
   14d). On-demand: `tools/run-scout.sh`. Proposal: auto-schedule **scout only**
   (read-only — doesn't violate the manual-over-auto doctrine); destructive
   remediation stays operator-fired.
7. **S2 — REM-004 image-freshness sweep** (trivy says the lever is stale base
   images): bump the ~10 priority images to current patch tags, verify running
   tags post-run (version-pin shadow gate now guards the config side).
8. **S3 — REM-009 PostgreSQL SSL** (mkcert CA mount + PGSSLMODE=require on the
   6 PG clients) and **REM-008 ERPNext dedicated DB user** — the two remaining
   config-change items that close Phase C.
9. **S4 — backup known-gaps:** extend `backup_dirs_to_dump` for Vaultwarden /
   n8n / Node-RED / Authentik-media host-bind state (with SQLite quiesce);
   deploy `backup_status_exporter.py` (91-backups dashboard is blind);
   wet-test the restic→RustFS DR round-trip. Operator: #5 volumes + #6
   external disk (see `docs/backup-architecture.md`).

**Track D — debt:**

10. **D1 — `{{ vars }}` wholesale retirement** (6 sites: core-up ×3, stack-up,
    blank-reset, pre-migrate) — hard-breaks on ansible-core 2.24; design the
    explicit loader-var namespace now, ship before the 2.24 floor bump.
11. **D2 — CI dev-push gap:** decide — (a) enable Integration on `dev` pushes
    (25-min cost per push), (b) a light `dev` job (lint+pytest+syntax only),
    or (c) keep `ci-local.sh` discipline documented as the gate. Review
    recommends (b).
12. **D3 — uptime-kuma 1.23.13 → 2.2.1** (full SSTI fix REM-037/073; breaking
    config-schema migration — needs an upgrade recipe + wet test).

### Release shape proposal (v0.6-beta)

Theme: **"The console you can trust" — Wing UI truthfulness + security
follow-through.** W6.1–W6.4 + S1–S3 + D2; S4/D1 stretch. Gate: full all-on
blank + `tools/ci-local.sh` + green release PR (the v0.5 PR went red on the
filter saga — fixed since, but the next PR must prove it).

---

## Prior track: **v0.4-beta cross-platform (Linux) — shipped 2026-06-01**

> Snapshot of the 2026-05-31 state (header preserved for archaeology):
> v0.3-beta is tagged. This session took the playbook cross-platform: the full
> `ansible-playbook main.yml` now provisions Ubuntu 24.04 LTS end-to-end, pinned
> by a standing `Integration (ubuntu-24.04)` CI wet-test (**green**). ~19 gap
> fixes on `feat/linux-port`, all macOS-byte-identical (Darwin / pkg-manager /
> service-manager gates): platform seam, systemd --user daemons (Bone/Pulse/
> backup/heartbeat), FrankenPHP Wing on Linux, mkcert apt, portable nginx.conf,
> `docker_bin` remap + `nos_docker_ready` compose-layer gate, host-nginx vhosts
> Darwin-gated (Traefik routes Linux). Also closed the long-standing macOS
> `integration` **idempotence** red (re-run `changed=0`): `wing_api_token`
> persisted, install/PECL/service-start `changed_when` fixed, dnsmasq notify-
> driven. Gates: ubuntu Integration green, macOS Integration green, syntax-check
> clean. **NEXT: cut `v0.4-beta`** (`feat/linux-port → dev → master` PR + tag,
> operator-gated, admin bypass) — clears the 3 dependabot symfony alerts too.
> **Deferred post-v0.4:** OpenClaw (Ollama/CUDA) + Hermes Linux runtimes, host-
> nginx vhost templates on Linux, fleet provisioning (p2p/server-client/mesh).

---

## Prior track: **v0.3-beta release prep (2026-05-30 evening) — shipped**

The macOS release. Cross-platform = v0.4 (operator decision). Tagged: finalized
`RELEASE.md`, ran the operator's `dev → master` PR + `v0.3-beta` tag (admin
bypass — see memory `nos-release-flow`). The lanes that built up to it:

## Prior track: **Upgrade-engine first-real-apply + Wing tiered RBAC (2026-05-30)**

Operator-driven "bring nOS up to date" session. Two lanes landed on `dev`
(11 commits `daf6a2b..981f68c`), live-verified on the operator's host:

* **Upgrade engine apply-path made real** — the `--tags upgrade` engine had
  NEVER run for real (dry-run short-circuits before handlers, so the "success"
  was a false positive). First real run exposed a fully-broken contract; now
  fixed and exercised end-to-end:
  - **Render layer** — recipe step strings mix play-vars (`{{ rustfs_data_dir }}`,
    filters) and engine tokens (`{{ upgrade_id }}`); `nos_migrate.py` now renders
    BOTH via Jinja2 against controller-passed `tmpl_vars` (undefined-safe
    `lookup('vars')`) + engine tokens. The recipe is raw-loaded so tokens stay
    literal for this layer to own.
  - **exec.shell bridge** — recipes author `command:` shell-strings; the
    upgrade action table wraps the strict handler to alias `command→cmd` +
    auto-`shell` (gate unchanged). `compose.recreate` added for rolling
    same-tag bumps; `set_image_tag` gained `override` (shared file), `--force-recreate
    --pull always`, post-up image verify + converge-on-drift.
  - **Live container names** are `<stack>-<service>-1`, base file is
    `docker-compose.yml`; recipe target tags were corrected to real registry
    tags; `upgrade_exclude` carve-out keeps PG out of bulk.
  - **Persistence** — applied upgrades bump the role-default version var
    (otherwise a plain `main.yml` re-render reverts them). **6/7 done + verified:**
    redis 8.0, firefly 6.2.21, bluesky 0.4, bookstack v26.05-ls264, authentik
    2026.5.2, rustfs at-target. **PG 16→17 deferred to the coexistence track**
    (sole `rm -rf data` recipe; pin #3).
  - **authentik recovery** — the 2026.5.2 jump + a buggy recipe rollback
    (restore_db under new code) half-migrated the auth DB → `cert_expiry already
    exists` boot loop, SSO down. Recovered out-of-band: clean pre-upgrade dump
    restore into a dropped+recreated DB → forward-migrate (10 users / 49 providers
    intact). authentik recipe hardened: local-port health probe (was the public
    domain → Cloudflare 403), rollback → `noop` (major upgrades are forward-only).
  - See memory `upgrade-engine-apply-path`. Engine internals spec:
    `files/anatomy/docs/upgrade-recipes.md`.
* **Wing tiered RBAC via Nette identity** — Wing read forward-auth groups
  ad-hoc and a new state-mutating presenter could forget the gate. Added
  `nette/security`; `ForwardAuthUserStorage` builds a stateless Nette identity
  from the `X-Authentik-*` headers each request (roles = groups → `$user->isInRole()`
  without session churn). `callerHasGroup`/`requireSuperAdmin` route through it;
  new `TIER_GROUPS` + `callerTier` + `requireTier` + declarative `$minAccessTier`
  enforced by default in `BasePresenter::startup()` (privileged presenters gate
  with one property). UpgradesPresenter → tier-1. Live-verified: tier-1 → 200,
  tier-2/3/4 → 403; render/CSRF intact.
* **GitLab readiness** — `/-/readiness` is monitoring-whitelist-gated; the
  host-side probe (NAT'd to the bridge gateway) 404'd for the full ~10 min
  retry budget. Added `172.16.0.0/12` to `monitoring_whitelist`.

**Next (this session): finish A** — playbook completes → verify version
persistence + PLAY RECAP → re-run `tools/run-upgrade-advisor.sh` (queue should be
near-empty) → PG 16→17 via `--tags coexistence` → re-run the Wing agents.
**Pre-C gate — DONE (2026-05-30):**
* **Big review** of the session's 16 commits → caught a **CRITICAL** bug:
  `lookup('vars', *names)` lacked `wantlist=true`, so every recipe play-var
  collapsed to its first char and `rm -rf {{ postgresql_data_dir }}/*` rendered
  as `rm -rf //*` (would have fired on the PG coexistence run — PG was
  `upgrade_exclude`'d so no live damage). Fixed + verified. Plus result-gate
  hardening, stale-test fixes. Masked/latent follow-ups noted (expanduser filter
  precedence; `_rewrite_all_image_tags` first-image assumption).
* **Autowiring epic** — already complete: P1a hub_card harvest + icon-glyph
  render (lucide self-hosted, `0177022`, live-verified) is closed; P2b/P4
  deferred-with-reasons; only #61 (tree-shake the 392KB lucide → ~5KB) is an
  optional perf nicety. See [[auto-wiring-epic-state]].

Roadmap lane now unblocked: **Linux port (Track C)** or **A8 conductor scheduled
drift-scans** (open backlog — would automate this "update everything" cadence).
Parked this-session backlog (observability/Wing-data) above also awaits.

### Parked backlog — observability + Wing-data flow (diagnosed 2026-05-30)

Operator flagged empty Grafana/Wing surfaces; root-caused, not yet fixed:

* **Agent run-lifecycle (feature + bug)** — failed/incomplete agent runs
  (concurrency crash, timeout-kill, LLM API socket error) never emit
  `agent_run_end`, so their `agent_sessions` row hangs `running` forever (5
  orphans cleaned by hand this session). Build the operator-requested
  `/agents` UI: token-consumption progress bar (`tokens_input/output/cache_read`
  already on the row), elapsed + countdown to a ~30-min cap, and an admin-only
  manual-kill (set `status=interrupted`) — plus a server-side auto-terminate of
  runs past the cap so dead runs self-clean. **Run claude-CLI agents
  sequentially** (concurrent = all crash — see [[agent-two-runtime-session-gap]]).
* **Grafana nOS dashboards empty** (22-ai-agents, 90-security, 99-playbook) —
  NOT missing data: `frser-sqlite-datasource@4.0.6` is installed + Prometheus
  has 6/7 targets up. The dashboards carry **stub panels** (`vector(0)`) + query
  Loki/Prom series that don't flow (openclaw off, app metrics unexported) + the
  SQLite datasource likely isn't mounted onto `wing.db` (Grafana is containerised,
  wing.db is host-side). Wire the SQLite DS to wing.db + replace stubs with real
  SQL over `events`/`agent_sessions`/`remediation_items`.
* **Wing /remediation empty despite data** — 24 pending / 59 resolved rows
  exist; `RemediationPresenter::renderDefault` calls `repo->list(['limit'=>200])`
  (no status filter) so the data IS queried → template render issue, needs a
  live `/remediation` check.
* **Wing inbox empty** — `notifications` table = 0; nothing posts notifications
  (agents write events, not notifications). Wire agent verdicts / A9 severities
  → notifications.
* **pentest stale / gitleaks 0** — no recent pentest scan; gitleaks can't ingest
  (unrendered HMAC pulse env, see [[pulse-catalog-literal-substitution]]).

---

## Prior track: **Epic C (Zpevnění) DONE (2026-05-25)**

Post-v0.2-beta hardening epic, landed 2026-05-25 on `dev`:

* **C3 — GDPR operator surface** — closed the keystone gap: per-plugin `gdpr:`
  blocks (loader-validated but never ingested) now flow through one canonical
  mapper (`files/anatomy/module_utils/nos_gdpr.py`) into TWO synchronized
  surfaces — the static DPA register (`state/dpa-register.md`, 67 services, for
  a DPO) and the live `gdpr_processing` table (Wing `/gdpr`). Plus Art.17
  right-to-erasure fan-out (`tasks/gdpr-forget.yml`, dry-run+confirm, audited
  `state/gdpr-erasure-map.yml`, DSAR legal record), storage-limitation purge
  (`tasks/audit-retention.yml`), DPO one-pager (`docs/security-baseline.md`).
  6 new anatomy gates.
* **C1 — image-pin sweep** — 16 floating tags pinned to fixed versions;
  remediation queue 53→25 pending (28 resolved; ZDI-no-fix + freescout
  scheme-mismatch kept honest); anti-regression gate `test_image_pin_hygiene.py`.
* **C2 — Nextcloud** — `stable`→`"33"` major-lock (likely live-500 fix: NC
  refuses major skips/downgrades on existing data).

**Next lane: Track C — Linux infra stack green** (`docs/linux-port.md`,
`docs/roadmap-2026q2.md` Track C). Ubuntu LTS target so nOS stops being
macOS-only. Real `pazny.linux.apt` + `pazny.linux.systemd_user`, Darwin-gate the
mac-only roles, CI `integration-linux` job.

## Prior track: **v0.2-beta cut — A1–A19 + security hardening DONE**

**v0.2-beta milestone (2026-05-23)** — see [`RELEASE.md`](../RELEASE.md).
Cut as git tag `v0.2-beta` from `master` (prior tag `v0.1-beta`). Validated
by a full STRICT all-on blank: `ok=1886 failed=0`. A19 bundle:

* **Plugin-wiring unification** — notification routing canonicalized to the
  A9 severity shape (`on_critical`/`on_high`/`on_medium`/`on_low`/`on_info`
  → `wing-inbox`|`ntfy`|`mail`) across **55/55** plugins. New CI gate
  `tests/anatomy/test_plugin_wiring_contract.py`, report
  `tools/plugin-wiring-report.py`, doctrine
  `files/anatomy/docs/plugin-wiring-capabilities.md` (live-consumer vs
  forward-ready metadata). qdrant-base gained a `feature_flag`; gitleaks
  gdpr/schema conformed.
* **Orchestration health-wait** — blocking `docker compose up --wait`
  replaced by `up -d` + an in-stream health-wait heartbeat
  (`tasks/stacks/wait-stacks-healthy.yml`, `tasks/stacks/health-tick.yml`,
  `files/anatomy/scripts/stack-health-probe.py`). ~15s ticks print per-stack
  readiness lines into `ansible.log`. STRICT — every container must reach
  healthy. New vars `stack_up_parallel` / `stack_up_wait_timeout` /
  `stack_wait_tick_interval`; sequential cold-blank avoids Docker-daemon
  saturation. New `profiles/all-on.yml` (every known-good service, excludes
  erpnext/freepbx/spacetimedb). Applied to core-up / stack-up / apps-up.
* **Sudo-free runner** — `tools/nos-stacks.sh [tag]` runs the stack layer
  without sudo and without the vars_prompt (agent/CI dev).
* **Single-run autowiring** — `authentik_bootstrap_token` is
  playbook-generated + pinned as the Authentik blueprint token key (Wing
  /users + invitations work on ONE blank run, no fetch-tool second pass);
  Woodpecker↔Gitea OAuth2 client auto-created.
* **Wing Latte CSRF fix** — CSRF tokens on every browser POST form (SEC-14).

---

## Prior track: **steady-state closeout — A1–A17 + security hardening DONE**

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
* **Linux port** (`docs/linux-port.md`) — Ubuntu LTS target; deferred.
* **Post-A17 hardening follow-ups** — keep security fixes small, gated,
  and tied to anatomy tests; the Tier-2 `from: app_manifest` aggregator path
  is already live and pinned by `tests/anatomy/test_apps_runner_aggregator_cutover.py`.

### Last verified state (2026-05-23)

- **`git status`:** clean before the closeout doc/test-fix pass; local
  `dev` was ahead of `origin/dev` by 20 commits after the E2E hardening
  commit. Push is the remaining publication step.
- **Broad pytest gate:** `896 passed, 5 skipped` across anatomy, apps,
  Authentik, Bone auth, callback, coexistence, migrate, and upgrades.
- **Ansible syntax:** `ansible-playbook main.yml --syntax-check` clean.
- **Authentik aggregator parity:** `authentik_oidc_apps` central coverage is
  0; plugin `inputs.clients` has 38 entries; central-only blockers are 0.
- **Playwright SSO:** static-identity full suite green — 14 passed,
  7 deployment-skipped. Helper uses exact `AUTHENTIK_DOMAIN` hostname
  matching and Playwright request preflight for dev/prod TLS parity.

### What landed since 2026-05-07

| Area | Highlights |
|---|---|
| **Wing UI revision (2026-05-17, evening)** | 4-phase consolidation (W3+W1+W2+W4) + follow-ups: browser-verified 403 fix (super-admin gate accepts nos-providers OR nos-admins per CLAUDE.md RBAC table); Dashboard rewrite (drops dead 'Components moved to Hub' surface + in-page tab soup); Latte 3 syntax + AUTHENTIK_DOMAIN env fixes; UX coherence pass on Hub/Pentest/Remediation/Audit/Agents (structured empty-states, subtitles, links to operator wrappers). 26 new anatomy gates. |
| **SSO + identity doctrine lock (2026-05-17)** | Mode trichotomy pinned (gitea/qdrant/grafana normalized to canonical labels); RBAC gate widened to accept nos-admins + nos-providers; 2 privilege-escalation bugs fixed (body-supplied resolved_by in Gitleaks + Remediation presenters); direct actor_id on pentest_findings + pentest_targets; Scout agent shipped (full), Inspektor + Librarian contract-only (runners deferred until tooling lands). 19+ anatomy gates. Authoritative guide `docs/sso-and-attribution.md`. |
| **Stalwart TLS SMTP path (2026-05-17)** | Dispatch worker now speaks STARTTLS (587) + AUTH LOGIN against Stalwart when `install_smtp_stalwart: true`. New `_smtp_open_session` helper handles raw / STARTTLS / implicit-TLS modes via `MAIL_TLS_MODE` env. wing-base plugin manifest flips env vars automatically based on the install flag. 2 new anatomy gates. |
| **Per-plugin notification templates (2026-05-17)** | Plugin manifest `notification.templates.<name>: {title, body}` with `$var`/`${var}` placeholders. Emitter sends `{template, context}` instead of literal title/body. Bone renders via Python string.Template.safe_substitute. gitleaks first consumer. 6 new anatomy gates. |
| **Tier-2 aggregator cleanup (2026-05-17)** | apps_runner/post.yml dropped the duplicate set_fact for authentik_oidc_apps + authentik_app_tiers (X.3 aggregator path is now SoT). Aggregator reads tier from nginx.rbac_tier. 3 new anatomy gates. |
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
8. **Security backlog** — 24 pending `remediation_items` rows (Epic C1
   burned down the version-bump backlog 2026-05-25/26); Phase A (CVE pins,
   largely done) → B (mem/cpu, done) → C (hardening) → D (architectural).
   Vendor-blocked: Open WebUI ZDI CVEs, RustFS gRPC sigverify.

---

## Snapshot table

| Surface | State |
|---|---|
| `git status` | A19 wiring + orchestration changes uncommitted on `dev` (this session) |
| Last verified | 2026-05-23; full STRICT all-on blank `ok=1886 failed=0`; pytest + syntax-check green |
| Release | `v0.2-beta` (cut from `master`; prior `v0.1-beta`) — see `RELEASE.md` |
| Tier-1 services | smoke probe: 31/32 OK on pazny.eu (Nextcloud 500 separate) |
| Plugin wiring | 55/55 notification-canonical; `test_plugin_wiring_contract.py` gate |
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
