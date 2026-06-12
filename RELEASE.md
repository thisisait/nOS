# nOS — Release notes

`nOS` is the open-source Ansible engine behind [**This is AIT — Agentic IT**](https://thisisait.eu): one command turns an Apple Silicon Mac into a reproducible, self-hosted, self-managing cloud of ~50 FOSS services behind one SSO.

Versioning is by git tag `v<semver>` cut from `master`. The prior tag was `v0.5-beta`.

---

## v0.6-beta (2026-06-12)

> **OpenTofu becomes the Authentik authority (ADR-0001 Phase 1 — complete).**
> The SSO wiring layer — every provider, application, and outpost attachment —
> is now declarative HCL applied by OpenTofu, replacing the imperative
> `ak apply_blueprint` path for that layer (`authentik_engine: tofu`). The
> cutover was executed the hard way (Path B: tofu-engine blank from scratch),
> which surfaced and closed six structural traps plus three latent AgentKit
> runner bugs — each pinned by a CI gate. Validated end-to-end: tofu-engine
> blank `failed=0`, `tofu plan` no-op across the full tenant, smoke catalog
> 48/48, e2e SSO journeys green, and a full conductor agent run.

### OpenTofu Authentik cutover

- **Ownership split:** OpenTofu owns providers + applications + outpost
  attachments via one hand-authored `for_each` module
  (`modules/nos-authentik-app`) over a committed, generated registry
  (`state/tofu-authentik-services.yml` ← plugin + Tier-2 app-manifest
  `authentik:` blocks). The other six blueprints (groups / MFA / RBAC /
  agents / enrollment / brand) stay imperative by design.
- **Safety rails:** destroy guard (apply refuses ANY delete in the plan) +
  `-parallelism=1` (the outpost attachment is a read-modify-write list; the
  default parallelism raced 20 writes and kept 11) + reversible engine flag.
- **Six cutover traps fixed + gated** (full archaeology in
  `docs/opentofu-authentik-cutover.md`): Authentik auto-applies mounted
  blueprints (no-op render under tofu); `lookup('file')` never resolves
  nested Jinja post-2.19 (`lookup('template')` bridge); the outpost m2m race;
  Tier-2 app manifests missing from the registry; perpetual
  `internal_host_ssl_validation` diff; and **missing `grant_types`** —
  Authentik 2026.5.x made it an explicit ArrayField, so tofu-created
  providers rejected every native_oidc login with `invalid_request` while
  forward_auth stayed green (now declared in the module AND probed live by
  the new `tests/e2e/journeys/test_native_oidc_authorize.py`).
- **Post-cutover punch list shipped same-day:** tofu state artifacts in the
  nightly encrypted backup set (`run_tofu_state()`); disabled services
  filtered out of the tfvars (no SSO objects for `install_*: false`); a daily
  plan-only drift Pulse job (`authentik-tofu-drift-base`, never applies,
  drift → A9 notification).

### AgentKit runner — first live exercise

The release sweep ran the AgentKit native trigger paths on a deployed box for
the first time (the pulse claude-CLI runtime had masked them) and fixed three
latent bugs: the CLI agents-root off-by-one (Nette `%appDir%` is
bootstrap-caller-derived → `agentsDir` parameter + a CLI override valid in
both the repo and deployed nesting), the operator-trigger 500 (`PHP_BINARY`
is empty under FrankenPHP's embedded SAPI → `WING_PHP_BIN` → fallback chain),
and a missing RobotLoader in the CLI bootstrap (AgentKit keeps value objects
beside their aggregates — PSR-4 can't autoload them). Gate:
`test_agentkit_runner_paths.py`. The claude-CLI runtime remains the live
agent path (verified: full conductor self-test, exit 0, report event in Wing).

### Validation

Tofu-engine blank `failed=0` (ok=1418, all 8 stacks healthy) → smoke 48/48 →
`tofu plan` rc=0 (full parity) → e2e SSO/web-UI journeys green incl. the new
native_oidc authorize probe (18/18 providers) → agents: conductor + scout +
remediator full runs rc=0. Anatomy suite: 1225 tests.

## v0.5-beta (2026-06-06)

> **SSO/MFA coherence + a pre-release security cluster.** This tag makes the
> single-sign-on story *honest and load-bearing*: MFA posture is explicit
> (remembered by default, strict for gov), autologin is documented exactly where
> upstream allows it (and where it can't), and three security findings that the
> SSO work surfaced — a forgeable identity-header trust boundary, an n8n SSRF, and
> an Authentik provider-flip collision — are closed and live-verified. No new
> services; the change is in how the existing fleet authenticates. A non-gov,
> non-`+all` run is behaviourally unchanged except for the network-isolation move.

### SSO autologin — honest coverage

The goal is "it feels like one app": sign in to Authentik once, then every
`*.<tld>` service is zero-to-one click. What that actually delivers per service
is bounded by what each upstream supports — stated here rather than over-promised:

| Login UX | Services (representative) | Why |
|---|---|---|
| **0-click** (forward_auth passthrough) | Kiwix, Uptime Kuma, Paperclip, Puter, Wing, Mailpit, BI | Authentik session **is** the auth; service has no own login |
| **0-click** (native_oidc auto-redirect) | Grafana | Upstream supports forced OIDC redirect — no login form shown |
| **1-click** ("Sign in with Authentik") | Gitea, Nextcloud, Outline, BookStack, 2FAuth, Superset, Vaultwarden | Upstream OIDC, but no auto-redirect — one button on the service's own page |
| **gate + own login** (documented ceiling) | **portainer** (OIDC button, no auto-redirect), **infisical** (CE org-OIDC is enterprise-licensed → forward_auth gate + own form), **metabase** (OSS has no OIDC → gate + shared operator account) | Upstream limitation, not a bug — gate-enforced `supports:` so it can't be falsely promised |

The global force-OIDC mechanism (`sso_autologin`, single config var → plugin
loader) ships **dormant (default `false`)**; the per-service upstream-support
truth lives in `docs/sso-autologin-plan.md` and `docs/sso-and-attribution.md`.

### MFA posture — explicit, per-tenant

- **Default (non-gov):** posture B — global MFA, *remembered*. An enrolled user
  re-challenges once per `mfa_remember_window` (default `hours=8`), not every login.
- **Gov (`profiles/gov-local.yml`):** **strict step-up** — `mfa_remember_window:
  "seconds=0"`, 2FA on every authentication-flow run, no remember-device.
- MFA is **configure-not-deny** (`nos-tier1-mfa-flow`, TOTP + WebAuthn passkey):
  an un-enrolled Tier-1 user is prompted to set up a device inline and continues —
  never a hard lockout. Non-Tier-1 providers keep the stock flow byte-unchanged.

### Security cluster (SEC-02 + REM-043 + MTI)

- **SEC-02 — header-trust isolation.** calibre-web, 2FAuth and Firefly trust the
  forwarded `X-authentik-*` / `REMOTE_USER` identity header with **zero upstream
  validation**, so on the flat `shared_net` any peer container could forge it
  straight to the backend, off-Traefik. Fix: a Traefik-only `gated_net`
  (calibre + 2FAuth) and `gated_b2b_net` (Firefly, with MariaDB + Redis joined for
  DB reach) — the backends leave `shared_net`; only Traefik routes them. Firefly's
  `TRUSTED_PROXIES` narrowed from `**` to `172.16.0.0/12`. **Live-verified:** an
  n8n→backend forge is unreachable (rc=1) while the edge still serves 302→auth and
  Firefly stays healthy. Pinned by `tests/anatomy/test_sec02_*`.
- **REM-043 — n8n SSRF closed.** Enabled n8n's built-in
  `N8N_SSRF_PROTECTION_ENABLED` guard (n8n core since 2.12, ships default-OFF) via
  the n8n-base plugin compose-extension, gated by `n8n_ssrf_protection` (default
  true), with optional blocked/allowed-range overrides. The previously-queued
  remediation (`N8N_WEBHOOK_AUTH=true`) was a **non-existent env var** — corrected
  in the remediation queue. Pinned by `tests/anatomy/test_n8n_ssrf_protection.py`.
- **MTI provider-flip reconcile.** Authentik's `ProxyProvider` is a Django
  multi-table-inheritance subclass of `OAuth2Provider` sharing the base PK and the
  globally-unique Provider `name`; flipping a service native_oidc→forward_auth
  (e.g. infisical) left a stale `OAuth2Provider` row that collided with the new
  proxy provider (the live symptom was infisical 404). `main.yml` now deletes the
  stale row idempotently before re-applying blueprints (no-op on a blank run).

### Other

- **Calibre library autowiring** — empty-DB bootstrap (`calibredb` create on an
  unseeded library, config dir + ownership) plus a seeded Project Gutenberg sample
  book, so a fresh Calibre-Web has a working library on the first run.
- **Remediation queue reconciled** — 16 pending / 69 resolved / 2 vendor-blocked of
  87 (CLAUDE.md + the queue's own summary block were stale; recomputed from items).
- **Housekeeping** — gov MFA strict pinned, `.gitignore` covers the operator's
  local Calibre-sync helper.

### Known / residual

- **SSO ceilings are upstream, not bugs** — portainer/infisical/metabase keep an
  own-login step (see the coverage table). `sso_autologin` global force-OIDC is
  dormant pending the per-service rollout.
- **Gov is scaffolding, not deployable** — ISDS (datové schránky) + NIA/eIDAS
  federation are greenfield; retention is metadata, not enforced. See
  `docs/compliance/gov-readiness-audit-2026q2.md`.
- **MTI reconcile is hard-coded to the known flip set** (`infisical`); a future
  native_oidc→forward_auth flip must add its slug to the `_FLIPPED` map in `main.yml`.

---

## v0.4-beta (2026-06-01)

> **Cross-platform + gov-readiness in one tag.** The playbook now provisions
> **Ubuntu 24.04 LTS** end-to-end (macOS Apple Silicon remains the reference
> platform; every Linux gate is macOS-byte-identical, so macOS behaviour is
> unchanged), and a Czech public-administration audit drove a remediation batch
> closing the structural GDPR / NIS2 P0 controls — all **default-OFF +
> `profiles/gov-local.yml` opt-in** (a non-gov run is byte-unchanged on both OSes).
> Plus a CVE remediation batch, observability metrics wiring, macOS idempotence,
> and a pre-release CodeQL/security hardening pass. Built + reviewed via
> multi-agent workflows; the post-batch adversarial review (35 agents → 22
> findings) is folded in.

### Cross-platform (Linux)

- **Platform seam.** `tasks/_platform.yml` resolves `nos_pkg_manager`
  (homebrew|apt|dnf), `nos_service_manager` (launchd|systemd-user), `nos_nginx_*`
  paths and `nos_docker_bin` per OS; every Homebrew install, brew shell-out,
  `launchctl`/`osascript`/`defaults`/`pmset` call and macOS system-settings task
  is gated on `nos_pkg_manager == 'homebrew'` / `ansible_os_family == 'Darwin'`.
  Gates resolve true on a Mac — macOS behaviour is byte-identical.
- **Host daemons on Linux.** Bone, Pulse, the backup orchestrator and the
  heartbeat render `systemd --user` units (`pazny.linux.systemd_user::ensure_unit`,
  `loginctl enable-linger`) instead of launchd; a Persistent= timer's
  bound-oneshot failure during provisioning is tolerated (the timer's service
  may not be ready when the timer starts). Bone/Pulse venvs build from the system
  `python3` (`tasks/python.yml` apt-installs `python3-venv`).
- **Wing on Linux.** Wing runs the FrankenPHP single binary downloaded to
  `~/.local/bin` (brew on macOS), composer driven via `frankenphp php-cli`;
  `~/.local` is forced operator-owned before the download so prior become/pip
  steps can't leave it root-owned and break the unprivileged fetch. The
  FrankenPHP static-binary download + systemd-user wiring still carry
  `NEEDS-VM-VALIDATION` markers (`roles/pazny.wing/tasks/main.yml`) — exercised in
  CI's minimal config but not yet full-runtime-validated on a real Ubuntu 24.04 VM.
- **TLS + proxy.** mkcert installs via apt on Linux (CAROOT is platform-aware);
  `templates/nginx/nginx.conf` is portable (epoll/`user www-data`/`/var`+`/run`
  on Linux, kqueue/homebrew/`user _www` on macOS). Per-service host-nginx vhosts
  stay macOS-only — **Traefik is the edge proxy on Linux**.
- **Docker.** `docker_bin` rebinds to `/usr/bin/docker`; a final `docker info`
  readiness probe (`nos_docker_ready`) gates the whole compose layer so a
  Docker-less host (e.g. a GitHub macOS runner that dropped Docker Desktop) skips
  the stacks gracefully instead of erroring; the compose-`ps` display tolerates a
  missing compose file on runners that never brought stacks up.
- **CI wet-test.** A standing `Integration (ubuntu-24.04)` job runs
  `ansible-playbook main.yml` once on a GitHub Linux runner against the minimal
  `tests/config.yml` (`install_traefik: false`, most services off — it exercises
  the base playbook, not the Docker stacks). The job has **no idempotence
  second-run** (unlike the macOS `Integration` matrix); it was iterated toward
  green when first added, with a chain of `fix(linux)` / `fix(ci)` commits closing
  the initial gaps (systemd timer-start tolerance, missing-compose-file `ps`,
  `~/.local` ownership, docker-readiness gating, macOS `python3` + ubuntu
  `/run/sshd` env gaps). Windows/WSL deferred.

### Gov / GDPR compliance

Four structural P0 controls + the data-subject-rights surface, all **default-OFF**,
opt-in via `profiles/gov-local.yml` (Tailscale off, FreePBX pinned off,
`enforce_mfa` / `require_disk_encryption` / `wing_audit_chain_enabled`). Flag-off
renders byte-identical. LIVE-validated on a `+all +gov` reconverge (`failed=0`):
`gdpr_consent` migrated on the real `wing.db` (ledger + CLI only — capture is
unwired, see Residual gaps) and the 31 previously auto-generated boilerplate
purposes ingested as authored purposes.

**Structural P0 controls:**

- **Enforced MFA + at-rest gate.** Dedicated `nos-tier1-mfa-flow` (TOTP +
  WebAuthn, `not_configured_action=configure` for inline self-enrol, passkey
  resident-key `preferred` — relaxed from `required` to cut enrollment friction
  from ~3 tries to first-try). The blueprint routes **every** Tier-1 provider
  (`authentik.tier == 1`) through this flow when `enforce_mfa=true` — currently
  the **9** Tier-1 OIDC/proxy providers (`portainer`, `infisical`, `grafana`,
  `spacetimedb`, `wing`, `influxdb`, `mailpit`, `openclaw`, `qdrant`). At-rest:
  `tasks/preflight-at-rest.yml` hard-fails on FileVault-off (macOS) / no-LUKS
  (Linux) before any personal-data service starts (`require_disk_encryption`). A
  post-validation fix (commit 76906f13) drops a brittle bootstrap trap — the
  original `50-mfa-policy` blueprint was atomically rejected over a
  `policybinding.target` referencing a non-existent `nos-enrollment-prompts` stage
  + an invalid `default-password-change-prompt`; the policy bindings are dropped
  (policy object retained for future manual/UI binding) and blueprint apply
  reordered so `50-mfa-policy` lands **before** `10-oidc-apps`, so Tier-1 provider
  `authentication_flow` resolves `nos-tier1-mfa-flow` on first apply. The
  `nos-password-policy` object (length-15 + zxcvbn) is created but **not**
  blueprint-bound to enrollment/password-change prompts for the same brittleness
  reason.
- **Backup encryption.** `backup.sh` AES-256-CBC/pbkdf2 stream filter client-side
  before `aws s3 cp` to RustFS (`resolve_openssl` locates the binary to survive
  the launchd PATH constraint + macOS LibreSSL compat gaps); `.enc` objects
  auto-decrypt on restore via matching passphrase in `tasks/restore.yml` (legacy
  plaintext restores unchanged; fails loud on passphrase mismatch).
- **Tamper-evident audit chain.** HMAC-SHA256 per-event hash-chain (Bone Python +
  Wing PHP writers, byte-parity proven by CI); WORM triggers block edits on signed
  rows; daily Pulse verify with cached verdict in the Wing header badge
  (off-by-default, `wing_audit_chain_enabled`). An `audit_chain_meta` singleton
  (k/v) anchors the cached verdict + purge boundary; `AuditChainRepository` caches
  so each render is one SELECT, not a full chain walk; `backfill-event-chain.php`
  (anchored in `wing post.yml`) records the OFF→ON toggle boundary. Verifier
  detects offline tampering segment-aware (legacy-compatible).
- **Breach-notification engine.** `BreachDeadlines` pure-math (Art-33 72h, NIS2
  24h/72h/1-month clamp, timezone-normalized); hourly Pulse scan (registered by
  the new `gdpr-breach-base` plugin, owner of the scheduled job) escalates overdue
  stages as CRITICAL notifications (dedup'd via deterministic UUID);
  `bin/breach-{file,scan,report}.php` CLIs + read-only Tier-1 `/breaches` view;
  operator runbook in `docs/incident-response-plan.md`; provably inert (empty
  register → no-op).

**GDPR data-subject rights:**

- **Art-7 consent registry.** `gdpr_consent` ledger (grant→withdraw) +
  `bin/record-consent.php`, decoupled from SSO naming (the `gate_sso_required`
  proxy is named via a never-called `consent_capture_satisfied` predicate). The
  ledger and CLI exist and were migrated; **consent capture is not wired into any
  onboarding flow** — all 3 seeded activities ship `capture_wired:false`. Ledger ≠
  operational consent enforcement (documented gap).
- **Art-15 right-of-access export.** `tasks/gdpr-export.yml` (opt-in
  `[gdpr-export,never]`, dry-run-first, `-e export_confirm=true`), audited
  `state/gdpr-export-map.yml`, single-exact-email Authentik auto-capture,
  `0700/0600` bundle. Strict RFC-5322 email-regex validation blocks
  shell-metacharacters in the one-liner (host-RCE guard).
- **Art-17 erasure.** Honest DSAR terminal status — `record-dsar.php --update`
  records `completed` only when zero manual/failed steps remain (the `--update`
  path was a no-op bug, now fixed: commits 3b9504b7, 39c74180). Erasure-map reach
  documented for backend stores (Redis/Qdrant/RustFS/wing.db/Loki/Tempo) + 22
  per-service deletes; a new Qdrant delete seam (commits ff032d53, 9f3716bd);
  **exact-email** Authentik match guards against cross-subject erasure; strict
  email-regex validation on the erasure one-liner (host-RCE guard); status-enum
  validation prevents invalid transitions being written. A CI erasure-coverage
  gate (commit 8d214817) requires every gdpr plugin to carry an Art-17 entry,
  closing the silent-green new-service loophole.
- **Art-30 records.** The 31 plugin `gdpr` blocks that previously shipped
  auto-generated boilerplate purposes now carry author-provided purposes
  (`purpose_generated` 31→0); the CI gate `test_gdpr_register_coverage.py`
  requires an author-provided purpose for every `end_users`-PII service (33 such
  services across the 65 plugin records, each with an authored purpose).
  Controller/DPO block (Art-30(1)(a)) added to the DPA register (commit 35119192)
  but **ships placeholder-unset** (operator must fill it).
- **Access control.** `GdprPresenter` is gated `minAccessTier=1` — tier-4 guests
  can no longer view all subjects' PII in `/gdpr`.

**Baseline-claim corrections.** Three doc-vs-code falsehoods resolved in code:
encrypted-backup claim now true (commit 877da0e7), Bone embeddings redaction
implemented, the non-existent `audit_retention` role claim corrected to describe
the real manual-only `tasks/audit-retention.yml`. `docs/compliance/gov-readiness-audit-2026q2.md`
carries a reconciled 2026-06-01 scorecard that supersedes the original audit
snapshot.

**Residual gaps (honest).** The code is present but key controls remain
inert/manual in the deployed config: retention enforcement is metadata-only (no
scheduled per-`retention_days` purge beyond `wing.db` events); consent capture is
unwired (never-called predicate); erasure automation depth is 3/29 (26 remain
manual); DSAR bundles are unencrypted on disk; at-rest is a host-disk gate, not
per-service TDE/KMS; Czech ISDS (datové schránky) + NIA/eIDAS federation is
greenfield (needs external endpoints). Per the reconciliation, the platform moved
from "four structural §32/§21 absences" to "those present + opt-in; enforcement +
Czech-integration still absent."

### Security & CVE remediation

- **Bone embeddings email redaction.** `redaction.py` strips RFC-5322 email
  addresses from upsert payloads before Qdrant (recursive dict/list walk; scope is
  addresses only — non-email PII passes through); default-on,
  `BONE_EMBED_REDACT=false` disables; 5 unit tests pin behaviour.
- **CVE batch (7 commits, `origin/master..HEAD`).** n8n 2.14.1→2.20.7 (RCE trio
  CVE-2026-44789/90/91 + vm2/convict/handlebars, REM-086); Tempo 2.10.0→2.10.3
  (S3 `encryption_key` exposure via `/status/config`, CVE-2026-28377, REM-036);
  ntfy v2.21.0→v2.22.0 (CVE-2026-39087, REM-087); FreeScout pinned
  `php8.3-1.17.159` (bundles 1.8.219; CVE-2026-32752/35584/39384 — CRITICAL
  broken-access-control / missing auth / authorization bypass, REM-069/070/071);
  `symfony/yaml` 7.4.10→7.4.13 (3 low alerts — Billion Laughs ReDoS,
  untrusted-input; composer.lock only).
- **Version-pin unshadow (commit cdfe43e4).** n8n / Tempo / FreeScout pins synced
  from role defaults to `default.config.yml` (vars_file outranks role defaults —
  the pins were dead on render).
- **REM verifications.** socket-proxy (REM-001) resolved by architecture —
  Portainer already routes through `docker-socket-proxy` (verified, commit
  2b8fb950); pyodide (REM-054) pinned in Open WebUI, marked resolved (it's
  browser-sandboxed, not server-side jupyter).
- **dnsmasq token leak (commit 935b1eb4).** Jinja template fix (string literal vs
  concatenation) stops the `dnsmasq_dev_domain` token leaking into the
  `systems.description` API + a Grafana table.
- **Trivy rescan** of 61 images conducted (585 CRITICAL / 5002 HIGH fixable,
  overwhelmingly stale base-image OS packages).

### Observability

- **cAdvisor + Gitea + Woodpecker metrics.** cAdvisor now stores per-container
  labels (`--store_container_labels=true`) for per-container CPU/memory metrics;
  Gitea (`GITEA__metrics__ENABLED` + bearer `GITEA__metrics__TOKEN`) and Woodpecker
  (`woodpecker_prom_token`) metrics endpoints enabled and scraped by Alloy with
  bearer-token auth (new scrape jobs).
- **MTTR recording rule.** `woodpecker_pipeline_mttr_seconds` derives mean time to
  recovery from failed pipeline-run durations (`03-apps.yml`).
- **Dashboard PromQL fixes** across 4 dashboards: `gitea_repos` →
  `gitea_repositories`, corrected Woodpecker MTTR query, broadened
  `container_cpu` regex patterns, BookStack/Firefly/ERPNext metric-name prefixes.
- **No new Loki panels** — the gitea-push / outline-edit / hedgedoc-ops log panels
  reuse the **existing** `loki.source.docker` logs. Business-metrics exporters
  (sql_exporter for Outline/BookStack/Firefly/ERPNext/RBAC, nextcloud_exporter,
  per-user login label) deferred pending new observability infrastructure.

### macOS — idempotence

- **Idempotence fixes across macOS tasks.** PECL extensions detect by `.so` file
  existence (immune to registry emptiness on the macOS runner — iterated `pecl
  info` → `pecl list | grep` → `.so` check); `dotnet tool install` checks
  stdout+stderr for "already installed"; nginx/PHP-FPM/backup probe `launchctl`
  state first so service-start reports changed only on a real load; dnsmasq
  restart is notify-driven. `~/.zshrc` uses `copy force:false` instead of `touch`.
  Docker login-item addition now gates on `/Applications/Docker.app` existing (no
  phantom re-add on Docker-less Macs).
- **Stateless secrets persisted for idempotence.** `wing_api_token` regenerated
  every run, re-rendering Pulse's launchd plist → churning agents' bearer; now
  persisted in `~/.nos/secrets.yml` alongside `authentik_secret_key`. Four more
  service tokens (`vaultwarden_admin_token`, `paperclip_auth_secret`,
  `outline_utils_secret`, `hedgedoc_session_secret`) moved from regen-every-run to
  persisted. Stateless (rotatable session/auth tokens, not data-encrypting); one
  one-time churn on first run after upgrade, `changed=0` thereafter.
- **Volatile timestamps eliminated.** `service-registry.json`, the Grafana
  dashboard, `hub-cards.json`, and `notification-routing.json` dropped per-run
  `generated_at` / `ansible_date_time.iso8601` footers (no consumer reads them;
  dropping them makes renders idempotent). Wing launchd bootstrap (`changed_when`
  now keys on `bootstrapped` in stdout, not unconditional true), heartbeat, and
  coexistence cutover/cleanup/provision nginx-reload handlers corrected to gate
  `changed_when` on actual module changes.
- **nos_state refresh tasks** (introspect/persist/state-report/upgrade-engine)
  marked `changed_when: false` — they stamp a fresh `generated_at` but represent
  runtime housekeeping, not config drift.

### Pre-release hardening

- **CodeQL alert clears.** ReDoS guards on the email regex (`_EMAIL_RE` bounded to
  RFC limits — dot-free labels + explicit separators; `py/redos` cleared, commits
  1059a079 / 19192c39); url-substring assertion converted to exact list membership
  in `test_parser`; path-containment hardening (realpath + is_relative_to) on
  patches/upgrades; `index.html` tab allowlist clamped (commit 317ae077).
- **Portainer fail-closed.** admin-init gate reverted from fail-open (`!=204`) to a
  fail-closed allowlist `[404, 303]` (commit 530d8b3a); retry loop (6×5s) on
  health-check flakes; container restart on cold-blank window timeout (commit
  bec68f3b).
- **Probe fixes.** FreeScout verify adds the trusted-host `Host` header (commit
  b980014b); all service HTTP probes stop following redirects
  (`follow_redirects: none` — 3xx/SSL mismatches no longer burn retries, commit
  e3f928bf, fixes GitLab and others).
- **E2E tester identity.** Tester email domain now derived from `TENANT_DOMAIN`,
  not `NOS_HOST` (fixes Authentik 400 on IP domains, commit f4fd5573); SEC-6 edge
  token added to the playwright browser context (commit 6d462f85).
- **Contracts regenerated.** `wing.db-schema.sql` + `wing.openapi.yml` synced for
  drift (`gdpr_consent` table/indexes + `/api/v1/audit/verify` route, commit
  b8ee023a).
- **Doc hygiene.** Closed-bug docblocks trimmed (genealogy dropped, present-tense
  invariants kept); "until C5 lands" headers retired (C5 shipped 2026-05-12);
  CLAUDE.md / TLDR / main.yml / framework-docs freshness pass.

### Deferred / still-open

- **Gov:** Czech ISDS (datové schránky) + NIA/eIDAS federation greenfield;
  retention enforcement metadata-only; consent capture unwired; erasure automation
  3/29; DSAR bundles unencrypted on disk; at-rest is host-disk gate not
  per-service TDE/KMS.
- **Linux:** ubuntu CI Integration runs once (no idempotence second-run); Wing
  FrankenPHP path carries `NEEDS-VM-VALIDATION` markers (CI-exercised, not
  full-VM-validated); OpenClaw (Ollama/CUDA), Hermes, host-nginx per-service vhost
  templates on Linux (Traefik covers routing), and fleet provisioning
  (p2p/server-client/mesh) remain macOS-only / greenfield. Windows/WSL deferred.
- **Observability:** business-metrics exporters (sql_exporter, nextcloud_exporter,
  per-user login label) pending new observability infrastructure.

---

## v0.3-beta (2026-05-30)

> 116 commits since `v0.2-beta`. Headline: the **upgrade/coexistence engine now
> applies for real**, **tiered RBAC** reaches Wing, the **observability veins**
> are wired end-to-end (Grafana SQLite dashboards finally populate), and the
> **hub autowiring** epic (P1/P2) lands. Validated on the operator's host: a full
> all-on run (`ok=1201 failed=0`, 33/33 smoke), e2e 3 core journeys green, and
> CI-equivalent `pytest` 1398 passed / ansible-lint 0 / lockfile in sync. Draft
> notes — the `dev → master` PR + `v0.3-beta` tag are the operator's to cut
> (admin bypass; outward-facing).

### Upgrade & coexistence engine — first real apply

- **Apply path exercised end-to-end** (`daf6a2b..23609c8`). The `--tags upgrade`
  flow had never run for real — dry-run short-circuited before handlers, masking
  a multi-defect apply path. Now: `nos_migrate.py` renders recipe step strings via
  Jinja2 against play-vars + engine tokens; the upgrade-table `exec.shell` wrapper
  aliases recipe `command:`→`cmd`; `compose.set_image_tag` gained `override` +
  `--force-recreate` + converge-on-drift; recipes aligned to live container names
  (`<stack>-<service>-1`, base `docker-compose.yml`); `upgrade_exclude` carve-out.
- **CRITICAL fix** — `lookup('vars', …)` needs `wantlist=true`; without it the
  play-var list collapsed to first characters (a big-review catch before a real
  PG run; no live damage). authentik major upgrades are forward-only (rollback
  `noop`; restoring a dump under new code half-migrates the schema).
- **Coexistence apply** — track now derived from the legacy `{service}.yml`
  override (inherits env/networks/healthcheck) so stateful tracks boot (pg17
  verified beside pg16); major-version data via logical dump/restore at cutover.
- **Advisor stale-recipe gaps closed** — gitlab `from_regex` fixed to match
  18.10+ (was `^18\.(0|[1-9])\.`, blind to two-digit minors); 5 at-target
  forward-coverage tracks (grafana/mariadb/infisical/authentik/redis) so the
  advisor matches the installed line instead of reporting stale. Re-validated:
  architect GREEN, all 12 services with a known version match a recipe.

### RBAC & SSO

- **Wing tiered RBAC via Nette identity** — `ForwardAuthUserStorage` builds a
  stateless `Nette\Security` identity from the `X-Authentik-*` forward-auth
  headers each request (roles = Authentik groups). `BasePresenter` gained a
  declarative `$minAccessTier` enforced by default in `startup()`.
- **SSO admin propagation** — Authentik group → service admin for GitLab,
  Gitea (OIDC groups), Open-WebUI; **pure-SSO onboarding** (public signup closed,
  external-only registration) so a blank run needs zero manual registration.

### Observability veins (data → Grafana / Wing)

- **Grafana SQLite dashboards finally populate** — the `wing_sqlite` datasource
  was orphaned by the P1 datasource split (declared only in an unrendered
  `all.yml.j2`), so every playbook-timeline / AI-agent SQLite panel was dark
  against a full `wing.db`. New **`grafana-wing` composition plugin** renders it
  (gated on `install_observability` + `wing-base`); plugin pinned `4.0.6`. New CI
  gate pins the dashboard→datasource→provisioning chain. *Verified live: the
  datasource registers, health OK, panels query `wing.db`.*
- **Stub panels → real queries** — `22-ai-agents` (token / success-rate / latency /
  model-distribution from `agent_sessions`) and `90-security` (CVE bargauge
  repointed off a non-existent table to `remediation_items`); every SQL
  live-verified.
- **Idempotent re-sync** — `bin/ingest-remediation.php` + `bin/ingest-pentest.php`
  UPSERT `/remediation` + `/pentest` from the authoritative JSON every run
  (migrate.php was one-shot and drifted); WHERE-guarded so a steady-state run is
  `changed=0`.
- **gitleaks scan fixed** — 8.x dropped `--source` (positional repo now); every
  nightly scan had been exiting 2, leaving the Wing Inbox + Secret Findings empty.

### Hub autowiring (P1/P2)

- `ui-extension.hub_card` harvested into `/hub` (icons via self-hosted lucide,
  tier overlay, RBAC `viewerTier`); Uptime-Kuma probes `hub_card.health_check`;
  Nextcloud↔OnlyOffice auto-wired; non-clickable backends filtered + a post-run
  URL-audit gate.

### Agent runtime

- **Sequential run lock** — `pulse-run-agent.sh` (the single chokepoint) now takes
  an atomic `mkdir` mutex; concurrent claude-CLI agents had crashed all
  participants. Stale lock reclaimed by PID liveness; released on any exit.
- claude-CLI session tokens captured; agent exit verdict (REVIEW vs GREEN)
  propagated; agent reports shown in the session transcript.

### Fleet (review only)

- `docs/archive/fleet-review-2026q2.md` reconciles the aspirational fleet design with
  reality (built vs greenfield), confirms the naming (fleet mode / Track F), maps
  the p2p / server-client / mesh topologies, and tees up the push-vs-pull
  control-plane decision. No live config changed.

---

## v0.2-beta (2026-05-23)

Bundle **A19** — plugin-wiring unification, orchestration health-wait, single-run autowiring — on top of the A1–A18 anatomy + security hardening that landed since v0.1-beta.

### Security

- **A1–A18 hardening** carried forward: ANSSI/GDPR baseline, per-service recovery posture catalog (SEC-15), Pulse stdout/stderr scrub before forwarding to Wing (SEC-9).
- **CSRF** — Wing Latte templates now emit a CSRF token on every browser POST form (SEC-14).
- **HMAC** — Bone event ingestion validates Standard-Webhooks-shaped HMAC; bash-built JSON bodies are canonicalized (`jq --sort-keys -c`) so signatures verify.
- **Secret lifecycle** — `agent_credentials.secret_ref` stays a pointer (`env:` / `infisical:`), resolved only in function-local memory; per-user invite credentials provisioned into Infisical + Stalwart (A18).

### Plugin wiring

- **Notification unification** — every service plugin now carries the canonical A9 severity-routing block (`on_critical` / `on_high` / `on_medium` / `on_low` / `on_info` → channels `wing-inbox` | `ntfy` | `mail`). **55/55 plugins** conform.
- **Wiring contract** — new CI gate `tests/anatomy/test_plugin_wiring_contract.py` pins the shape; `tools/plugin-wiring-report.py` measures coverage; `files/anatomy/docs/plugin-wiring-capabilities.md` documents which manifest blocks have a live consumer vs. forward-ready metadata.
- **Conformance fixes** — qdrant-base gained a `feature_flag`; gitleaks gdpr/schema blocks conformed.

### Orchestration

- **In-stream health-wait heartbeat** — stack bring-up changed from blocking `docker compose up --wait` to `docker compose up -d` plus a non-blocking health-wait (`tasks/stacks/wait-stacks-healthy.yml`, `tasks/stacks/health-tick.yml`, `files/anatomy/scripts/stack-health-probe.py`). Each ~15s tick prints a per-stack readiness line into the main `ansible.log` (e.g. `iiab: 17/18 ready (waiting: jellyfin[starting])`), so a long bring-up no longer freezes the log. Applied across core-up, stack-up, and apps-up. The wait is **STRICT** — every container must reach healthy, no tolerance escape hatch.
- **Sequential cold-blank** — new `default.config.yml` vars: `stack_up_parallel` (default `true`; set `false` to bring stacks up one at a time and avoid Docker-daemon saturation when enabling everything on a cold blank), `stack_up_wait_timeout` (default 540s; per-stack health budget), `stack_wait_tick_interval` (default 15s). Slow services (GitLab cold init ~12 min) just need a generous timeout.
- **All-on test profile** — `profiles/all-on.yml` enables every known-good service (excludes `erpnext` / `freepbx` / `spacetimedb`), forces sequential bring-up and a 1200s timeout: `ansible-playbook main.yml -e @profiles/all-on.yml [-e blank=true]`.
- **Sudo-free stack runner** — `tools/nos-stacks.sh [tag]` runs the Docker stack layer autonomously, without sudo and without the interactive prompt (compose-up tasks carry zero `become:`; `-e nos_sudo_password=''` skips the vars_prompt). For agent / CI-driven dev; refuses `blank=true`.

### Autowiring

- **Single-run bootstrap** — `authentik_bootstrap_token` is now playbook-generated and pinned as the Authentik blueprint token key, so Wing /users + invitations work on a single blank run (no fetch-tool second pass).
- **Woodpecker OAuth2** — the Woodpecker↔Gitea OAuth2 client is auto-created during provisioning.

### Blank-run hardening (2026-05-24)

End-to-end fixes surfaced while validating the STRICT all-on blank — each pins a tendon the heartbeat / strict-wait exposed:

- **Health-wait early-exit** — a `when:` on a *looped* `include_tasks` does not short-circuit, so the heartbeat ran the full time budget every time (and a flap on the final tick could false-timeout). Each tick task is now gated on `not _wait_done` so the loop genuinely stops at first all-ready.
- **Core-up ordering** — DB setup (MariaDB / PostgreSQL roles) now runs *before* the infra health-wait, so Authentik's Postgres role exists on a cold blank (was a deadlock: the strict wait blocked on a DB user that hadn't been created yet).
- **Blank-safe autowiring** — gitea repo + Woodpecker wiring uses Gitea **admin Basic auth over 127.0.0.1** (a pre-provisioned `gitea_api_token` is wiped by `blank=true` → 401); Woodpecker activation skips gracefully when its OAuth-derived PAT cannot yet exist. Post-config container checks resolve the running container by compose **label** — the old `-f <base> ps -q <svc>` returned "no such service" (base composes are `services: {}`), silently skipping every admin/OIDC task on a blank, so gitea had no admin user → 401.
- **Bone telemetry** — `app.deployed` HMAC timestamp uses the current epoch (`date +%s`), not `ansible_date_time.epoch` (frozen at gather_facts → >300 s stale on an hour-long blank → "timestamp out of window" 401). The play-level Bone restart handler now `bootout`+`bootstrap`s (env reload) instead of `kickstart -k`.
- **Uptime Kuma** — monitor setup tolerates Socket.IO event-delivery starvation under peak load: a larger per-event timeout, fail-fast after 3 consecutive timeouts (was a ~30-min hang), and a role-level retry until the load settles. A heavily-loaded blank may still defer monitor creation to a host-idle `--tags uptime_kuma` re-run (non-fatal — monitors/events are never lost).
- **Traefik** — Tier-1 routing resolves upstreams by container name on the shared network (the IPv6 host-gateway path produced 502s).

### Security review + hardening (2026-05-24)

A 5-agent audit (`docs/llm/security/2026-05-24-multiagent-review.md`) against the SEC-1..15 baseline — solid, no true CRITICALs after reconciliation. New hardening:

- **SEC-16** — weak-prefix gate: refuse `global_password_prefix` in {`changeme`, '', <12 chars} on a public tenant (it seeds DB roots, OIDC/agent secrets, admin pws). Lenient on `dev.local`; `-e allow_weak_prefix=true` bypass. Dead prefix-derived `NOS_DEPLOY_HMAC_SECRET` fallback + retired `BONE_SECRET` dropped from the launchd plists.
- **SEC-17** — Pulse execution-boundary command allowlist: the SEC-8 allowlist now enforces in the runner that spawns the process (not just the PHP create path), so *any* `pulse_jobs` row is gated. Child env scoped — secrets stripped (`WING_API_TOKEN`, …), job-supplied loader/PATH overrides (`DYLD_*`/`LD_*`) refused; `max_runtime_s` clamped.
- **SEC-18** — 83 `no_log: true` across 30 task files (admin pws/tokens were persisting in Wing's SQLite via the telemetry callback, which redacted by key-name only); the callback now scrubs by value too; every shell pipe gets `set -o pipefail`; the Bluesky bridge `| quote`s the Authentik-sourced email (injection).
- **portainer** — `--http-enabled` (2.19+ 303-redirects plain HTTP → HTTPS, which silently skipped admin-init + OAuth setup).

Deferred (tracked in the review): the OIDC/agent-secret compartmentalization refactor (mitigated now by SEC-16), deploy-trigger edge-gating, askpass-on-failure cleanup.

### Validated by

- STRICT all-on blank (`-e @profiles/all-on.yml -e blank=true`): **`failed=0`, zero fatal**, with the hardening live (M-SEC1 gate passes on a ≥12 prefix; `no_log`/pipefail post-config unaffected), **Kuma creating all 48 monitors in-context**, and **Bone `app.deployed` returning HTTP 200** (the timestamp fix).
- Gate suite green: `pytest` (1120 passed, 4 skipped — incl. the SEC-17 Pulse-allowlist tests), plugin-loader smoke (63 ok / 0 failed / 0 schema), wiring contract (DAG / gate-parity / notification), ansible-lint (`risky-shell-pipe` fixed, not skipped), `composer validate`, `--syntax-check`. `tests/e2e` runs in CI with a live tester identity.
