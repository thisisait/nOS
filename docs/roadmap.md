# nOS roadmap

Canonical, prioritized roadmap — the single forward-planning surface. Supersedes
the scattered ones (`active-work.md` is the NOW pointer only; `roadmap-2026q2.md`
+ the 49 `v07-*.md` dumps + RELEASE prose should be triaged/archived — see
§"Doc reconciliation"). Produced by an 8-agent state-of-nOS audit (2026-07-07),
grounded in code + git + the live install, not the docs.

## The through-line

nOS's engineering is **weeks ahead of its documentation**. The last wave shipped
to `dev` (HEAD `51721247`) but appears in no changelog: reset-scope + session-safety
(Phases 0-4), macOS-as-managed-upgrade (Inc 1-3c, **live-validated** on a real
26.3.1→26.5.1 update), migration-author Phase-4. The agent runtime + coexistence
frameworks are genuinely mature — but their **headline acceptance criteria are
unexercised** (no real migration authored; PG 16→17 never cut over end-to-end).

The urgent problem is **security ground truth**: the cycle-16 scanner queue
(37 pending / 76 resolved / 3 vendor-blocked, 116 items) exists **only as an
uncommitted working-tree change**, while every committed doc still claims the stale
14/71/2-of-87 — and that hidden queue holds a **live-exploitable CRITICAL**
(FreeScout REM-118, CVSS 9.4 unauth account takeover, edge-routed + running).

**Order of operations:** commit + reconcile the security queue → patch what is
exploitable today → re-anchor the roadmap docs → then the backlog is mostly
mechanical burn-down plus a few well-scoped feature tails.

## NOW — the immediate queue

1. **[S] Commit the drifted security queue** (`docs/llm/security/{remediation-queue,scan-state}.json`, `2026-04-08-vuln-report.md`, ~1007 insertions uncommitted). A `git checkout .` / branch switch loses the entire cycle-16 truth incl. the CRITICAL. Enabler for all security prioritization below.
2. **[S] Patch the live-exploitable unauth surfaces:** FreeScout **REM-118** (CVE-2026-53595, 9.4 account takeover, running on MariaDB + 200-at-edge); Bone **REM-110** (unauth topology recon at `api.<tld>`); Alloy **REM-107** (OTLP bound `0.0.0.0:4317/4318` → set `alloy_otlp_bind_addr=127.0.0.1`; telemetry injection can poison the conductor's audit/trace lineage).
3. **[S] Fix the qgis-server restart loop** — `engineering-qgis-server-1` is thrashing `Restarting (0)` right now (non-idempotent apache2 entrypoint: `ln: failed to create symbolic link .../qgis.conf: File exists`). Undocumented; a small idempotent-entrypoint guard closes it. (gitlab's VirtioFS loop is the second degraded service — see risks.)
4. **[S/M] Re-anchor `active-work.md` + resolve the v0.7-beta state** — the NOW pointer is frozen at 2026-06-15 ("v0.7-beta tag prep") ~30 commits behind HEAD; RELEASE.md declares v0.7-beta shipped but **no git tag exists** (latest `v0.6-beta`). Either cut the tag or demote to unreleased.
5. **[M] Burn down the version-pin drift wave** — ~15 mechanical image bumps aged out of the C1 sweep (mariadb REM-102, redis REM-103, n8n REM-109, jellyfin REM-119 FFmpeg arg-injection, openwebui REM-101, outline, hedgedoc, mailpit, dnsmasq, gitlab XSS REM-111). Bump `default.config.yml` (wins over role defaults), then verify the running tag.

## Backlog

### P0 — security truth + exploitable + roadmap truth
- **Commit + reconcile the queue** (NOW #1) and fix the counts in CLAUDE.md:350 + active-work.md.
- **REM-118 / REM-110 / REM-107** (NOW #2) — the three live-exploitable surfaces.
- **Refresh the CVE full-scan baseline** — `scan-state.json last_full_scan=2026-05-31` is 37 days stale (past the 14-day drift-hook threshold).
- **Re-anchor active-work.md + v0.7-beta** (NOW #4).

### P1 — burn-down + the epic's own acceptance
- **[M] Version-pin drift wave** (NOW #5, REM-101..121).
- **[M] Gitea 1.25.x EOL → 1.26 migration** (REM-099, CRITICAL — CVE-2026-27771 serves private packages to anonymous pulls, fixed only in 1.26.x). A major-line migration via an **upgrade recipe** — a natural first real recipe.
- **[L] PG 16→17 end-to-end cutover** through the agent flow — the upgrade epic's OWN acceptance criterion. pg17 verified live beside pg16 on the coexistence track, but the actual cutover (logical dump/restore + pointer flip) has never run. Coexistence framework is shipped; needs operator-supervised execution.
- **[M] Author the first real migration** — `files/anatomy/migrations/` is empty; the Phase-4 reset propagation + `tests/migrations/test_reset_floor.py` are forward guards that activate only when a real migration lands. PG 16→17 (or Gitea 1.26) is the natural driver.
- **[L] Retention enforcement (gov P0-5)** — `retention_days` is descriptive metadata only; actual purge reaches only `wing.db` events. Application DBs / Qdrant / Redis / agent_* tables are unpurged (Art-5(1)(e) below passing).
- **[M] Merge `fix/sso-mfa-posture`** — 8 live-bug fixes stranded off dev (firefly remote_user_guard 500, traefik dup-router 502, enrollment blueprint idempotency, …).
- **[M] Promote the sso-autologin epic** (dev-only, dormant behind `sso_autologin:false`) to master + reconcile its plan doc.
- **[S] Infisical MTI oauth2/proxy orphan render fix** — the aggregator still emits an orphan OAuth2Provider for a forward_auth service; reappears every apply.
- **[S] CLAUDE.md reconcile** — Recently-shipped pointers for reset-scope 1-4 / macOS 1-3c / migration-author Phase-4; fix the ERPNext tech-debt bullet (role is PARKED, not flaky-with-retry).

### P2 — feature tails + robustness
- **[L] Close the conductor loop** — cadence auto-dispatch of downstream agents (today it reports but never auto-fires remediator/upgrade-advisor/migration-author). Needs operator sign-off on autonomous dispatch.
- **[L] Migrate the 5 CLI-wrapper agents to native AgentKit** (only migration-author runs native today).
- **[L/XL] Unblock inspektor** (trivy/grype/nuclei substrate) + **librarian** (Qdrant corpus ingest) — both contract-only, waiting on greenfield substrates.
- **[M] VirtioFS-workaround doctrine + gitlab puma socket fix** — consolidate the 6 scattered VirtioFS workarounds behind a doctrine doc + pytest gate + greppable `# VFS-DOCTRINE:` markers; move gitlab's `/var/opt/gitlab` off the host bind (or TCP-only puma). See `docs/plans/v07-darwin27-virtiofs-filesystem-workaround.md`.
- **[M] reset-scope blank wet-test + thin run_mode=detached UI auto-route** — the two named remainders of the upgrade epic.
- **[M] macOS Inc 4** — `upgrades/macos.yml` first-class host_reboot recipe (resolve the reboot-spanning recipe-modeling question first).
- **[L] Erasure automation depth** (Art-17: 26/29 entries still `method:manual`; backups never subject-purged) + DSAR/export bundle encryption.
- **[M] RustFS / OpenWebUI / Woodpecker CVE clusters** (pending, not vendor-blocked).
- **[M] Healthcheck coverage** for the 13 health-blind containers (freescout, calibre-web, homeassistant, nextcloud, wordpress, infisical, portainer, …) so STRICT wait-stacks-healthy actually gates them.
- **[M] Wing-on-Linux validation** (drop the `install_wing:false` stale workaround; apt php path).
- **[M] Consolidate the roadmap surface** (this doc) + triage the 49 `v07-*.md` shadow backlog; **add a machine-checkable active-work freshness gate** (the 150-line ceiling is pinned but nothing pins freshness — which is why it drifted 3 weeks).

## Cross-cutting risks
- **Uncommitted security ground truth** — the whole cycle-16 queue (incl. the 9.4) is only in the working tree; commit before anything else.
- **Live-exploitable now** — FreeScout 9.4 (edge-routed), Bone unauth recon, Alloy unauth OTLP; the last can poison the conductor's audit lineage.
- **VirtioFS is a class-risk, not a one-off** — puma `realdirpath ENOTSUP` recurs on every macOS update; a Darwin 27 Docker Desktop bind-semantics tightening could break more stateful containers silently. No gate detects the pattern.
- **ansible-core 2.24 jump** is coupled to the `{{ vars }}` retirement (removed in 2.24); needs a dedicated pre-2.24 wet-test lane.
- **Epic acceptance unexercised** — no real migration authored, PG 16→17 never cut over; latent bugs surface only on first real use.
- **Gov P0s genuinely open** — retention metadata-only, ISDS + NIA/eIDAS greenfield; not gov-deployable for citizen-facing Czech use despite the structural controls.
- **FreePBX vendor-blocked CRITICALs** (REM-014/046/113, incl. 9.3 hard-coded creds) unfixable in the abandoned image; only `install_freepbx=false` mitigates.
- **Systemic doc drift** — an agent/contributor taking the docs as source-of-truth will re-plan shipped work or miss live-degraded services.

## Doc reconciliation (queue after committing the security files)
- Security counts: CLAUDE.md:350 + active-work.md → 37/76/3 of 116. Vendor-blocked set = FreePBX-only (REM-014/046/113; 113 is a new third CRITICAL); reclassify REM-064/059 as pending.
- RELEASE.md — cut the v0.7-beta tag or demote; add a July section (os-resume / reset-scope / Phase-4).
- CLAUDE.md "Recently shipped" — add reset-scope 1-4, macOS 1-3c (live-validated), migration-author Phase-4, sso-autologin epic.
- `docs/plans/macos-as-managed-upgrade-target.md` header — says "Inc 2 next" but Inc 2-3c shipped; header lags its own body ~3 increments.
- `docs/plans/agentic-upgrade-migration-coexistence.md` + its memory — reframe "VISION/DESIGN-FIRST" → mid-Phase-B (B1-B6 + A1-A5 landed).
- `docs/sso-autologin-plan.md` + memory — flip from greenfield to shipped-on-dev.
- `docs/sso-and-attribution.md` — stale "not running on schedule" (conductor unpaused weekly + daily jobs); only inspektor+librarian are runner-less. Add/point-to a real agent matrix.
- Archive (grep inbound first): `adjustment-build-report.md`, `phase-b-build-report.md`, the resolved `v07-sec-*`/`v07-tofu-*`/`v07-sso-*-verify-ok.md` docs.
