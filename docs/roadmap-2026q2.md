# nOS Multi-Session Roadmap — Q2 2026

> **This document is the entry point for any session that picks up nOS work.**
> Read sections "Where we are today" + "Open decisions" first. Then go to
> the active track. Each track has its own commit conventions and exit
> criteria so progress survives context resets.
>
> Last updated: 2026-04-26 • commit: `3783ffa` • by: pazny

## Mission (in 3 sentences)

nOS is an Ansible-managed self-hosted server suite that lets a 5–30
person organization replace SaaS office/identity/comms/CI with ~50 FOSS
services on a single host (Apple Silicon Mac today, Ubuntu LTS in
progress). Every service is wired into central Authentik SSO with
auto-OIDC; telemetry events flow through a Bone FastAPI dispatcher into
Wing's read model. The product we sell is **operational excellence
around the FOSS core** — setup, retainer, monitoring, hotfix priority —
not feature-flagged enterprise tiers.

## Where we are today (2026-04-26)

### Verified working
- **macOS Apple Silicon** primary target — `ansible-playbook main.yml -K -e blank=true` produces 0 failed, ok=811 (last clean run)
- **60+ services** deployed across 8 Docker stacks (`infra`, `observability`, `iiab`, `devops`, `b2b`, `voip`, `engineering`, `data`)
- **Authentik SSO** with auto-OIDC for ~30 apps, RBAC tier 1–4 mapping
- **State framework** (state.yml + migrations + upgrades + coexistence) with JSON Schema validation
- **Wing telemetry pipeline** — 1949 events/blank, fallback queue empty, end-to-end tested
- **Watchtower** (notify-only) — Docker image drift surfaces in Mailpit
- **Mailpit** dev SMTP sink — 12 services relay through it
- **ACME / Let's Encrypt** wildcard cert via Cloudflare DNS-01 (role ready, awaiting CF zone delegation)
- **CI**: lint + syntax-check matrix (ubuntu-22.04, ubuntu-24.04, macos-14) + pytest job
- **Tests**: 355 Python passing, 71 PHP passing
- **GitHub Code Scanning**: 4 alerts fixed, 6 documented as false positive, 1 won't-fix (see `docs/security-triage.md`)

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

## Open decisions (need operator answer)

### O1. Bone container image — official registry?
Push to `ghcr.io/thisisait/bone:<tag>` or build locally on every host?
- Registry: faster `docker compose up`, but requires GitHub Container Registry setup + token rotation
- Local build: every host re-builds from `files/bone/Dockerfile` on each blank
- **Default proposal:** local build for v1, registry for v2 once we have CI image-build job

### O2. Wing container image — same question
Same trade-off. Wing builds Composer install + asset pipeline. Local build is slower but simpler.

### O3. Agent token lifetime
15 min default proposed. Trade-off:
- Short: better security, agent must refresh frequently
- Long (hours): less Authentik load, easier offline operation
- **Default proposal:** 15 min for write capability, 1 hour for read-only

### O4. BONE_SECRET deprecation window
90 days proposed. Should we make it shorter (30d) or longer (180d)?
- Shorter = forces migration but breaks unmanaged scripts
- Longer = compatibility but legacy secret persists
- **Default proposal:** 90 days, with monthly reminder events emitted to wing.db

### O5. ANSSI hardening default
- Linux-only opt-in (`install_hardening: false`)? — current proposal
- Linux-only opt-out (default true on Ubuntu)? — more secure, may surprise operators
- **Default proposal:** opt-in for v1, evaluate flipping after 6 months of feedback

### O6. GDPR DPA register format
- Markdown file in repo? — easy, but requires regeneration
- Wing `/gdpr` UI? — requires Wing changes (Track D scope creep)
- **Default proposal:** Markdown for v1, Wing UI later

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

---

## Next-session entry point

**If you're picking up this work fresh, do this:**

1. Read this file (you're doing it).
2. `git log --oneline -20` to see what's landed since the snapshot at top.
3. `git status` — uncommitted work might belong to operator's other branch, leave alone unless explicitly asked.
4. Check `~/.nos/state.yml` and `wing.db.events` count to verify the box is still in working order.
5. Choose your track:
   - Track A if Bone + Wing are still launchd-bound — that's the bottleneck.
   - Track B if Track A is done and operator wants agent identity.
   - Track C if Linux is the priority for sales push.
   - Track D if a customer conversation is imminent (compliance is the ask).
6. Read the track's "Files to touch" + "Exit criteria" before starting code.
7. Pre-flight: `ansible-playbook main.yml --syntax-check` + `python3 -m pytest tests/ -q` should both pass cleanly.
8. Always update the **Decision log** when making a non-trivial choice — future-you will thank you.

**Commit message convention:**
- `feat(<area>): one-line summary` for new functionality
- `fix(<area>): one-line summary` for bug fixes
- `docs(<area>): one-line summary` for doc-only changes
- `ci(<area>): one-line summary` for CI changes
- `refactor(<area>): one-line summary` for non-behavior code reshuffling
- Body explains the **why**, not the what (diff shows the what)
- Co-Authored-By is **forbidden** per CLAUDE.md repo policy

---

## Appendix: stretch goals (post-Q2)

These are valid ideas that don't fit Q2:

- **Eye organ** (CVE feed integration) — referenced in `agent-operable-nos.md`, holds for Q3
- **Spine organ** (services.yml as single source of truth) — partial entry point already in Track D's `state/gdpr-classes.yml`
- **Hand organ** (capability-token executor) — overlaps with Track B's RBAC, fold in there
- **EUDIW integration** — Q3 2026 EU calls; build the Authentik blueprint when the call opens
- **Multi-tenant fleet mode** — central Bone aggregating state from many hosts; needed when nOS hits 10+ paid clients
- **La Suite Calc** — early prototype, watch upstream maturity, integrate when stable
