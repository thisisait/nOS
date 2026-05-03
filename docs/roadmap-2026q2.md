# nOS Multi-Session Roadmap — Q2 2026

> **Historical roadmap + decision log.** For the current session entry point,
> read [`docs/active-work.md`](active-work.md) first. Older Track A-G sections
> below are retained for context and may describe pre-2026-05-03 states that
> have since been superseded.
>
> Last updated: 2026-05-03 evening • commit: post-A6 plugin-loader (`717c446`) • by: pazny+claude
>
> **Q2 wave 1 (Tracks A-D) DONE.** Q2 wave 2 ALL DONE 2026-05-01 → 2026-05-03:
>
> | Track | Status | Commits |
> |---|---|---|
> | E — Tier-2 apps_runner wet test | ✅ DONE 2026-04-30 | 3 recovery |
> | J — Tech debt cleanup | ✅ DONE 2026-05-01 | 6 |
> | H — ansible-core 2.20+ tightening | ✅ DONE 2026-05-01 | 7 |
> | F — Dynamic instance_tld + per-host alias | ✅ DONE 2026-05-01 | 16 |
> | G — Cloudflare proxy + LE production | ✅ DONE wet 2026-05-03 | scaffold + 6 prod-cutover fixes |
>
> **Q2 wave 3 — Bones & Wings refactor** in flight 2026-05-03. Plan in
> [`docs/bones-and-wings-refactor.md`](bones-and-wings-refactor.md).
> Phases A0+A1+A2+A3a+A4+A6 landed (12 commits 2026-05-03 morning + afternoon).
> After the security-hardening full-blank gate, Phase A3.5 (Wing host-revert
> via FrankenPHP) is next; then A5/A6.5 validate contracts and the Track Q
> "tendons & vessels" doctrine. **Operator's runbook pointer:**
> [`docs/active-work.md`](active-work.md).
> Parallel implementation coordination lives in
> [`docs/bones-and-wings-bulk-plan.md`](bones-and-wings-bulk-plan.md).
>
> **Q2 wave 4 — Track Q autowiring debt consolidation** is post-PoC.
> See §"Track Q" below + the bones-and-wings refactor doc §13.1 for the
> 7-batch plan covering all 71 `pazny.*` roles.

## Mission (in 3 sentences)

nOS is an Ansible-managed self-hosted server suite that lets a 5–30
person organization replace SaaS office/identity/comms/CI with ~50 FOSS
services on a single host (Apple Silicon Mac today, Ubuntu LTS in
progress). Every service is wired into central Authentik SSO with
auto-OIDC; telemetry events flow through a Bone FastAPI dispatcher into
Wing's read model. The product we sell is **operational excellence
around the FOSS core** — setup, retainer, monitoring, hotfix priority —
not feature-flagged enterprise tiers.

## Where we are today (snapshot superseded)

> **Superseded:** this section is the 2026-04-29 snapshot preserved for
> historical context. Current verified state lives in `docs/active-work.md`
> and the bones & wings phase tracker in `docs/bones-and-wings-refactor.md`
> Appendix B.

### Current high-level state (2026-05-03 evening)

- **Security hardening gate:** current active track; operator full blank +
  `tools/post-blank.sh` is the next gate before more B&W implementation.
- **Last known green full blank:** `ok=920 changed=282 failed=0`.
- **Bones & Wings:** A0, A1, A2, A3a, A4, and A6 foundation landed.
- **Next B&W implementation:** A3.5 Wing host-revert via FrankenPHP, then A5
  contracts and A6.5 Grafana thin-role pilot.
- **Known B&W gaps:** Wing Pulse API missing, no production Pulse jobs,
  plugin side effects deferred beyond filesystem primitives, no committed
  OpenAPI/DDL contracts, no conductor/inbox/audit trail yet.

## Where we were on 2026-04-29

### Verified working (refreshed since last snapshot)
- **macOS Apple Silicon** primary target — last clean blank: `ok=842 changed=262 failed=0 skipped=364` (run 52853, 2026-04-29)
- **9 Docker stacks** (added `apps` for Tier-2): `infra` (12 healthy), `observability` (10), `iiab` (21), `devops`, `b2b`, `voip`, `engineering`, `data`, `apps`
- **Traefik containerized as primary edge proxy** (Track E1 / D1-D2 / commits `42c19c5..f9e57c1`) — two providers (file for Tier-1, Docker labels for Tier-2). 39+ Tier-1 routes auto-derived from `state/manifest.yml`. Host nginx is opt-in via `install_nginx: true`.
- **Tier-2 apps_runner — render path solid** (Track E2 partial / D3-D7 / commits `98a6d32..f9e57c1`) — `library/nos_apps_render.py` parses + GDPR-gates + token-resolves; `roles/pazny.apps_runner` renders compose override + persists secrets via canonical `to_nice_yaml`; image pre-flight catches typos before compose-up.
- **Coolify hybrid importer** — `tools/import-coolify-template.py` rewrites `${SERVICE_*}` → `$SERVICE_*_X` and scaffolds GDPR TODO block; 13 unit tests
- **4 pilot manifests** authored: `apps/{twofauth,roundcube,documenso}.yml` + `apps/plane.yml.draft`. All parse cleanly.
- **Authentik SSO** with auto-OIDC for ~30 apps, RBAC tier 1–4 mapping
- **State framework** (state.yml + migrations + upgrades + coexistence) with JSON Schema validation
- **Wing telemetry pipeline** end-to-end tested
- **CI**: lint + syntax-check matrix (ubuntu-22.04, ubuntu-24.04, macos-14) + pytest job
- **Tests**: 386 Python passing (355 baseline + 31 new for apps render + Coolify importer + schema), 71 PHP passing

### NOT YET WET-TESTED (code shipped, never ran end-to-end on a healthy apps stack)
- **Tier-2 apps stack containers running healthy** — three blank attempts so far: image typos (Documenso ghcr→docker.io, twofauth org name) and one indent-drift bug stopped the apps stack at 0 containers each time. Pre-flight image probe (commit `f9e57c1`) prevents repeat. Fourth blank should produce 4 healthy containers.
- **Tier-2 observability hooks (8 of them)** — never executed because they are gated behind apps stack-up rc=0. Specifically: service-registry append, Wing systems re-ingest, Authentik blueprint reconverge, Bone HMAC `app.deployed` events, Portainer apps endpoint, Kuma monitor extension, GDPR upsert via `bin/upsert-gdpr.php`, smoke-catalog runtime extension.

This is what Track E is for — close that gap with a real wet test.

### Reference docs (read these before starting any track)
- [`docs/agent-operable-nos.md`](agent-operable-nos.md) — strategic vision (Spine, Eye, Ear, Hand anatomy extensions)
- [`docs/domain-flip-operator-guide.md`](domain-flip-operator-guide.md) — Wedos + Cloudflare + ISP runbook for TLD flip
- [`docs/security-triage.md`](security-triage.md) — CodeQL alert rationale + maintenance protocol
- [`docs/framework-plan.md`](framework-plan.md) — state/migration/upgrade engine spec (older, authoritative for engine internals)
- [`CLAUDE.md`](../CLAUDE.md) — repo instructions for AI assistants

### Live in working tree but uncommitted
- `roles/pazny.spacetimedb/` — operator's parallel work, not part of this roadmap
- `templates/nginx/sites-available/spacetimedb.conf` — same
- alloy / nginx / core-up / default.config edits — same

---

## Roadmap: four tracks, run in this order

### Track A — Containerize Bone + Wing **(unblocks B+C)**

**Status: code-complete on master 2026-04-26.** Final acceptance gate is a successful run of `ansible-playbook main.yml -K --tags infra,iiab` on the operator's host followed by the smoke checklist in A7. Migration recipe `migrations/2026-05-01-bone-wing-to-container.yml` handles the cut over from launchd Bone + Homebrew php-fpm. After verification, mark this track DONE and unblock Tracks B + C.

#### Why this comes first
Bone (FastAPI) and Wing (PHP-FPM via Homebrew) are currently host-native via launchd plist + nginx vhost pointing at `127.0.0.1:8099` / Unix socket. This means:
- Linux port has to re-engineer launchd → systemd for both services
- HMAC secret distribution is launchd-env, not 12-factor
- Wing PHP-FPM is tied to Homebrew's PHP version, not pinnable
- Mac upgrade of PHP can break Wing silently

Containerized Bone + Wing eliminates all four issues and unlocks Tracks B + C.

#### Scope
1. **Containerize Bone**
   - `Dockerfile` already exists at `files/bone/Dockerfile` — verify it builds
   - Refactor `roles/pazny.bone/` from launchd plist to compose-override pattern
   - Move into `infra` stack (next to Authentik / Infisical)
   - Wing telemetry callback URL stays the same — Bone listens on iiab_net at `bone:8099`, fronted by nginx at `api.<tld>`
   - HMAC secret via Docker secret or env-from-file (not env-string)

2. **Containerize Wing**
   - Use `php:8.3-fpm-alpine` base, add Composer install + Nette app + SQLite
   - Move into `iiab` stack (PHP app cluster)
   - `wing.db` path moves to a named volume (`infra_wing_data` or `iiab_wing_data`)
   - nginx vhost adapts: `fastcgi_pass wing:9000` instead of `unix:/.../php-fpm.sock`
   - Composer install at build time, not Ansible-host time

3. **State migration for existing installs**
   - Migration recipe `migrations/2026-05-01-bone-to-container.yml`:
     - Detect: `~/Library/LaunchAgents/eu.thisisait.nos.bone.plist` exists
     - Action: `launchctl bootout` + remove plist + bind-mount `~/bone/data/` into new container
     - Verify: `curl http://api.<tld>/api/health` returns 200 from container
     - Rollback: re-render plist + start
   - Same for Wing — `~/wing/app/data/wing.db` → named volume; old path becomes read-only backup symlink for one cycle

4. **Test plan**
   - Existing 71 PHP tests run unchanged
   - End-to-end: `WING_EVENTS_DEBUG=1 ansible-playbook /tmp/smoke.yml` should produce events that land in `wing.db` (validated already, just re-validate post-container)
   - Watchtower should now monitor Bone + Wing image tags too

#### Files to touch
```
roles/pazny.bone/
  defaults/main.yml          # bone_image: ghcr.io/...; remove launchd vars
  tasks/main.yml             # remove launchd, render compose template
  templates/compose.yml.j2   # NEW
  templates/bone-launchd.plist.j2  # delete (or move to backup)
  handlers/main.yml          # docker compose up bone instead of launchctl

roles/pazny.wing/
  defaults/main.yml          # wing_image, wing_php_version pinned
  tasks/main.yml             # remove Homebrew composer + nginx-on-host steps
  templates/compose.yml.j2   # NEW (php-fpm container)
  templates/nginx-fastcgi.conf.j2  # NEW (nginx → fastcgi_pass wing:9000)

migrations/
  2026-05-01-bone-to-container.yml
  2026-05-01-wing-to-container.yml

tasks/stacks/stack-up.yml    # add bone + wing to compose render loop
tasks/stacks/core-up.yml     # bone joins infra stack alongside Authentik

main.yml                     # remove import_role pazny.bone (now in stack-up)
```

#### Exit criteria
- [ ] `docker ps` shows `infra-bone-1` + `iiab-wing-1` (or wherever they land)
- [ ] `~/Library/LaunchAgents/eu.thisisait.nos.bone.plist` is gone post-blank
- [ ] Wing telemetry pipeline: 1949+ events on a fresh blank
- [ ] Migration recipe handles `dev.local` → containerized upgrade for existing installs
- [ ] All 71 PHP tests + 355 Python tests pass

#### Estimate: 2 days

---

### Track B — Agent identity (Authentik-bound) **(blocked on A)**

#### Why this matters
GDPR demands that **every action against personal data has an identifiable
actor**. With AI agents calling Bone/Grafana-MCP/PHP CLI today via shared
secrets (BONE_SECRET), there's no audit who did what. For SMB clients to
trust nOS, every agent must be a first-class Authentik identity with
RBAC + token lifetime + tier-bound capability.

#### Scope
1. **Authentik blueprint additions**
   - `state/blueprints/authentik/agents-tier-{1,2,3,4}.yaml` — group definitions
   - Each agent gets an `application` + `oauth2provider` with grant_type=`client_credentials`
   - Token lifetime: 15 min (short — agent re-fetches as needed)

2. **Bone JWT verifier**
   - New module `files/bone/auth.py`:
     - Fetches JWKS from `https://auth.<tld>/application/o/<app>/jwks/`
     - Validates JWT signature + expiry
     - Extracts `sub` (agent username) + `groups`
     - Maps group → capability set (drawn from `Hand` org doc)
   - New dependency `Depends(require_capability("events:write"))` etc.
   - **Coexists** with existing `_verify_api_key` for backward-compat during transition (deprecate after 90 days)

3. **Agent provisioning API in Bone**
   - `POST /api/agents/draft` — user submits agent draft
   - `GET /api/agents/draft/queue` — admin sees pending
   - `POST /api/agents/draft/{id}/approve` — admin approves, Bone:
     - Calls Authentik API to create user + group binding
     - Provisions OIDC client_credentials
     - Stores credentials in Infisical at `agents/<owner>/<agent_name>`
     - Emits audit event `agent_provisioned` to wing.db
   - `POST /api/agents/draft/{id}/deny` — with reason
   - `DELETE /api/agents/{id}` — revoke (deletes Authentik user + Infisical secret)

4. **Wing UI: `/agents` page**
   - User: list own agents, "Create agent" form, view current credentials path in Infisical
   - Admin: pending queue with approve/deny + reason
   - Audit: per-agent activity log filtered from wing.db.events

5. **Capability matrix** (`state/schema/agent-capability.schema.json`):
   ```yaml
   tier_1_admin:
     - "events:write events:read"
     - "state:write state:read"
     - "playbook:execute"          # irreversible, requires confirmation
   tier_2_manager:
     - "events:write events:read"
     - "state:read"
     - "patch:draft"               # can propose, not apply
   tier_3_user:
     - "events:write events:read"
     - "state:read"
     - "wing:read"
   tier_4_guest:
     - "events:read"
     - "wing:read"
   ```

6. **Migration for existing agents**
   - OpenClaw + any existing automated callers currently use BONE_SECRET
   - Migration: provision `agent.system.openclaw` with tier-1 → JWT
   - Old BONE_SECRET path stays for 90 days then removed

#### Files to touch
```
files/bone/
  auth.py                    # NEW — JWT verifier
  agents.py                  # NEW — agent CRUD
  main.py                    # add new endpoints + Depends(require_capability())

state/schema/
  agent-capability.schema.json    # NEW
  agent-draft.schema.json         # NEW

state/blueprints/authentik/
  agents-tier-1.yaml         # NEW
  agents-tier-2.yaml         # NEW
  agents-tier-3.yaml         # NEW
  agents-tier-4.yaml         # NEW

files/project-wing/app/Module/Agents/
  AgentsPresenter.php        # NEW
  templates/                 # NEW

tests/
  bone-jwt/                  # NEW pytest suite
  bone-agents/               # NEW
```

#### Exit criteria
- [ ] OpenClaw runs as `agent.system.openclaw` with tier-1 JWT
- [ ] Operator can create + approve + revoke an agent via Wing UI
- [ ] All Bone /api/v1/* routes accept JWT (BONE_SECRET still works for 90d)
- [ ] wing.db has `agent_id` column populated for events triggered by agents
- [ ] GDPR DPA register lists every agent's data scope

#### Estimate: 4–5 days

---

### Track C — Linux infra stack green **(parallel to B)**

#### Why this matters
SMB market is Linux. Nothing meaningful sells until "infra stack runs on
Ubuntu LTS". Until then, nOS is a tinkerer's macOS toy.

#### Scope
1. **CI Linux integration job** (matrix syntax-check already running)
   - Add new job `integration-linux` running on `ubuntu-24.04`
   - Limited tags: only `infra` stack tagged tasks
   - Validates: PostgreSQL + MariaDB + Redis + Authentik + Traefik + Infisical end-to-end
   - Initial blank = expected to fail; iterate to green

2. **Real `pazny.linux.apt` implementation**
   - Replace stub with: apt update, apt-key add for third-party repos, install loop
   - Mirror pazny.mac.homebrew's outdated → upgrade → report flow
   - Auto-detect Debian vs Ubuntu, pick correct repo lines (Docker, Tailscale)

3. **Real `pazny.linux.systemd_user` implementation**
   - `tasks_from=ensure_unit` callable from any role
   - Renders `~/.config/systemd/user/<name>.{service,timer}` from a unified spec
   - Used by linux-equivalents of pazny.bone (post-Track-A: not needed if Bone is containerized!), pazny.acme renewal, pazny.backup
   - Calls `loginctl enable-linger $USER` once

4. **Conditional roles for OS-portability**
   - `pazny.dotfiles` — already mostly portable, just verify on Ubuntu
   - `pazny.nginx` — install via apt instead of brew on Linux; vhost paths under `/etc/nginx/sites-available`
   - `pazny.acme` — already portable (acme.sh is bash); systemd timer instead of launchd plist
   - `pazny.backup` — same

5. **Drop Mac-only services on Linux** (gated, no replacement attempted in v1)
   - `pazny.openclaw` — MLX is Apple Silicon only; emit deprecation warning + skip on Linux. Linux replacement = Ollama-CUDA, separate role, post-v1.
   - `pazny.mac.dock`, `pazny.mac.mas`, `pazny.iiab_terminal` — Mac-only, gate off

6. **Test target: Ubuntu 24.04 LTS ARM64**
   - Lima/Multipass on Mac Studio: `multipass launch noble --cpus 4 --memory 8G --disk 60G --name nos-test`
   - Mount `/Users/pazny/projects/nOS` into VM
   - Iterate `ansible-playbook main.yml -K --tags infra,observability` until green
   - x86_64 follow-up after ARM64 lands

#### Files to touch
```
.github/workflows/ci.yml     # add integration-linux job

roles/pazny.linux.apt/
  tasks/main.yml             # real impl, not stub

roles/pazny.linux.systemd_user/
  tasks/main.yml             # real impl
  tasks/ensure_unit.yml      # NEW — reusable from other roles
  templates/service.j2       # NEW
  templates/timer.j2         # NEW

roles/pazny.acme/tasks/main.yml          # systemd timer branch when not Darwin
roles/pazny.backup/tasks/main.yml        # same
roles/pazny.nginx/tasks/main.yml         # apt branch when Debian/Ubuntu
roles/pazny.dotfiles/tasks/main.yml      # verify Ubuntu, branch if needed

main.yml                     # gate openclaw / mac.dock / mac.mas / iiab_terminal on Darwin
```

#### Exit criteria
- [ ] CI job `integration-linux` is green on push
- [ ] `multipass exec nos-test -- curl https://auth.dev.local` returns 200 from inside the VM
- [ ] Authentik admin login works in Firefox-on-host pointing at the VM's IP
- [ ] All 6 infra services healthy: MariaDB, PostgreSQL, Redis, Authentik, Traefik, Infisical
- [ ] Documentation update: README "Supported platforms" table now lists Ubuntu 24.04 LTS as beta

#### Estimate: 5–7 days

---

### Track D — ANSSI hardening + GDPR baseline **(parallel to B+C, ships docs immediately)**

#### Why this matters
Every consulting conversation with a CZ/EU SMB ends with "but is it
GDPR-compliant?". Today the answer is "yes by architecture, but I don't
have a one-pager you can show your DPO". Track D produces that one-pager
and the engineering work that makes it true.

#### Scope
1. **`pazny.hardening` role (Linux-only)**
   - Translate from `cloud-gouv/securix/modules/anssi/`:
     - `kernel-options.nix` → `templates/sysctl-anssi.conf.j2` (drop into `/etc/sysctl.d/99-anssi.conf`)
     - `ruleset.nix` → `templates/auditd.rules.j2`
     - `pam/u2f.nix` → optional FIDO2/PAM (later)
   - Default `install_hardening: false` — opt-in for production deployments
   - `meta/main.yml` cites securix as design reference; commit message links the upstream files

2. **GDPR data classification taxonomy**
   - New file `state/gdpr-classes.yml`:
     ```yaml
     classes:
       none:        no personal data
       internal:    business data, no PII
       personal:    Article 4 PII (names, emails, IDs)
       sensitive:   Article 9 special category (health, biometrics)
     ```
   - Each entry in `state/services.yml` (when Spine lands) declares `gdpr_class`
   - Wing dashboard `/gdpr` view aggregates: services × classes table

3. **Audit retention policy**
   - `wing.db.events` — 365 days default, configurable per `wing_audit_retention_days`
   - Authentik `/events` — same, cron job calls `ak events_purge --older-than 365d`
   - Daily housekeeping role `pazny.audit_retention`

4. **DPA register generator**
   - Ansible task: render `state/dpa-register.md` from `state/services.yml` + `state/gdpr-classes.yml`
   - Output: list per service of: data classes processed, retention, encryption-at-rest method, subprocessors (CF, Wedos, Apple, Docker Hub)
   - Operator hands this to their DPO at audit time

5. **Encryption baseline doc**
   - `docs/security-baseline.md` — what's encrypted at-rest, in-transit, key custody
     - At-rest: FileVault (Mac) / LUKS (Linux) — operator responsibility, documented
     - Per-service: Infisical KMS for sensitive secrets; service-internal AES for PG `pgcrypto` extension
     - In-transit: ACME wildcard cert, no plaintext on the wire
     - Key custody: `~/.nos/secrets.yml` mode 0600, in-Infisical for runtime, no cloud KMS dependency

6. **Right-to-be-forgotten cookbook**
   - Per-service script template `roles/pazny.<svc>/tasks/forget_user.yml`:
     - Authentik: revoke sessions + delete user
     - Nextcloud: `occ user:delete`
     - Outline: API DELETE
     - Bone: emit `gdpr_forget_user` event with userId
   - Emit one orchestration task `tasks/gdpr-forget.yml` that fans out to all services

7. **NGI proposal alignment**
   - Reference securix in NGI Zero Commons proposal as design lineage
   - Include DPA register output as appendix
   - GDPR baseline doc is a sales asset

#### Files to touch
```
roles/pazny.hardening/
  defaults/main.yml          # NEW
  meta/main.yml              # NEW (cite securix)
  tasks/main.yml             # NEW
  templates/sysctl-anssi.conf.j2   # NEW
  templates/auditd.rules.j2  # NEW
  README.md                  # NEW — "translated from securix v0.X.Y"

state/
  gdpr-classes.yml           # NEW
  dpa-register.md            # NEW (generated)

docs/
  security-baseline.md       # NEW — operator + DPO reference
  gdpr-compliance.md         # NEW — Article 30 register explanation

roles/pazny.audit_retention/
  defaults/main.yml          # NEW (retention_days, etc.)
  tasks/main.yml             # NEW

tasks/gdpr-forget.yml        # NEW — operator command-driven user deletion

roles/pazny.<svc>/tasks/forget_user.yml   # per service, ~12 to add
```

#### Exit criteria
- [ ] `ansible-playbook main.yml --tags hardening` on Ubuntu installs ANSSI sysctl + auditd
- [ ] `state/dpa-register.md` is generated, lists 60+ services with classes
- [ ] `tasks/gdpr-forget.yml -e user_id=...` removes user from Authentik + Nextcloud + Outline + Bone audit (emits "forgotten" event)
- [ ] Audit retention cron purges events older than `wing_audit_retention_days`
- [ ] `docs/security-baseline.md` exists and is one-pager-quality for handing to a DPO

#### Estimate: 7–10 days (mostly docs + light code)

---

### Track E — Tier-2 apps_runner wet test **(active — D8-D9)**

**Status: render path code-complete on master 2026-04-29 (commits `d3a9d35..f9e57c1`); deploy path + observability hooks UNVERIFIED.** Three blank-runs hit image typos / indent drift; image pre-flight (`f9e57c1`) is the last layer of defence. Track exit = 4-th blank produces a healthy apps stack with all 8 post-hooks proven.

#### Why this comes first (before dynamic-domain refactor F)
Without a working Tier-2 deploy, refactoring `instance_tld` → `tenant_domain + host_alias + apps_subdomain` (Track F) is vacuum-state design. Tier-2 wet test surfaces the operational shape that F has to honour.

#### Scope
1. **Single-pilot wet test (D8)** — `apps/twofauth.yml` only. Promote `apps/roundcube.yml` and `apps/documenso.yml` to `.draft` so the runner ignores them. Get this ONE to:
   - 1 container running healthy in `apps` stack (verifiable: `docker compose -p apps ps`)
   - Traefik route visible (verifiable: `curl -s http://127.0.0.1:8080/api/http/routers | jq '.[] | select(.name | contains("twofauth"))'`)
   - Authentik proxy provider visible (verifiable: Authentik admin UI / Applications)
   - Wing `/hub` lists `app_twofauth` row (verifiable: browser at https://wing.dev.local/hub or `sqlite3 ~/wing/wing.db "SELECT id, name FROM systems WHERE id LIKE 'app_%'"`)
   - GDPR row inserted (verifiable: `sqlite3 ~/wing/wing.db "SELECT id, legal_basis FROM gdpr_processing"`)
   - Bone `app.deployed` event in events.jsonl (verifiable: `tail ~/.nos/events/playbook.jsonl | grep app.deployed`)
   - Kuma monitor green (verifiable: https://kuma.dev.local — login → Monitors)
   - Smoke probe passes (verifiable: `python3 tools/nos-smoke.py --tier 2`)
   - Browser → `https://twofauth.apps.dev.local` → 302 → Authentik login → 200 + 2FAuth UI
2. **Multi-pilot wet test (D9)** — un-draft `roundcube` + `documenso` once `twofauth` is fully observable. Verify same checklist for each. Plane stays `.draft` (13 containers, separate stress-test sprint).

#### Files to touch
- `apps/twofauth.yml`, `apps/roundcube.yml`, `apps/documenso.yml` — only if any one of them surfaces a manifest-level issue (image, env, healthcheck)
- `roles/pazny.apps_runner/tasks/post.yml` — only if a hook misfires; otherwise no edits
- `docs/tier2-wet-test-checklist.md` (NEW) — operator's copy-paste checklist; primary deliverable of D8

#### Exit criteria
- 4 healthy containers (twofauth + roundcube + documenso + documenso-db) in `apps` stack
- 3 entries each in: service-registry.json, Wing systems table, Authentik proxy providers, Kuma monitors, gdpr_processing rows
- 3 `app.deployed` events in `~/.nos/events/playbook.jsonl`
- `state/smoke-catalog.runtime.yml` exists with 3 entries
- `python3 tools/nos-smoke.py --tier 2` returns 0 failures
- Track marked DONE; new commits use `feat(apps): ` for additions, `fix(apps): ` for follow-ups
- `docs/tier2-wet-test-checklist.md` published — re-runnable forever

---

### Track F — Dynamic instance_tld + per-host alias **(after E, D10)**

**Status: not started.** Currently `instance_tld: dev.local` is host-default; `dnsmasq_dev_domain` is local-only DNS suffix; mkcert wildcards `*.dev.local`. For multi-host fleets (operator's vision: Ansible runner on a Raspberry Pi managing several Macs across a tenant network) and for public deploy, FQDN composition needs to flex.

#### Why this comes after E
Dynamic-domain design is informed by what Tier-2 actually looks like in production. Refactoring before the wet test means doing it twice.

#### Scope
1. **Decompose `instance_tld`** into composable parts (operator-set in `config.yml`):
   - `tenant_domain` — the TLD the tenant owns (e.g. `acme.com` for public, `dev.local` for solo dev)
   - `host_alias` — per-host prefix when many nOS hosts share a `tenant_domain` (default `""`; e.g. `media`, `office`)
   - `apps_subdomain` — Tier-2 isolation segment (default `apps`; settable to `""` for direct `<svc>.<tenant_domain>`)
   - Resolved FQDN pattern: `<svc>[.<host_alias>][.<apps_subdomain>].<tenant_domain>` (segments dropped when empty)
2. **Refactor consumers** — anywhere `instance_tld` appears (about 50 templates + role tasks):
   - `pazny.acme` — wildcard cert SAN list
   - `pazny.traefik` static config + dynamic services file provider
   - `library/nos_apps_render._fqdn_for` + `module_utils.nos_app_parser.resolve_tokens` (already accept `apps_subdomain` kwarg from F precedent)
   - `templates/service-registry.json.j2`
   - `roles/pazny.dnsmasq` — local-only resolver suffix
   - `tasks/nginx.yml` (legacy fallback path)
3. **Backwards-compat default** — `tenant_domain: "dev.local"`, `host_alias: ""`, `apps_subdomain: "apps"` reproduces today's hostnames byte-for-byte. Existing deploys survive without manual edits.
4. **Test**: blank with `tenant_domain: "foo.example"` produces a fully working set of FQDNs that match (a) Traefik routes, (b) Authentik OIDC redirect_uris, (c) cookie domain, (d) cert SAN.

#### Files to touch
- `default.config.yml` — new vars + deprecation alias for `instance_tld`
- `roles/pazny.{acme,traefik,dnsmasq}/` — consume new vars
- `library/nos_apps_render.py` — already wired
- `templates/service-registry.json.j2` — derive URL from new vars
- `migrations/2026-05-XX-instance-tld-decomposition.yml` (NEW) — migrates old config.yml to new shape
- `docs/operator-domain-naming.md` (NEW)

#### Exit criteria
- Two test blanks: one with `tenant_domain: "dev.local" + host_alias: ""` (today's behaviour, byte-for-byte same hostnames) + one with `host_alias: "lab"` (every FQDN flips to `<svc>.lab.<rest>`)
- Both blanks: smoke 39+/39+ green, Tier-2 still works
- Migration recipe ships
- `docs/operator-domain-naming.md` published

---

### Track G — Cloudflare proxy + LE production exposure **(after F, D11)**

**Status: 1/3 prerequisites already exist.** `pazny.acme` role with Cloudflare DNS-01 challenge is ready (per Track A's existing notes). Missing: operator wiring + public-deploy decisions for Bluesky PDS, optional Mastodon, and primary local SMTP server.

#### Why this comes after F
F sets up `tenant_domain` as a real public domain. Without F, public deploy is a hack (config.yml manually overrides `instance_tld`). G picks up where F leaves off.

#### Scope
1. **Public-exposed services (operator-decided)**:
   - **Bluesky PDS** — already in infra stack, has `bluesky_pds_hostname`, just needs port-80/443 exposure via Traefik + LE wildcard cert + CF orange-cloud (or grey-cloud for federation requirements TBD)
   - **Local SMTP relay** (Stalwart-class — see Track G appendix) — primary motivation: outbound mail for all services that today log-only via Mailpit. INBOUND IMAP optional. Stalwart over alternatives because: written in Rust (Apple Silicon-friendly), single binary, supports SMTP+IMAP+JMAP, has its own admin UI.
   - **Mastodon** (optional, time-permitting) — requires real public DNS; cleanly fits Tier-2 once F lands
2. **Cloudflare proxy modes** in `default.config.yml`:
   - `cloudflare_proxy_mode: off` (default — DNS-only, public IP visible)
   - `cloudflare_proxy_mode: flexible` — orange-cloud, edge TLS to nOS plain HTTP (fast but downgrades end-to-end TLS)
   - `cloudflare_proxy_mode: full` — orange-cloud, edge TLS to nOS HTTPS (LE cert at origin)
3. **Operator-facing public deploy guide** — `docs/public-deploy.md`
4. **Wing UI deep-link refresh** — `wing.dev.local/hub` and `/apps` URLs reflect `tenant_domain` (no hardcoded `dev.local`)

#### Files to touch
- `default.config.yml` — `cloudflare_proxy_mode`, `expose_public: [bsky, smtp, ...]`
- `roles/pazny.acme/` — already mostly there
- `roles/pazny.bluesky_pds/` — public exposure flag
- `roles/pazny.smtp_stalwart/` (NEW) — full role
- `templates/traefik/dynamic/services.yml.j2` — public router blocks gated on `expose_public` membership
- `docs/public-deploy.md` (NEW)

#### Exit criteria
- `tenant_domain: <real-domain.tld>` + `cloudflare_proxy_mode: full` blank produces:
  - Bluesky PDS reachable from external network at `https://bsky.<tenant_domain>` with valid LE cert
  - Local SMTP server accepting outbound mail from at least 5 services
  - Wing UI shows correct tenant URLs in `/hub` cards
- Operator runbook in `docs/public-deploy.md` survives a fresh-eyes read

---

### Track J — Tech debt cleanup **(2026-05-01, between E and H per O16)**

**Status: DONE 2026-05-01 in 6 commits `0a6a960..f321b6e` + this commit.** A focused 3-3.5h sweep landing all the debris from Track E recovery (mailpit cross-stack, misleading task names, false-friend traps) plus an opportunistic pull-forward of the `ansible_env` modernization that simplified Track H.

#### Why this came before H/F/G
Three Track-E recovery commits (`8091c07`, `a8fc804`, `d4e99f2`) shipped working code but left footprints — comments that lied about architecture, file names that misled the next reader, a misnamed warning that led ME to misdiagnose its own logs. Cleaning these up before tackling Track H (mechanical ansible-core upgrade), Track F (108-occurrence `instance_tld` refactor), or Track G (new Stalwart role + public deploy) means each downstream track starts from a tree that doesn't actively mislead.

#### Scope (6 phases, 6 commits)
1. **Phase 1 — apps-up clarity polish** (commit `0a6a960`). The post-hook gate at `tasks/stacks/apps-up.yml:120` was correct all along (`when: rc == 0`); audit of yesterday's logs showed `skipping: [127.0.0.1]` on the include task when rc=1. I had misread Ansible's task-registration log lines. This commit just renames the warning task and adds the Section 12 recovery hint to its body.
2. **Phase 2 — mailpit dual-attach** (commit `9708133`). Mailpit was on `iiab_iiab_net` only — Documenso couldn't resolve `mailpit:1025` from `apps_apps_net`. Added `shared_net` to mailpit's networks list (parity with infra postgres / mariadb / redis / authentik dual-attach). Fixed lying comment that claimed apps reached mailpit "inside the iiab_net docker network".
3. **Phase 3 — `pazny.authentik post.yml` rename** (commit `326a592`). The 32-line file did ONLY readiness probe but its name suggested post-deploy reconverge. `git mv post.yml health.yml` + update single caller + 25-line docstring pointing future readers to the canonical `tasks_from: blueprints.yml + meta: flush_handlers` reconverge pattern.
4. **Phase 4 — `ansible_env` → `ansible_facts['env']`** (commit `85b933b`). Pulled forward from Track H. Actual count: 9 occurrences in 6 files (state-manager + coexistence + pre-migrate + state-report). Track H is now ~1 day instead of 2 (no sed pass needed).
5. **Phase 5 — pytest collection cleanup** (commit `f321b6e`). 4 collection errors on `tests/authentik/*` (missing `responses`) + `tests/bone_auth/*` (missing `jwt` — Track B work that hasn't landed). Top-of-file `pytest.importorskip` so collection succeeds without optional deps. Net: 431 tests collected (was 8 collected + 4 errors).
6. **Phase 6 — roadmap + active-work + remember refresh** (this commit). Decisions O12-O16 logged. Track H scope reduced. active-work.md flipped to point at Track J → Track H.

#### Total LOC delta
~140 lines code/comments + 6 commits + 0 tests added (this is debt-paydown, not feature work). 89 apps tests still passing post-J.

#### Exit criteria
- [x] All Track E recovery footprints cleaned up
- [x] Track H Phase 1 (`ansible_env`) pre-paid
- [x] Pytest collection green (0 errors)
- [x] Decisions O12-O16 logged
- [x] Roadmap reflects new J→H→F→G order

---

### Track H — ansible-core 2.20+ tightening + 2.24 readiness **(DONE 2026-05-01)**

**Status: DONE in 7 commits `6767e56..72c021d` on 2026-05-01.** Original Track H targeted ansible-core 2.24 — but 2.24 hasn't shipped yet (latest stable: 2.20.5; latest RC: 2.21.0rc1). Re-scoped (Decision O17) to "robust 2.20+ tightening + future 2.24 readiness". When 2.24 ships, the actual jump is ~4 hours (single requirements.yml floor bump + collection review + blank).

#### Why ordering revised (O16) and re-scoped (O17)
Original O11 placed H at the end targeting ansible-core 2.24. Track J Phase 4 pre-paid the `ansible_env` migration (9 occurrences, not 200-400). On audit 2026-05-01, ansible-core 2.24 turned out **not yet released** by upstream (latest stable: 2.20.5, RC: 2.21.0rc1). Decision O17: re-scope Track H to "robust 2.20+ tightening with verified 2.21 RC forward-compat + ansible-lint production-profile clean". The remaining 2.24 jump becomes a ~4h follow-up when upstream ships.

#### Scope delivered (Phases 1-8)
1. **Phase 1 — `requirements.yml` collection pinning** (commit `6767e56`):
   - Bumped floors + added upper bounds for `community.general`, `community.docker`, `community.mysql`
   - Added missing `ansible.posix` (3 files actually use it; previously implicit)
   - Dropped 3 unused: `community.crypto`, `community.postgresql`, `nextcloud.admin`
   - Reproducible installs across operator + ubuntu-22.04/24.04/macos-14 CI
2. **Phase 2 — `meta/main.yml min_ansible_version`** (commit `9d26b4a`): 60× `2.14` + 4× `2.15` + 1× `2.16` + anomalies → all 66 at `"2.20"`. Plus 3 new meta/main.yml for `pazny.mac.{dock,homebrew,mas}` which were previously bare.
3. **Phase 3 — CI ansible-core pin** (commit `ddd5722`): `pip3 install ansible` (floating) → `ansible-core>=2.20,<2.21` in lint + syntax + integration jobs. Reproducible builds; bump-here-once for next upgrade.
4. **Phase 4 — Custom-module audit + with_* modernization** (commit `d65f8ba`): All 13 Python modules import clean under 2.20 + 2.21rc1, all `AnsibleModule()` use modern argspec, no v1 callback hooks, no `_text` legacy imports. Real finding: `pazny.dotfiles` had 4 `with_items`/`with_indexed_items` (forked from upstream pre-rebrand) → modernized to `loop:` + `loop_control: index_var`.
5. **Phase 5 — 2.21.0rc1 sandbox forward-compat probe** (verification only, no commit): venv install, syntax-check + 89-test pytest suite + custom-module imports — all clean under 2.21 RC.
6. **Phase 6 — ansible-lint production-profile clean** (commit `23d970b`): 30+ findings → 0 fatal/0 warning. Categories: 12× `risky-shell-pipe` (set -o pipefail + bash exec), 5× `command-instead-of-module` (kept tar+curl shell with noqa rationale, modernized git_config), 3× `no-handler` (kept inline with launchctl-ordering rationale), 4× `load-failure[filenotfounderror]` (root-cause fix: replaced `{{ playbook_dir }}/...` with relative paths in 4 includes), plus 5 minor (literal-compare, ignore-errors with rationale, jinja[invalid] defensive default, meta-no-tags 'app-store' → 'appstore', name[casing] noqa for jsOS brand). Final result: ansible-lint 26.4.0 reports `Passed: 0 failure(s), 0 warning(s) ... Last profile that met the validation criteria was 'production'.`
7. **Phase 7 — CLAUDE.md Known Tech Debt refresh** (commit `72c021d`): replaced obsolete "ansible_env needs migration before 2.24" entry with current status + commit chain pointing at J + H phases.
8. **Phase 8 — roadmap + active-work + remember refresh** (this commit): closes Track H, marks it DONE, flips active-work to Track F.

#### Files touched
- `requirements.yml` (Phase 1)
- `roles/pazny.postgresql/meta/main.yml` (drop unused collection dep, Phase 1)
- 69× `roles/pazny.*/meta/main.yml` (66 bumped + 3 new for mac.*, Phase 2)
- `.github/workflows/ci.yml` (3 jobs, Phase 3)
- `roles/pazny.dotfiles/tasks/main.yml` (Phase 4)
- 21 files in roles/ + tasks/ (Phase 6 lint cleanup; see commit `23d970b` for full list)
- `.ansible-lint` (skip_list extension + exclude_paths for molecule scaffold, Phase 6)
- `CLAUDE.md` (Phase 7)

#### Exit criteria — ALL MET
- [x] `ansible-core==2.20.5` runs blank green (operator's last green blank: 2026-04-29 `ok=845 changed=261 failed=0`)
- [x] CI matrix pinned to >=2.20,<2.21 across all jobs
- [x] All 66 `roles/pazny.*` meta/main.yml advertise `min_ansible_version: "2.20"`
- [x] 89 apps tests passing, 431 total tests collecting clean
- [x] `ansible-playbook main.yml --syntax-check` — clean on 2.20.5 AND 2.21.0rc1
- [x] `ansible-lint --offline` — 0 failures / 0 warnings (production profile)
- [x] CLAUDE.md "Known Tech Debt" updated with reality, not aspirational guess

#### Outstanding (deferred until 2.24 ships)
- One-line bump in `requirements.yml` + `.github/workflows/ci.yml` from `>=2.20,<2.21` to `>=2.24,<2.25`
- Floor bump 66× `meta/main.yml` from `"2.20"` to `"2.24"`
- One blank to surface any actual 2.24 changes
- Estimated: ~4 hours when 2.24 stable lands

---

## Cross-cutting concerns

### Testing strategy across tracks
- **Pytest suite** must stay green on every commit (CI gates merges)
- **PHP suite** same — `tests/wing-api/run-all.sh`
- **Smoke suite** for telemetry — `WING_EVENTS_DEBUG=1 + small playbook` after every Bone/Wing change
- **Schema-vs-handler consistency** test (`tests/state_manager/test_schema_handler_consistency.py`) catches drift in migration/upgrade enums vs code
- **Catalog smoke tests** validate every YAML in `migrations/` and `upgrades/` parses cleanly

### Telemetry expansion (deferred from `agent-operable-nos.md`)
- Add to event schema in v2: `trigger.type` (`manual`|`scheduled`|`agent`), `parent_event_id`, `safety_level`, `error_class`
- Track-B agent identity work makes `agent_id` first-class — fold into the same migration

### Documentation debt
- README needs English version + screenshots before NGI proposal submission
- `CONTRIBUTING.md` exists? — verify, write if missing
- LICENSE — confirm Apache 2.0 chosen
- Public roadmap (this file) eventually surfaces in Wing's `/help` view

### Migration safety
- Every blank-breaking change ships with a migration recipe in `migrations/`
- Existing dev.local installs must survive Track A (Bone container) without manual intervention
- Track B's BONE_SECRET deprecation is 90-day soft → hard removal

### Domain flip status
- Wedos NS delegation to Cloudflare = manual, ~5 min, propagation 1–24h
- After Track A lands, the flip is safer (Bone + Wing inside containers don't care about cookie-domain at the host level)
- Operator runbook: `docs/domain-flip-operator-guide.md`

---

## Dependency graph

```
Track A (Bone+Wing containerize)
  ├── Unblocks → Track B (agent identity) — JWT verifier easier in container env
  ├── Unblocks → Track C (Linux port) — no launchd to translate
  └── Independent ← Track D (hardening + GDPR) — parallel, doc-heavy

Track B (agent identity)
  └── Pre-req for → BONE_SECRET deprecation, full audit trail

Track C (Linux infra)
  └── Pre-req for → SMB sales pipeline (Linux is the market)

Track D (ANSSI + GDPR)
  └── Pre-req for → CZ/EU SMB conversations, NGI proposal credibility
```

**Recommended sequence:**
1. Track A first (2 days) — unblocks others
2. **In parallel**: Tracks B (5d), C (7d), D (10d) — different file regions, three operators or three claude sessions can run them simultaneously
3. Integration sprint at end (2 days) — all four merged + final blank + Playwright UI sweep

Total ETA: **~3 weeks of focused work**.

---

## Open decisions

_All Q2 wave-1 decisions (Tracks A–D) were resolved on 2026-04-26.
Q2 wave-2 (Tracks E–H) decisions were resolved on 2026-04-29 — see
Decision log below. The roadmap has explicit ordering, and tracks
have explicit exit criteria, so there's no decision blocking next
session's work. Multi-tenant fleet mode + router-as-architecture were
deferred to **post-roadmap stretch goals** (see Appendix below)._

(none open)

---

## Decision log (already decided + rationale)

| Date | Decision | Rationale |
|---|---|---|
| 2026-04-22 | Stay with Ansible (NOT NixOS rewrite) | Cross-platform abstraction works, NixOS rewrite alienates current users |
| 2026-04-23 | Apache 2.0 license | Business-friendly, SMB-compatible, doesn't block proprietary add-ons |
| 2026-04-23 | "Open source + paid hosting/support" model (NOT open core) | Simpler codebase, no community ill-will from feature-gating |
| 2026-04-24 | Wing telemetry HMAC: bare hex sig over `(ts.body)` | Aligns with Bone's events.py verifier; sort_keys=True canonical body |
| 2026-04-24 | Telemetry pipeline: callback → Bone → wing.db | Auto-drain fallback queue on activation; 503 (not 500) for Wing-DB-not-ready |
| 2026-04-25 | mailpit notify-only by default for Watchtower | Stateful upgrades stay manual via upgrade recipes; Watchtower is early-warning only |
| 2026-04-25 | dnsmasq + /etc/resolver gated on `instance_tld_is_local` + `dnsmasq_force_local_domains` flag | Hybrid mode: real domain identity + local-only reachability |
| 2026-04-25 | Linux primary target: Ubuntu 24.04 LTS ARM64 | Match Apple Silicon dev experience via Lima/Multipass + match SMB reality |
| 2026-04-26 | Containerize Bone + Wing (NOT whole-nOS-in-VM) | Ditches launchd/systemd duplication; preserves Apple Silicon perks |
| 2026-04-26 | Agent identity = Authentik OIDC client_credentials grant | Native Authentik primitive, machine-readable, audit logged |
| 2026-04-26 | Don't move whole nOS into a Linux VM | Loses MLX backend; resource tax; HW passthrough complications |
| 2026-04-26 | **O1**: Bone container = local build (not registry) | Single-host home lab; no GHCR token rotation; simpler. Re-evaluate when CI image-build job lands. |
| 2026-04-26 | **O2**: Wing container = local build (not registry) | Same rationale as O1. Composer install runs inside container via `wing-cli` profile. |
| 2026-04-26 | **O3**: Agent token lifetime = 12 hours | Long enough to survive a workday + overnight cron, short enough to rotate during operator shift. Refresh-token flow handles longer sessions. |
| 2026-04-26 | **O4**: Drop `BONE_SECRET` without deprecation window | Repo isn't yet in third-party hands; full agent SSO integration is the cleaner cut than carrying dual auth for 90 days. Breaking change documented in Track B. |
| 2026-04-26 | **O5**: ANSSI hardening default = ON, opt-out via `install_hardening: false` | Matches French/Danish sovereignty stance; surprise-on-deploy is acceptable for a security-positioned product. |
| 2026-04-26 | **O6**: GDPR Article 30 register = Wing UI (not just markdown) | Markdown alone is too passive for B2B sales conversations. Track D scope grows by ~1 day for the `/gdpr` route. |
| 2026-04-29 | **O7**: Tier-2 default subdomain = `<slug>.apps.<tld>` (NOT direct `<slug>.<tld>`) | Explicit isolation segment prevents Tier-2 slug from colliding with any future Tier-1 vhost; one extra URL segment is acceptable cost. Per-app override via `nginx.subdomain` is intentionally NOT added (more code, more docs, no concrete need today). |
| 2026-04-29 | **O8**: Tier-2 slug stays bound to filename (`^[a-z][a-z0-9-]*$`); no brand-name override | E.g. 2FAuth ships as `apps/twofauth.yml` and serves at `twofauth.apps.<tld>` — operator lives with the textified slug. Brand-friendly URLs are a stretch goal. |
| 2026-04-29 | **O9**: Multi-host fleet mode = composable `host_alias` segment (Track F), NOT per-tenant-on-one-host | Track F adds `host_alias` (e.g. `media`) so FQDN becomes `<svc>.<host_alias>.<tenant_domain>` in multi-host fleet networks. Per-tenant-on-one-host (many TLDs sharing one nOS deploy) is 5× more work and is **deferred to post-roadmap** (see Stretch goals). |
| 2026-04-29 | **O10**: Public exposure (Track G) targets Bluesky PDS + local SMTP server (Stalwart-class), with Mastodon optional | Personal sovereign-identity (bsky) + outbound mail (today's biggest gap, every service log-only) are the clear value adds. Mastodon ships if time permits. |
| 2026-04-29 | **O11**: Roadmap order = E (Tier-2 wet test) → F (dynamic domain) → G (public deploy) → H (ansible-core 2.24) | Wet test before refactor: dynamic-domain design is informed by what Tier-2 actually looks like in production. ansible-core upgrade last so it doesn't derail in-flight work. **SUPERSEDED by O15** (2026-05-01) once the actual `ansible_env` count came in at 9 (not 200-400). |
| 2026-04-30 | **O12**: Tier-2 apps reach infra services via `shared_net`, not a dedicated `infra_net` external mount | The infra stack's network is named `infra_infra_net` (compose project prefix); declaring `external: infra_net` in the apps stack never resolved. Architecture already routes cross-stack via `shared_net` — infra services are dual-attached. Same pattern now applied to mailpit (Track J Phase 2, commit `9708133`) and any future cross-stack service. Surfaced during Track E recovery, fixed in commit `8091c07`. |
| 2026-04-30 | **O13**: Apps stack `--wait-timeout` = 240s default | Cold-start budget for N parallel Tier-2 containers: `start_period (60s) + healthcheck interval × retries (≤150s) + image pull/volume init headroom`. With 4 containers (twofauth + roundcube + documenso + documenso-db) on Apple Silicon, 120s was tight (compose-up returned rc=1 even though all 4 became healthy ~30s later). 240s gives enough margin for 6-8 containers; will need to revisit if Tier-2 catalog grows past ~10 simultaneous deploys. Commit `d4e99f2`. |
| 2026-04-30 | **O14**: Authentik runtime reconverge entry-point = `tasks_from: blueprints.yml` + `meta: flush_handlers` | The role's `tasks_from: post.yml` (renamed to `health.yml` in Track J Phase 3, commit `326a592`) is JUST a readiness probe — calling it for "blueprint reconverge" is a no-op trap that burns recovery cycles. Canonical pattern lives in `roles/pazny.apps_runner/tasks/post.yml` lines ~123-150 (commit `d4e99f2`). |
| 2026-04-30 | **O15**: Section 12 recovery pattern is the canonical Tier-2 fix flow (no full blank required) | `ansible-playbook main.yml -K --tags apps,tier2,apps-runner` re-renders manifests, re-runs image probes, re-deploys apps stack, re-fires post-hooks. Validated 3× in succession during Track E recovery (each commit `8091c07` / `a8fc804` / `d4e99f2` was tested via partial re-run). Documented as Section 12 of `docs/tier2-wet-test-checklist.md`. |
| 2026-05-01 | **O16**: Roadmap order revised to **J → H → F → G** | Track J (tech debt cleanup, ~3-4h) lands first to remove Track-E-recovery debris and false-friend traps. Track H (ansible-core 2.24) shrinks to ~1 day after J Phase 4 lands the `ansible_env` migration (9 occurrences, not 200-400 as originally feared). Track F (instance_tld decomposition) keeps its position before G. Track G (public deploy) keeps its position last so Stalwart SMTP role can build on a clean tree. Total revised Q2-wave-2 ETA: ~7-9 days (was estimated ~3 weeks). |
| 2026-05-01 | **O17**: Track H re-scoped from "ansible-core 2.24 upgrade" to "2.20+ tightening + 2.24 readiness" | ansible-core 2.24 not yet released by upstream (audit 2026-05-01: latest stable 2.20.5, latest RC 2.21.0rc1). Original Track H was forward-looking. Re-scoped to deliver what's possible today: pin current versions across operator + CI, modernize what 2.21 RC flags, run ansible-lint production profile clean. The actual 2.24 jump becomes a ~4h floor-bump follow-up when 2.24 ships. Operator confirmed Variant A. Track H DONE 2026-05-01 in 7 commits `6767e56..72c021d`. |
| 2026-05-01 | **O18**: New post-G arc — Wing modernization + agent platform | Operator-proposed 2026-05-01: a strategic Wing audit + refactor + agent-suite + watchtower-scheduler + pentest-run-loop that turns `~/wing/` from a fragmented filesystem layout into a cohesive Tier-2-app-style project consuming our own infra (Authentik + Bone + Loki + Traefik). Sketched as Tracks K/L/M at the end of this document. **SUPERSEDED by O19** (2026-05-01) — full plan written, scope expanded, Track K/L/M IDs retired. |
| 2026-05-01 | **O19**: bones & wings refactor — full plan written, all 7 architectural decisions resolved | Plan in [`docs/bones-and-wings-refactor.md`](bones-and-wings-refactor.md). Replaces K/L/M. Scope expanded beyond original sketch: (a) **all-local architecture** — Wing PHP-FPM via Homebrew + Bone/Pulse Python via launchd; reverses Track A containerization for the platform-control plane; zero shared volumes/networks within anatomy. (b) **Repo reorg** — `files/anatomy/` umbrella absorbs `migrations/`, `library/`, `module_utils/`, `patches/`, framework-internal `docs/`; top-level repo becomes lean Ansible. (c) **Plugin system** — drop-a-directory auto-wiring (Authentik client + Wing route + Pulse cron + Grafana dashboard + ntfy/mail templates + GDPR row + schema migration). (d) **Conductor as primary agent** (PoC); inspektor/librarian/scout post-PoC, each ~2-4h. (e) **Gitleaks as PoC plugin**, others as separate plugin commits post-PoC. (f) **Per-actor Authentik identity + audit trail** — every wing.db write tagged `(actor_id, action_id, acted_at)`; GDPR Article 30 query is one SELECT. (g) **Wing source as git submodule** at `external/wing/` with `cp+jinja` render pattern. PoC estimate: ~12 days sequential. Pre-impl gate: Tracks F + G DONE. |
| 2026-05-01 | **O20**: Smoke přitvrzení + tester identity (Track G/0 within batch) | Operator-driven pivot to AIT philosophy: **30x/40x/50x sole responses are unacceptable as proof a service works**. Manual click-through tests are too costly + error-prone. Two-step strict path: (a) `nos-smoke.py --strict` tightens default expect to `[200, 204]`; entries declare `auth: tester` to opt into headless flow. (b) Authentik blueprint adds `nos-tester` user (member of all RBAC tier groups) + `nos_tester_password` in credentials. (c) `nos-smoke.py` implements the Authentik flow-executor headless login (urllib + cookiejar, no new deps) — POSTs identification → password stages, follows callback, validates final 200. (d) `tasks/post-smoke.yml` plumbs Ansible vars (`tenant_domain`, `host_alias`, `nos_tester_*`) through CLI flags. **Strict mode is opt-in initially** (default still legacy expect list) so today's blanks stay green; operator flips `nos_smoke_strict_status: true` after Track G phase 3 lands and the auth flow is wet-tested. Foundation also unblocks Track P (Playwright headless browser) — same tester credentials, browser layer instead of urllib. |
| 2026-05-01 | **O21**: Track G batch scope — full scaffold today, wet activation post-domain-switch | All Track G prerequisites scaffolded **before** the operator flips DNS: Stalwart SMTP role (gated `install_smtp_stalwart: false`), Bluesky public-federation flag (gated `bluesky_pds_public_federation: false`), Mastodon flag (`install_mastodon: false`, role TBD), CF ACME role README, comprehensive `docs/operator-domain-switch.md` (wedos NS flip + CF zone setup + DNS records + router port forwarding + Tailscale Funnel alternative + verification). Each toggle defaults OFF and refuses to render on a local TLD (Stalwart fail-fast, ACME meta `end_play`). This batch lands without changing today's blank shape — operator flips toggles ONE BY ONE after the domain-switch checklist is walked. |
| 2026-05-02 | **O22**: bones&wings refactor PoC seed work landed pre-A0 | Honest stock-take with parallel agent flagged that the refactor PLAN is committed (`f4545c1`) but **0 implementation lines exist** — `files/anatomy/` doesn't exist, `hooks/playbook-end.d/` is empty, Wing source still rsync (not submodule), Bone still container (not launchd). Rather than wait for Tracks F+G full activation to start the 12-day PoC, three "first-flight" targets land NOW because they prove contracts the refactor builds on: (a) `hooks/playbook-end.d/20-cve-drift-check.sh` — first live hook; emits `security.drift.snapshot` on stdout + Prometheus textfile (`nos_security_drift.prom`); validates the empty-hooks-dir contract works. (b) `tools/wing-telemetry-smoke.py` — synthesizes fake event, HMAC-signs, POSTs to Bone, verifies wing.db readback + Loki query_range; one-command "is the telemetry pipe healthy?" check that survives the Bone-container-to-launchd cut in §A6. (c) `files/vuln-scan/scan-runner.sh` rewrites `claude -p` dispatch with `lib-jsonl.sh` shared helper that emits `scan.batch_started` / `scan.batch_done` events into wing.db (HMAC-authenticated, hex via openssl, byte-compatible with Python's `hmac.compare_digest`). Plus three new SSO agent identities in the Authentik blueprint (`nos-inspektor` / `nos-librarian` / `nos-scout`) with security-specific scopes (`nos:security:read|write|scan`, `nos:pentest:execute`) — provisioned now so wing.db audit trail tags the right `actor_id` from day one. Bone's `events.py` validator extended with new event types (`scan.*`, `security.drift.*`). Total: ~370 LOC + 4 new files + 3 mods, no blast on Tracks F/G. |

---

## Next-session entry point

**If you're picking up this work fresh, do this:**

1. Read this file (you're doing it).
2. Read [`docs/active-work.md`](active-work.md) — the always-current "what to do right now" pointer; updated more often than this file.
3. `git log --oneline -20` to see what's landed since the snapshot at top.
4. `git status` — uncommitted work might belong to operator's other branch, leave alone unless explicitly asked.
5. Check `~/.nos/state.yml` and the most recent ansible.log for the last blank's `PLAY RECAP` line.
6. Choose your track based on `docs/active-work.md`. Default order today
   (2026-05-03 evening): finish the security-hardening full-blank gate, then
   resume bones & wings at A3.5. For parallel B&W work, use
   `docs/bones-and-wings-bulk-plan.md`.
7. Read the track's "Files to touch" + "Exit criteria" before starting code.
8. Pre-flight: `ansible-playbook main.yml --syntax-check` + `python3 -m pytest tests/apps tests/state_manager -q` should both pass cleanly.
9. Always update the **Decision log** when making a non-trivial choice — future-you will thank you.
10. After meaningful progress, update `docs/active-work.md` so the next session has a fresh entry point.

**Commit message convention:**
- `feat(<area>): one-line summary` for new functionality
- `fix(<area>): one-line summary` for bug fixes
- `docs(<area>): one-line summary` for doc-only changes
- `ci(<area>): one-line summary` for CI changes
- `refactor(<area>): one-line summary` for non-behavior code reshuffling
- Body explains the **why**, not the what (diff shows the what)
- Co-Authored-By is **forbidden** per CLAUDE.md repo policy

---

### bones & wings refactor **(post-G arc, planned 2026-05-01)**

**Replaces former Tracks K / L / M** — the original sketch from O18 (2026-05-01) was expanded into a comprehensive plan during a same-day operator review. **Authoritative document: [`docs/bones-and-wings-refactor.md`](bones-and-wings-refactor.md).** Track K/L/M phase IDs are retired; new phases A0-A10 in §8 of the refactor doc are the current breakdown.

**Headline shape:**
- **Umbrella name:** bones & wings (operator-facing); **`anatomy`** (path/identifier form)
- **Architecture:** **all-local target** — Wing FrankenPHP via launchd + Bone/Pulse Python via launchd. A3a already reverted Bone to host launchd; A3.5 reverts Wing from container/FPM sidecar to FrankenPHP. Wing UI stays served via Traefik file-provider with Authentik forward-auth.
- **Repo reorg:** `files/anatomy/` is the home for platform code: Wing source (path-moved into `files/anatomy/wing/`; no `external/wing` submodule for PoC), Bone, Pulse, skills, plugins, agents, schema artifacts. Moves `migrations/`, `library`, `module_utils`, `patches`, framework-internal `docs` into anatomy. Top-level repo becomes lean Ansible.
- **Plugin system:** drop-a-directory auto-wiring. `files/anatomy/plugins/<name>/plugin.yml` declares Authentik client, Wing route/view, Pulse cron job, Grafana dashboard, ntfy/mail templates, GDPR row, schema migration. `ansible-playbook --tags anatomy.plugins` wires all of it.
- **Primary agent:** **conductor** (PoC). Runs `ansible-playbook --check` every 4h; reports drift via Wing `/inbox`; on operator approval applies upgrades/migrations. Other profiles (inspektor, librarian, scout) post-PoC, each ~2-4h work.
- **PoC plugin:** **gitleaks**. Other FOSS cybersec tools (trivy/grype/syft/nuclei/lynis/testssl/osquery) ship as separate plugin commits once the gitleaks pattern is operator-validated.
- **Audit trail:** every wing.db write tagged `(actor_id, action_id, acted_at)`. GDPR Article 30 forensic query is one SELECT.
- **Notification fanout:** Wing `/inbox` primary; ntfy for push (severity ≥ high); mail (Stalwart from Track G) for critical; everything observable in Grafana.

**PoC estimate: ~14-16 days sequential** from original start; A0-A4+A6 foundation has landed. Remaining implementation centers on A3.5, A5, A6.5, A7-A10. Post-PoC expansion is incremental, ~2-4h per added plugin or profile.

**Current gate:** security-hardening full blank + wet test must pass before the next B&W slice, unless the operator explicitly waives it. After that: A3.5 → A5/A6.5 → A7/A8 → A9/A10.

**Read the full plan in [`docs/bones-and-wings-refactor.md`](bones-and-wings-refactor.md) before any code-touch.** It has ~1100 lines of architecture, edge-case catalog, and phase-by-phase exit criteria; this stub is just the index card.

---

### Track Q — Autowiring debt consolidation **(post-PoC, first-class follow-on, 2026-05-03 elevated)**

**Status: blocked on bones&wings PoC A6.5 (Grafana thin-role pilot) — doctrine proof point.** 7 batches × 3-5 days each = 4-6 weeks total. Plan in `docs/bones-and-wings-refactor.md` §13.1.

**Doctrine** (refactor doc §1.1, "tendons & vessels"): every Tier-1 role post-Track-Q is install-only (defaults + main.yml + compose template + meta). All wiring lives in service + composition plugins under `files/anatomy/plugins/`. Net LOC delta projected: **-2000 to -3500** across ~50 distinct integrations.

**Audit 2026-05-03** of all 71 `pazny.*` roles found **30 with `tasks/post.yml` (= wiring leak indicator)**, top-10 by LOC: `pazny.apps_runner` 412 (framework, exempt), `pazny.wing` 291, `pazny.portainer` 272, `pazny.postgresql` 236, `pazny.erpnext` 205, `pazny.paperclip` 165, `pazny.mcp_gateway` 165, `pazny.jellyfin` 152, `pazny.freescout` 152, `pazny.nextcloud` 139.

**Q1 — Observability (5 roles, ~700 LOC, start point):** grafana (A6.5 reference), prometheus, loki, tempo, alloy.
**Q2 — IAM + secrets (3 roles, ~942 LOC, biggest blast):** authentik (V4 source-plugin pattern), infisical, vaultwarden. `authentik_oidc_apps` central list (40 entries) disappears.
**Q3 — Storage + DB:** mariadb, postgresql, redis, rustfs.
**Q4 — Comms:** smtp_stalwart, ntfy, mailpit.
**Q5 — Content (largest, 9 roles, ~1300 LOC):** nextcloud, outline, bookstack, hedgedoc, wordpress, calibre_web, kiwix, jellyfin, puter.
**Q6 — Dev/CI:** gitea, gitlab, woodpecker, code_server, paperclip.
**Q7 — Misc + sweep (16 roles):** uptime_kuma, homeassistant, n8n, nodered, miniflux, openwebui, firefly, erpnext, freescout, metabase, superset, qgis_server, freepbx, onlyoffice, spacetimedb, mcp_gateway.

**Per-batch deterministic 6-step recipe:** `files/anatomy/docs/role-thinning-recipe.md`.

**Out of Q (special-cased):** `pazny.bone` ✅ thin (A3a), `pazny.wing` ⏳ A3.5, `pazny.pulse` ✅ born thin (A4), `pazny.traefik` (source plugin candidate), `pazny.acme` (already thin), `pazny.bluesky_pds` (federation flag refactor), `pazny.watchtower` (image bump 2026-05-03 P0), `pazny.openclaw/opencode/hermes/iiab_terminal` (non-Docker host pattern), `pazny.mac.*/linux.*/dotfiles/state_manager/backup` (host infra).

**Exit criteria:** every `roles/pazny.<service>/` post-Q has shape `defaults + tasks/main.yml + templates/compose.yml.j2 + meta`. No `tasks/post.yml` unless install-internal. `default.config.yml` has zero per-service OIDC blocks.

---

### Track R — Anatomy structure grooming + role namespace cleanup **(pre-Q / alongside A6.5, proposed 2026-05-03)**

**Status: proposed.** Short structural cleanup before mass Track Q thinning. Goal: make the anatomy boundary explicit in both filesystem and Ansible naming, so future Tendons&Vessels work does not keep adding new `pazny.*` debt.

**Target shape:**
- **Anatomy control-plane roles:** rename `pazny.bone`, `pazny.wing`, `pazny.pulse`, and optional future `pazny.anatomy` to collection-style names under `n_os.anatomy.*`.
- **Service installer roles:** stay `pazny.<service>` until Track Q thins them; they are not anatomy roles, they are bones that plugins wire.
- **Tendons&Vessels:** `files/anatomy/plugins/<service>-base/` remains the config+wiring home. Role namespace cleanup must not move plugin manifests into roles.
- **Compatibility:** keep aliases/wrappers for one release window so existing playbooks using `pazny.*` do not break abruptly.

**R1 — Namespace decision + alias map (0.5 d):**
- Decide exact physical layout: either `roles/n_os.anatomy.<organ>/` as repo-local role dirs, or a real Ansible collection under `collections/ansible_collections/n_os/anatomy/roles/<organ>/`.
- Write a mapping table: `pazny.bone → n_os.anatomy.bone`, `pazny.wing → n_os.anatomy.wing`, `pazny.pulse → n_os.anatomy.pulse`, `pazny.anatomy → n_os.anatomy.platform`.
- Define compatibility policy and deprecation warnings.

**R2 — Move only anatomy-control roles (1-2 d):**
- Rename/move role directories, update `main.yml`, `tasks/stacks/*`, docs, tests, and role READMEs.
- Preserve runtime names (`eu.thisisait.nos.{wing,bone,pulse}`), vars (`wing_*`, `bone_*`, `pulse_*`), API paths, and filesystem paths (`files/anatomy/*`).
- Add thin wrapper aliases if Ansible layout permits; otherwise document a hard-cut migration.

**R3 — Tendons&Vessels contract cleanup (1 d):**
- Update plugin schema/docs to allow `requires.role: n_os.anatomy.<organ>` and service roles such as `pazny.grafana`.
- Update draft plugins (`grafana-base`) and recipes to distinguish **role being wired** from **anatomy role namespace**.
- Add a short `docs/anatomy.md` naming section explaining organs, roles, plugins, tendons, vessels, synapses.

**R4 — Q-readiness sweep (0.5-1 d):**
- Grep stale anatomy paths and role names.
- Update `docs/bones-and-wings-refactor.md`, `files/anatomy/README.md`, `CLAUDE.md`, and `docs/bones-and-wings-bulk-plan.md`.
- Exit with a green syntax check and anatomy tests.

**Exit criteria:** all anatomy-control-plane references use `n_os.anatomy.*`; service roles remain `pazny.<service>` until individually thinned by Track Q; plugin manifests remain the only home for config+wiring; old `pazny.{bone,wing,pulse}` usage is either wrapper-compatible or explicitly documented as migrated.

---

### Track P — Automated wet-test (Playwright + Cowork) **(post-H stretch)**

**Status: scaffolding seeded in Track E batch (commit chain `c7b5a4e..`).** File skeletons landed:
- `docs/wet-test-automation.md` — architecture, Cowork session protocol, file layout, activation steps
- `tests/e2e/tier2-wet-test.spec.ts` — Playwright skeleton mapping checklist sections 2/3/4/5/8/11 to `describe`/`test` blocks; every test currently calls `test.fixme()` so a `npx playwright test` reports "skipped" until Track P proper

**Why this matters:** walking `docs/tier2-wet-test-checklist.md` by hand is tractable for 3-5 pilots but won't scale once the Tier-2 catalog reaches 10+. Operator's vision: a Cowork session driven Playwright suite that walks the 12 sections autonomously, files `fix(apps):` commits for low-risk failures (image tag bumps, healthcheck timing), and surfaces Cowork questions for anything that needs human judgment.

**Activation (post-H):** `cd tests/e2e && npm ci && npx playwright install chromium`, then a Cowork session runs `npx playwright test --reporter=json` after each blank and acts on the JSON.

**Exit criteria:** all 12 checklist sections have a corresponding Playwright test; Cowork session can drive a full wet-test from "blank just finished" to "all green, branch ready for review" hands-free; documented Cowork prompt template at `docs/cowork-wet-test-prompt.md`; operator confirms a successful end-to-end Cowork-driven wet test in the Decision log.

---

## Appendix: stretch goals (post-Q2 / next-roadmap)

These are valid ideas that don't fit current Q2 wave-2 (Tracks E-H):

- **Eye organ** (CVE feed integration) — referenced in `agent-operable-nos.md`, holds for Q3
- **Spine organ** (services.yml as single source of truth) — partial entry point already in Track D's `state/gdpr-classes.yml`
- **Hand organ** (capability-token executor) — overlaps with Track B's RBAC, fold in there
- **EUDIW integration** — Q3 2026 EU calls; build the Authentik blueprint when the call opens
- **Multi-tenant fleet mode (per-tenant-on-one-host)** — operator's brainstorm 2026-04-29: many TLDs sharing one nOS deploy. **NOT** the same as multi-host fleet mode (Track F's `host_alias` covers that). Per-tenant-on-one-host is ~5× more work — Authentik tenants, Wing /hub multi-tenant view, per-tenant secret namespaces, per-tenant data segregation. Needed when nOS hits 10+ paid clients sharing infra. Postponed.
- **Router-as-architecture** — operator's brainstorm 2026-04-29: every nOS host MUST sit behind a tenant-controlled router (e.g. OpenWrt / pfSense / Mikrotik) which handles cross-host LAN, DNS for the `<host_alias>` namespace, optional WireGuard hub for the tenant network, and split-horizon DNS (split between LAN view and CF-proxied public view). Could solve substantial cross-host comms without code on the nOS side. Worth a 1-day spike when fleet mode lands.
- **Brand-friendly Tier-2 URLs** — per-app `nginx.subdomain` override so 2FAuth lands at `2fa.apps.<tld>` instead of `twofauth.apps.<tld>`. Trivial code, deferred only because no concrete need today (O7 / O8).
- **La Suite Calc** — early prototype, watch upstream maturity, integrate when stable
- **Ansible runner on Raspberry Pi controlling Mac inventory** — operator's brainstorm 2026-04-29: physically separate the playbook driver from the deploy host. Probably falls out naturally once Track F's fleet model is in place; document in fleet runbook when written.
