# nOS roadmap

Canonical, prioritized roadmap — the single forward-planning surface. Supersedes
the scattered ones (`active-work.md` is the NOW pointer only; `roadmap-2026q2.md`
+ the 49 `v07-*.md` dumps + RELEASE prose should be triaged/archived — see
§"Doc reconciliation"). Produced by an 8-agent state-of-nOS audit (2026-07-07),
**revised 2026-07-08** after the security-batch + converge-green session — grounded
in code + git + the live install, not the docs.

## The through-line

nOS's engineering is **weeks ahead of its documentation**. The reset-scope +
session-safety work (Phases 0-4), macOS-as-managed-upgrade (Inc 1-3c, **live-validated**
on a real 26.3.1→26.5.1 update), and migration-author Phase-4 all shipped to `dev`
but appear in no changelog. The agent runtime + coexistence frameworks are genuinely
mature — but their **headline acceptance criteria are unexercised** (no real migration
authored; PG 16→17 never cut over end-to-end).

The **security ground-truth crisis is resolved** (2026-07-08): the cycle-16 queue is
committed, and the live-exploitable CRITICAL (FreeScout REM-118, CVSS 9.4 unauth
takeover) is **patched + verified on-host**, alongside Bone unauth recon (REM-110),
Alloy unauth OTLP (REM-107), and the three degraded services that were failing the
STRICT health gate (qgis, gitlab-VirtioFS, puter). **The converge is green** (61
containers, 0 unhealthy).

What remains is **burn-down + epic acceptance**: a 29-item version-pin wave (two
CRITICALs left — Gitea EOL + a Woodpecker misconfig), the never-exercised upgrade/
migration acceptance criteria, and a large **doc-reconciliation** debt so an agent or
contributor stops taking the stale docs as source-of-truth.

## Shipped this session (2026-07-08) — reconcile into changelogs

- **Security queue committed + reconciled** (was uncommitted working-tree truth).
- **REM-118 FreeScout** → `nfrastack/freescout:2.1.3-php8.3` (app 1.8.226 > 1.8.224
  fix); cross-org migration (tiredofit EOL) + `SITE_URL`→`APP_URL`. Live healthy.
- **REM-110 Bone** → `require_scope(nos:state:read)` on services/status/health-aggregate
  (liveness stays open); **PyJWT floor → 2.13.0**. Live 401/200.
- **REM-107 Alloy** → `alloy_otlp_bind_addr` var (default `127.0.0.1`), both config
  copies. Live loopback bind.
- **qgis** restart-loop → idempotent entrypoint guard **+ `command:` restore**
  (compose `entrypoint:` clears the image CMD). Live running.
- **gitlab VirtioFS puma loop** → tmpfs over `/var/opt/gitlab/gitlab-rails/sockets`
  (socket off VirtioFS → no more `realdirpath ENOTSUP`). Live healthy, 0 errors.
- **puter** telemetry-preload crash → `command:` override drops the `-r telemetry.js`
  preload (base image stopped bundling `@opentelemetry/auto-instrumentations-node`).
  Live "PuterServer fully booted".
- **First real upgrade recipe** `upgrades/freescout.yml` (converge-driven for the
  cross-org bump; full backup→verify→rollback for future same-org 2.x bumps).
- Queue tally: **pending 36 / resolved 79 / vendor-blocked 3** (of 118).

## NOW — the immediate queue

1. **[M] Version-pin drift wave — 29 pending `version_bump` items**, incl. **two
   CRITICALs**: **REM-099 Gitea 1.25.x EOL → 1.26** (CVE-2026-27771 serves private
   packages to anonymous pulls) and **REM-002 Woodpecker misconfig**. The rest are
   mechanical HIGH/MEDIUM bumps (nginx, ollama, rustfs×2, openwebui, mariadb, redis,
   n8n, gitlab XSS, erpnext, jellyfin FFmpeg, portainer, dnsmasq, mailpit, outline,
   homeassistant, uptime-kuma, tileserver, puter). Bump `default.config.yml` (wins
   over role defaults), then **verify the running image tag** (version-pin-shadow
   trap). Gitea 1.26 is a major-line jump → do it as the **first same-org upgrade
   recipe** (§P1), not a blind bump.
2. **[S/M] Re-anchor `active-work.md` + resolve the v0.7-beta state** — the NOW pointer
   is frozen at 2026-06-15 ("v0.7-beta tag prep"), ~40 commits behind HEAD
   (`f7f0176a`); RELEASE.md declares v0.7-beta shipped but **no git tag exists**
   (latest `v0.6-beta`). Either cut the tag or demote to unreleased.
3. **[S] Doc reconciliation pass** (§ below) — security counts everywhere → **36/79/3
   of 118**; the shipped-this-session list into CLAUDE.md "Recently shipped" +
   RELEASE.md; the plan-header lags.

## Backlog

### P0 — roadmap truth (security truth now closed)
- **Doc reconciliation** (NOW #3) — fix the counts in CLAUDE.md:350 + active-work.md
  (still claim the stale 14/71/2-of-87) and add the 2026-07-08 shipped list.
- **Refresh the CVE full-scan baseline** — `scan-state.json last_full_scan` is past
  the 14-day drift-hook threshold; a fresh full scan re-grounds the 36-pending set.
- **Re-anchor active-work.md + v0.7-beta** (NOW #2).

### P1 — burn-down + the epic's own acceptance
- **[M] Version-pin drift wave** (NOW #1, 29 items incl. REM-099/002 CRITICAL).
- **[M] Gitea 1.25.x EOL → 1.26 migration** (REM-099) — a major-line bump via an
  **upgrade recipe**. Cleaner than FreeScout as a recipe-engine exercise: **same org**,
  so `compose.set_image_tag` fully drives it (no template org-swap), truly exercising
  the `--tags upgrade` backup→apply→verify→rollback path end-to-end.
- **[L] PG 16→17 end-to-end cutover** through the agent flow — the upgrade epic's OWN
  acceptance criterion. pg17 verified live beside pg16 on the coexistence track, but
  the actual cutover (logical dump/restore + pointer flip) has never run. Framework
  shipped; needs operator-supervised execution.
- **[M] Author the first real migration** — `files/anatomy/migrations/` holds only a
  `_template` + one `_archived`; the Phase-4 reset propagation + `test_reset_floor.py`
  are forward guards that activate only when a real migration lands. PG 16→17 (or
  Gitea 1.26) is the natural driver.
- **[M] Merge `fix/sso-mfa-posture`** — 8 live-bug fixes stranded off dev (firefly
  remote_user_guard 500, traefik dup-router 502, enrollment blueprint idempotency, …).
- **[M] Promote the sso-autologin epic** (dev-only, dormant behind `sso_autologin:false`)
  to master + reconcile its plan doc.
- **[S] Bone dep-lockfile** — pin fastapi/uvicorn/httpx/PyYAML/PyJWT to a lockfile
  (mirroring wing `composer.lock` discipline); the REM-110 PyJWT floor bump landed but
  the full supply-chain pin is the remaining folded-in ask.
- **[L] Retention enforcement (gov P0-5)** — `retention_days` is descriptive metadata
  only; actual purge reaches only `wing.db` events. Application DBs / Qdrant / Redis /
  agent_* tables are unpurged.
- **[S] Infisical MTI oauth2/proxy orphan render fix** — the aggregator still emits an
  orphan OAuth2Provider for a forward_auth service; reappears every apply.

### P2 — feature tails + robustness
- **[M] VirtioFS class-risk doctrine** — the gitlab puma socket is **fixed** (tmpfs,
  this session), but the pattern is a class-risk: consolidate the ~6 scattered VirtioFS
  workarounds behind a doctrine doc + pytest gate + greppable `# VFS-DOCTRINE:` markers
  so a Darwin-27 bind-semantics tightening is detectable, not silent. See
  `docs/plans/v07-darwin27-virtiofs-filesystem-workaround.md`.
- **[M] Healthcheck coverage** for the health-blind containers (freescout, calibre-web,
  homeassistant, nextcloud, wordpress, infisical, portainer, …) so STRICT
  wait-stacks-healthy actually gates them (this session, freescout/qgis/puter/gitlab
  came up but only some expose a real HEALTHCHECK; the wait treats no-healthcheck as
  "running=ready", a coverage gap).
- **[L] Close the conductor loop** — cadence auto-dispatch of downstream agents (today
  it reports but never auto-fires remediator/upgrade-advisor/migration-author). Needs
  operator sign-off on autonomous dispatch.
- **[L] Migrate the 5 CLI-wrapper agents to native AgentKit** (only migration-author
  runs native today).
- **[L/XL] Unblock inspektor** (trivy/grype/nuclei substrate) + **librarian** (Qdrant
  corpus ingest) — both contract-only, waiting on greenfield substrates.
- **[M] reset-scope blank wet-test + thin run_mode=detached UI auto-route** — the two
  named remainders of the upgrade epic.
- **[M] macOS Inc 4** — `upgrades/macos.yml` first-class host_reboot recipe (resolve the
  reboot-spanning recipe-modeling question first).
- **[L] Erasure automation depth** (Art-17: 26/29 entries still `method:manual`; backups
  never subject-purged) + DSAR/export bundle encryption.
- **[M] RustFS / OpenWebUI / Woodpecker CVE clusters** (pending, not vendor-blocked).
- **[M] Wing-on-Linux validation** (drop the `install_wing:false` stale workaround).
- **[M] Consolidate the roadmap surface** (this doc) + triage the 49 `v07-*.md` shadow
  backlog; **add a machine-checkable active-work freshness gate** (the 150-line ceiling
  is pinned but nothing pins freshness — which is why it drifted 3+ weeks).

## Cross-cutting risks
- **VirtioFS is a class-risk, not a one-off** — the gitlab puma `realdirpath ENOTSUP`
  loop is now fixed (tmpfs), but the same bind-semantics gap could break other stateful
  containers on a Darwin-27 Docker Desktop tightening. No gate detects the pattern yet.
- **ansible-core 2.24 jump** is coupled to the `{{ vars }}` retirement (removed in 2.24);
  needs a dedicated pre-2.24 wet-test lane.
- **Epic acceptance unexercised** — the freescout recipe is the first shipped, but no
  real *migration* authored and PG 16→17 never cut over; latent bugs surface only on
  first real use of the same-org recipe / migration / coexistence-cutover paths.
- **Healthcheck blindness** — no-HEALTHCHECK containers pass the STRICT wait as long as
  they are `running`, so a booted-but-broken app (like puter was) can read as ready.
- **Gov P0s genuinely open** — retention metadata-only, ISDS + NIA/eIDAS greenfield; not
  gov-deployable for citizen-facing Czech use despite the structural controls.
- **FreePBX vendor-blocked CRITICALs** (REM-014/046/113, incl. 9.3 hard-coded creds)
  unfixable in the abandoned image; only `install_freepbx=false` mitigates.
- **Systemic doc drift** — an agent/contributor taking the docs as source-of-truth will
  re-plan shipped work or miss live-degraded services.

## Doc reconciliation
- **Security counts**: CLAUDE.md:~350 + active-work.md → **36 pending / 79 resolved /
  3 vendor-blocked of 118**. Vendor-blocked set = FreePBX-only (REM-014/046/113).
- **CLAUDE.md "Recently shipped"** — add the 2026-07-08 batch (REM-107/110/118 + qgis +
  gitlab-VirtioFS + puter + first upgrade recipe), reset-scope 1-4, macOS 1-3c
  (live-validated), migration-author Phase-4, sso-autologin epic. Fix the ERPNext bullet
  (role is PARKED, not flaky-with-retry).
- **RELEASE.md** — cut the v0.7-beta tag or demote; add a July section (os-resume /
  reset-scope / Phase-4 / the security batch).
- `docs/plans/macos-as-managed-upgrade-target.md` header — says "Inc 2 next" but Inc
  2-3c shipped; header lags its own body ~3 increments.
- `docs/plans/agentic-upgrade-migration-coexistence.md` + memory — reframe
  "VISION/DESIGN-FIRST" → mid-Phase-B (B1-B6 + A1-A5 landed); note the first recipe shipped.
- `docs/sso-autologin-plan.md` + memory — flip from greenfield to shipped-on-dev.
- `docs/sso-and-attribution.md` — stale "not running on schedule"; only inspektor +
  librarian are runner-less.
- Archive (grep inbound first): `adjustment-build-report.md`, `phase-b-build-report.md`,
  the resolved `v07-sec-*`/`v07-tofu-*`/`v07-sso-*-verify-ok.md` docs.
