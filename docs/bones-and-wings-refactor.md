# bones & wings — refactor master plan

> **Status:** PROPOSED 2026-05-01 (architecture decisions resolved with operator on the same day; PoC scope confirmed). **NO code commits before Track G ships.** Replaces and supersedes the K/L/M sketch in `docs/roadmap-2026q2.md` (lines 745-812). The roadmap section will be re-pointed at this document.
>
> **Out of scope until in scope:** this plan does **not** start until Tracks F (instance_tld) and G (CF + Stalwart + bsky exposure) are DONE. Estimated start: 2026-05-22…2026-05-29. **PoC estimate: ~12 days of focused work** (single agent, sequential). Post-PoC expansion (additional plugins, additional agent profiles) is incremental.
>
> **Reading order:** sections 1-3 are vision and current-state. Section 4 introduces the **anatomy reorg** (a major repo-level structural change). Section 5 is the **all-local architecture**. Section 6 is the **plugin system** — the core extension surface. Section 7 covers agent profiles with **conductor as primary**. Section 8 is the **PoC phase plan**. Sections 9-13 cover edge cases, notifications, audit, decisions, and out-of-scope.

---

## 1. Vision

The non-Docker zoo of Wing + Bone + ad-hoc shell scripts becomes a **single coherent platform** called **bones & wings**, with these properties:

- **One namespace, one home.** All bones-and-wings source, configuration, schemas, and plugins live under `files/anatomy/`. The repo's top level becomes a clean Ansible playbook surface; everything platform-internal is collapsed into the `anatomy/` tree.
- **Local-first, zero-trust.** Wing, Bone, and Pulse run as **local processes** on the macOS host (PHP-FPM via Homebrew + Python via launchd), not as containers. No shared Docker volumes between subsystems. No shared Docker networks within anatomy. Every subsystem has its own filesystem and its own data; cross-subsystem communication is HTTP+JWT (or HMAC for the legacy callback path).
- **Wing UI fronted by Traefik.** Even though Wing-PHP runs on the host, the public surface is `wing.<tld>` via Traefik file-provider with Authentik forward-auth — same as every other Tier-1 service. The user doesn't notice Wing isn't a container.
- **Plugin system as the extension surface.** Any new capability — security tool, scheduled job, UI view, agent profile — lands as a **plugin** under `files/anatomy/plugins/<name>/` with a manifest. Wing's plugin loader auto-wires Authentik client + UI route + Pulse cron job + Grafana dashboard + ntfy/mail templates + GDPR row. Drop a plugin directory, run `ansible-playbook --tags anatomy.plugins`, capability is live.
- **Pulse is the heartbeat.** A local launchd daemon (`nos-pulse`) runs both **agentic** (claude-SDK invocations) and **non-agentic** (cron-style scripts) scheduled work. Pulse calls Wing/Bone APIs over loopback — no privileged access, no Docker socket mount, no container indirection.
- **Conductor is the key agent.** The first agent that ships is `conductor` — it runs `ansible-playbook --check` on schedule, reports drift via Wing, and on operator-approval applies upgrades and migrations. Other profiles (inspektor, librarian, scout) are post-PoC additions, each ~2-4h of work.
- **Per-agent identity.** Every agent and every plugin gets its own Authentik OIDC client. Every write to wing.db is tagged with the actor identity and time. The audit trail satisfies GDPR Article 30 forensic queries — "who/what/when accessed/modified which personal datum" is a single SQL query.

The point of the refactor is not feature parity in a prettier wrapper. The point is to **make adding a new capability a 1-day plugin commit instead of a 1-week cross-codebase trek through three half-documented surfaces**.

---

## 1.1 Doctrine — "tendons & vessels": thin roles + modular wiring

**Operator framing 2026-05-03:** *"Součásti Bones & Wings budou šlachy a cévy které budou zajišťovat autowiring systémů mezi sebou. Chceme do budoucna mít co nejtenší installer služby a k tomu poskytovat config a wiring — vše modulárně — ne jedna obrovská role."*

Translated to architecture:

- A **role** is just a **bone** — the skeletal install of a service. It does *one* thing: bring up the binary/container, render a minimal config, expose a port. No cross-service knowledge. No OIDC blueprints. No Grafana dashboards. No DB seeding for *other* roles. No notification templates. No GDPR rows. No Prometheus scrape config.
- A **plugin manifest** is a **tendon or vessel** — the connective tissue. **Tendons** wire roles to anatomy (Wing UI, Pulse jobs, audit, GDPR). **Vessels** wire roles to infra/observability (DB tables, Prometheus scrape, Loki labels, Grafana dashboards, Tempo OTLP, ntfy/mail templates, OIDC clients). Drop a manifest, run one tag, the service joins the body.
- **Composition plugins** are **synapses** — they fire only when two or more services are both alive (e.g., grafana-spacetimedb dashboard activates when both grafana AND spacetimedb are installed). Without a synapse plugin, the two services exist in the same body but don't talk; with it, they cooperate. **Same install state, different cooperation surface.**

### Today's anatomy (the lesson learned)

`roles/pazny.grafana/` today carries: dashboards, OIDC config, Prometheus datasource, Loki datasource, Tempo datasource, alert rules, schema for grafana.db, notifier wiring, mailpit relay. Roughly **70% of the role is wiring, not install.** Same shape across Authentik (~70% wiring), Bluesky PDS (~60%), Outline (~75%). The wiring is **glued into the role** because we lacked a place to put it.

### The doctrine — what every role must shed

After Track Q completes, a Tier-1 role like `roles/pazny.grafana/` should contain ONLY:

```
roles/pazny.grafana/
├── defaults/main.yml         # version, port, data_dir, mem_limit
├── tasks/main.yml            # data dir + render compose-override
├── templates/compose.yml.j2  # Docker Compose service fragment, no top-level networks:
└── meta/main.yml
```

That's it. **No `tasks/post.yml`. No dashboards/. No OIDC blocks in `default.config.yml`. No Prometheus scrape entry in `roles/pazny.alloy/`.** Everything that connects Grafana to the rest of the body lives in `files/anatomy/plugins/grafana-base/plugin.yml` (a service plugin) and in zero or more composition plugins (`files/anatomy/plugins/grafana-spacetimedb/`, `files/anatomy/plugins/grafana-bluesky-feed/`, etc.).

**A role's only public surface, post-Track-Q, is its name + its `defaults/`.** Plugins read defaults to know where to write/scrape/connect. Plugins do not modify the role.

### Implications for adding a new service

**Today (pre-Track-Q):** add `roles/pazny.foo/`, then edit `default.config.yml` (OIDC entry), `roles/pazny.alloy/templates/scrape-config.yml.j2` (scrape), `tasks/stacks/core-up.yml` (DB), `roles/pazny.foo/tasks/post.yml` (auth wiring), `templates/traefik/dynamic/services.yml.j2` (router), maybe `roles/pazny.grafana/files/dashboards/` (dashboard). **Six files, three subsystems, no atomic commit.**

**After Track Q:** add `roles/pazny.foo/` (4 files, ~50 lines, just install) + `files/anatomy/plugins/foo-base/plugin.yml` (1 file, all wiring). **Two files. Atomic. Reversible. Testable in isolation.**

### Implications for the PoC

This doctrine elevates Track Q from **"post-PoC follow-on, scope TBD"** (§13.1's old framing) to **a first-class architectural promise of the refactor itself**. The PoC must therefore:

1. Build the plugin loader so it can validate AND apply **all three plugin types** (skill / service / composition), even if PoC only ships one of each. Forward-compat schema is no longer enough — loader code paths must exist.
2. Migrate ONE Tier-1 service to the thin-role pattern as a **proof point** (proposed: `pazny.grafana` because its wiring is dense and self-contained — no cross-tenant complexity). This becomes the **canonical reference** for every subsequent migration.
3. Document the migration recipe in `files/anatomy/docs/role-thinning-recipe.md` so future migrations follow a deterministic 6-step process.

The new PoC exit criterion: **a fresh blank with `pazny.grafana` migrated to thin-role + grafana-base plugin produces a byte-identical functional Grafana** — same dashboards, same datasources, same OIDC, same scrape, same alerts. Zero operator-visible regression. **If we can't prove this on Grafana, the doctrine isn't real.**

Track Q (the rest of the migration: Authentik, Outline, Bluesky PDS, ~50 more integrations) stays multi-week post-PoC, but with the recipe + reference migration in hand, each subsequent role is a 2-4h commit, not a "scope TBD" hand-wave.

See §8 (revised PoC plan) for the new phase A6.5 — Grafana thin-role pilot. See §13 (revised) for Track Q with concrete first batch.

---

## 2. Why now

Three forces converge:

1. **Tracks E + J + H landed.** Tier-2 apps_runner is solid, the framework is clean, ansible-core surface is hardened. We're standing on a stable base for the first time since branch start. Refactor risk is at a local minimum.
2. **The pentest-task.md prompt is fully written but has no runner.** Every day it stays unscheduled is a day of CVE drift on 19 components. The refactor enables the runner.
3. **Wing's PHP source is rsync'd from outside the repo today.** Every month we delay confronting that lock-in, drift between environments grows. The refactor binds Wing source as a git submodule and renders configs via jinja during `pazny.anatomy` install — explicit, versioned, reproducible.

**Pre-implementation gates** (operator must clear before phase A0 code-touch):
- Track F DONE + blank-test green
- Track G DONE + bsky/SMTP wet-tested (Stalwart needed for mail notifications)
- This document accepted by operator (sections 4, 5, 8 specifically)

---

## 3. Current state — one-pager

What exists, what doesn't, what's the lock-in. Drawn from a 2026-05-01 audit.

### 3.1 What exists

**Wing** (Tier-1, `iiab` stack, since Track A 2026-04-26)
- Nette 8.3 PHP-FPM container + nginx sidecar
- Source tree: `files/project-wing/` — **fully in repo** (106 tracked files: Dockerfile, NEON configs, app/, bin/, www/, tests/, composer.json). Build artifacts (`vendor/`, `temp/`, `log/`, runtime `data/wing.db*`) are gitignored. *Note 2026-05-03: earlier draft of this doc claimed app/src/www/bin were rsync'd from outside the repo — that was incorrect. Source IS committed; A2 reduces to a path-move into `files/anatomy/wing/`, no git submodule needed.*
- DI services: 14 repositories registered (Component, ScanState, Remediation, Token, Pentest, Advisory, Patch, System, Event, Migration, Upgrade, Coexistence, Gdpr, BoneClient)
- DB: SQLite at `~/wing/app/data/wing.db`; bootstrapped by `bin/init-db.php`, migrated by `bin/migrate-systems.php`
- ~25 REST endpoints under `/api/v1/`, Bearer-token authenticated
- **No OpenAPI spec committed.** API surface defined only in PHP controllers (which ARE in repo per the correction above; spec generation is A5 phase work).

**Bone** (Tier-1, `infra` stack, since Track A 2026-04-26)
- FastAPI 0.115 + Uvicorn, Python 3.13
- Source tree: `files/bone/{main,auth,events,state,migrations,upgrades,coexistence,patches}.py` + Dockerfile (all committed)
- HMAC ingestion at `POST /api/v1/events`; JWT-scoped operational endpoints (`/api/run-tag`, `/api/state`, `/api/migrations`, `/api/upgrades`, `/api/coexistence`, `/api/patches`)
- Cross-mount writes events directly into wing.db (anti-pattern under zero-trust; this refactor removes the cross-mount).

**Telemetry callback** (`callback_plugins/wing_telemetry.py`)
- Fires on every Ansible task; batched HTTP POST to Bone with HMAC
- Lifecycle hook system: `playbook_start`/`playbook_end` events appended to `~/.nos/events/playbook.jsonl`; executes any executable in `hooks/playbook-end.d/` with event JSON on stdin
- **This is the existing trigger surface that nos-pulse adopts directly.**

**Inspektor task spec** (`docs/llm/security/pentest-task.md`)
- 427-line drop-in Claude task prompt; not a sketch
- Phases 1+2+2b+3 fully specified; all persistence via Wing API; workspace at `~/wing/repos/` and `~/wing/patches/`

### 3.2 What does not exist

- **OpenAPI spec for Wing.** Has to be generated. Operator's "symlink" expectation collapses to a committed file in `skills/contracts/`.
- **OpenAPI spec for Bone.** FastAPI auto-generates `/openapi.json` at runtime; the artifact isn't committed.
- **DB DDL export.** Wing's schema is implicit in `bin/init-db.php` + repository class definitions. No committed `db-schema.sql`.
- **Scheduler.** No cron, no launchd timer, no in-app scheduler.
- **Plugin system.** Does not exist. Every "skill" today is reimplemented inline in agent prompts.
- **Per-agent Authentik identities for the agent profiles.** Track B framework is there; instances aren't.
- **Approval workflow in Wing UI.** Pending plans / upgrade drafts / patch drafts have no inbox view.

### 3.3 Lock-in / brittle surfaces (resolved by this refactor)

- ~~**Wing PHP source not in repo**~~ → **CORRECTED 2026-05-03**: Wing PHP source IS committed at `files/project-wing/` (106 files). The original doc draft was wrong about this. A2 phase rescoped from "git submodule under `external/wing/`" to "path-move into `files/anatomy/wing/`" — symmetric to A1.
- **Bone bundles ansible-core 2.18-2.20 inside container** → resolved: Bone moves to host launchd daemon, uses operator's ansible-core 2.20.5 directly.
- **wing.db cross-mount-written by Wing+Bone** → resolved: only Wing process writes; Bone POSTs events to Wing via existing HMAC channel, no shared mount.
- **Bone callback HMAC secret rotates only on `blank=true`** → resolved: `migrations/2026-XX-rotate-bone-hmac.yml` recipe; rotation hook in conductor.
- **`hooks/playbook-end.d/` exists but empty** → resolved: pulse becomes the first consumer (its own daemon also sees the JSONL fallback; no runtime dependency on the hooks dir, but the hook is still respected for orthogonal scripts).

---

## 4. Naming, topology, anatomy reorg

### 4.1 The umbrella

**bones & wings** is the operator-facing product name. In paths and identifiers: **`anatomy`** (singular, no conjunction). The Ansible role that installs the platform is `pazny.anatomy`. Sub-tasks instantiate Wing, Bone, Pulse.

Concrete names by surface:

| Surface | Name |
|---|---|
| Product (operator-facing) | bones & wings |
| Source tree (in repo) | `files/anatomy/` |
| Ansible role(s) | `roles/pazny.{wing,bone,pulse,backup}/` (thin) + `roles/pazny.anatomy/` (parent-orchestrator-optional) |
| Top-level config flag | `install_anatomy: true` (default) |
| Wing UI host | `wing.<tld>` (unchanged) |
| Bone API loopback | `127.0.0.1:8099` (host port; was container) |
| Pulse internal API loopback | `127.0.0.1:8090` (host port, NEW) |
| Wing PHP-FPM | `127.0.0.1:9000` (host port; was container) |
| launchd labels | `eu.thisisait.nos.{wing,bone,pulse}` |

### 4.2 The repo reorg

**Goal:** every bones-and-wings file lives under `files/anatomy/`. Top-level repo becomes lean Ansible.

**Target structure** (after the reorg lands):

```
nOS/
├── apps/                       # Tier-2 manifests (unchanged)
├── default.config.yml
├── default.credentials.yml
├── main.yml                    # playbook entry (unchanged)
├── requirements.yml
├── roles/                      # Ansible roles, namespace pazny.* (unchanged)
│   ├── pazny.wing/             # thin role: PHP-FPM install, render config, launchd plist
│   ├── pazny.bone/             # thin role: Python venv, copy code, launchd plist
│   ├── pazny.pulse/            # NEW thin role: same shape
│   ├── pazny.backup/           # thin role
│   ├── pazny.anatomy/          # OPTIONAL parent: import_role to wing+bone+pulse+backup
│   └── pazny.<service>/...     # all other Tier-1 deployments
├── tasks/                      # playbook tasks (unchanged)
├── templates/                  # playbook-level templates (unchanged)
├── tests/                      # platform pytest (unchanged)
├── state/
│   └── manifest.yml            # service catalog — STAYS top-level (referenced platform-wide)
├── callback_plugins/           # Ansible callback plugins (Ansible convention)
│   └── wing_telemetry.py
├── external/
│   └── wing/                   # NEW git submodule — Wing PHP source
└── files/
    └── anatomy/                # NEW — all bones-and-wings code, configs, schemas
        ├── wing/               # rendered configs, jinja templates for Wing self-update
        │   ├── config/         # NEON files, rendered into ~/wing/app/config/
        │   ├── bin/            # CLI scripts: export-openapi.php, export-schema.php
        │   └── README.md
        ├── bone/               # FastAPI source (was files/bone/, now here)
        │   ├── main.py, auth.py, events.py, state.py, ...
        │   ├── pyproject.toml
        │   └── tests/
        ├── pulse/              # NEW — Pulse Python source
        │   ├── pulse/          # daemon module
        │   ├── runners/        # claude-spawn wrapper, non-agentic job exec
        │   ├── pyproject.toml
        │   └── tests/
        ├── skills/             # reusable capabilities (one dir per skill)
        │   ├── contracts/
        │   │   ├── wing.openapi.yml
        │   │   ├── bone.openapi.yml
        │   │   └── wing.db-schema.sql
        │   ├── api-call/
        │   ├── fetch-cve/
        │   ├── repo-clone/
        │   ├── patch-format/
        │   ├── log-tail/
        │   └── run-tag/
        ├── plugins/            # plugin manifests (gitleaks first, others incremental)
        │   └── gitleaks/
        │       ├── plugin.yml
        │       ├── skills/run-gitleaks.sh
        │       ├── views/GitleaksFindings.latte
        │       ├── dashboards/gitleaks.json
        │       ├── notifications/{mail,ntfy}-template.txt
        │       └── tests/
        ├── agents/             # agent profile YAMLs + system prompts
        │   ├── conductor/
        │   │   ├── profile.yml
        │   │   └── prompt.md
        │   ├── inspektor/      # post-PoC
        │   │   ├── profile.yml
        │   │   └── prompt.md   # symlink/copy of docs/llm/security/pentest-task.md
        │   ├── librarian/      # post-PoC
        │   └── scout/          # post-PoC
        ├── migrations/         # MOVED from /migrations/
        ├── upgrades/           # MOVED from /upgrades/
        ├── patches/            # MOVED from /patches/ (inspektor outputs)
        ├── library/            # MOVED from /library/ (custom Ansible modules)
        ├── module_utils/       # MOVED from /module_utils/
        └── docs/               # bones-and-wings-specific docs
            ├── framework-overview.md  # MOVED from /docs/
            ├── framework-plan.md      # MOVED
            ├── migration-authoring.md # MOVED
            ├── upgrade-recipes.md     # MOVED
            ├── coexistence-playbook.md# MOVED
            └── wing-integration.md    # MOVED
```

**`ansible.cfg` updates** (mechanical):
```ini
[defaults]
library = files/anatomy/library
module_utils = files/anatomy/module_utils
```

**Operator-facing docs that STAY at top-level `/docs/`:**
- `roadmap-2026q2.md`
- `active-work.md`
- `tier2-app-onboarding.md`
- `coolify-import.md`
- `traefik-primary-proxy.md`
- `tier2-wet-test-checklist.md`
- `bones-and-wings-refactor.md` (this file)
- `llm/security/pentest-task.md` (operator authored, agent-consumed)
- `wet-test-automation.md` (Track P seed)
- `disaster-recovery.md` (if/when written)
- and other operator-facing surface docs

**What MOVES to `files/anatomy/docs/`:**
- Internal-framework specs (framework-overview, framework-plan, migration-authoring, upgrade-recipes, coexistence-playbook, wing-integration)

The split rule: if it's an **operator's runbook**, `/docs/`. If it's an **agent's contract**, `files/anatomy/docs/`.

### 4.3 Subsystems

| Subsystem | Where it runs | Owns | Communicates via |
|---|---|---|---|
| **wing** | local PHP-FPM via Homebrew (`brew services start php@8.3`) | wing.db, web views, REST API | Traefik forward-auth → host:9000 |
| **bone** | local Python via launchd | state.yml, migration/upgrade/patch files (read), playbook subprocess calls | host:8099 (loopback for callback HMAC; Traefik can also expose if needed) |
| **pulse** | local Python via launchd | pulse_jobs table, agent_runs table, profile state | host:8090 (loopback only — no public surface) |
| **plugins** | invoked by pulse OR loaded by wing | per-plugin filesystem space (subdirectory under `files/anatomy/plugins/<name>/runtime/` or `~/anatomy/plugins/<name>/`) | per-plugin: skill stdout JSON, Wing API HTTP, etc. |

**Mental model:** anatomy is a **local desktop application**, not a containerized service mesh. The macOS host is the deploy target; launchd is the supervisor; Traefik (in container) is the only public-edge proxy. Authentik (in container) is the only IAM. Everything else in anatomy is just PHP and Python on the host.

### 4.4 Pulse's two modes

`nos-pulse` runs **two classes** of scheduled work; collapsing them into one runner is deliberate:

1. **Agentic runs** — `claude -p` invocations with system prompt + skill bundle + tool-allowlist. Examples: conductor, inspektor, librarian, scout.
2. **Non-agentic jobs** — plain shell or Python scripts that don't talk to an LLM. Examples: rotate wing.db backup, refresh service-registry, sweep stale agent-run logs, weekly lynis audit, weekly testssl scan, gitleaks scan (PoC plugin).

Both share: schedule definition, auth (per-actor Authentik client_credentials), telemetry contract (events to wing.db), structured logs, operator pause/resume in Wing UI.

### 4.5 The schema artifacts

Three files become the single source of truth for any consumer of Wing+Bone:

- `files/anatomy/skills/contracts/wing.openapi.yml` — generated by `files/anatomy/wing/bin/export-openapi.php`
- `files/anatomy/skills/contracts/bone.openapi.yml` — pulled from Bone's runtime `/openapi.json` by a build-time fetcher
- `files/anatomy/skills/contracts/wing.db-schema.sql` — generated by `files/anatomy/wing/bin/export-schema.php`

These are committed. CI fails if they drift from the live runtime (a check spawns a temp Wing/Bone, fetches live spec, diffs).

**No symlinks** — committed plain files in a stable path. Operator's earlier "symlink" framing collapsed to "single canonical location."

---

## 5. Architecture target — full-local anatomy

### 5.1 Process model

Three local daemons supervised by launchd:

```
                        ┌──────────────────────────────────┐
                        │   macOS host (operator's Mac)    │
                        │                                  │
  Operator → ssh        │  ┌────────────────────────────┐  │
                        │  │  launchd                   │  │
                        │  │                            │  │
                        │  │  ▸ eu.thisisait.nos.wing   │──┼──→ PHP-FPM 127.0.0.1:9000
                        │  │  ▸ eu.thisisait.nos.bone   │──┼──→ FastAPI 127.0.0.1:8099
                        │  │  ▸ eu.thisisait.nos.pulse  │──┼──→ Pulse 127.0.0.1:8090 (loopback only)
                        │  └────────────────────────────┘  │
                        │                                  │
                        │  ┌────────────────────────────┐  │
                        │  │ Docker Desktop (containers)│  │
                        │  │                            │  │
                        │  │ ▸ Traefik (edge)           │──┼──┐
                        │  │ ▸ Authentik (IAM)          │  │  │
                        │  │ ▸ Postgres, MariaDB, Redis │  │  │
                        │  │ ▸ Loki, Prometheus, Tempo  │  │  │
                        │  │ ▸ ntfy, mailpit, Stalwart  │  │  │
                        │  │ ▸ all Tier-1 + Tier-2 apps │  │  │
                        │  └────────────────────────────┘  │  │
                        │                                  │  │
                        └──────────────────────────────────┘  │
                                                              │
                                                              ▼
                                       Traefik file-provider routes:
                                          wing.<tld> → host.docker.internal:9000
                                          (Authentik forward-auth applied)
```

Wing source lives under `~/wing/` on the host. Bone source under `~/bone/`. Pulse source under `~/pulse/`. Each daemon owns its own filesystem space; **no cross-process file mounts**.

### 5.2 Network model

- **Traefik** is the only public-edge proxy. It runs in the `infra` Docker stack (unchanged).
- Traefik's **file-provider** has one static entry per local subsystem that needs public exposure:
  - `wing` → `http://host.docker.internal:9000` with `authentik@file` middleware
  - `bone` → `http://host.docker.internal:8099` with `authentik@file` middleware (limited routes — operator may want some Bone endpoints public for emergency CLI tooling)
  - `pulse` → **no public route**. Pulse is loopback-only.
- **Authentik forward-auth** still runs at the Traefik layer. From Wing's PHP perspective, the auth UX is identical to today (`X-Authentik-*` headers arrive via fastcgi_param).
- **Loopback HTTP** for inter-anatomy calls:
  - Wing → Bone: `http://127.0.0.1:8099/api/...` with JWT (Wing mints its own client_credentials token from Authentik, current pattern).
  - Pulse → Wing: `http://127.0.0.1` with Bearer token from Wing's `tokens` table.
  - Pulse → Bone: `http://127.0.0.1:8099/api/...` with JWT (Pulse mints its own client_credentials).
  - Bone → Wing: `http://127.0.0.1` with Wing's HMAC for events; with JWT for non-event reads (rare).
- **No shared filesystem mounts** between subsystems. wing.db is owned by Wing process; Bone+Pulse access it only via Wing API.

### 5.3 Data ownership

| Data | Owner | Path | Accessed by others via |
|---|---|---|---|
| wing.db (SQLite, WAL mode) | Wing | `~/wing/data/wing.db` | Wing REST API only |
| state.yml | Bone | `~/.nos/state.yml` | Bone REST API only (was: shared mount) |
| Migration recipes | Bone (file) | `files/anatomy/migrations/` (repo) | Bone reads at request time; Wing reads via Bone API |
| Upgrade recipes | Bone (file) | `files/anatomy/upgrades/` (repo) | same |
| Patch outputs | Inspektor / human | `~/wing/patches/` (host) + commit to `files/anatomy/patches/` after operator approval | git |
| Pulse jobs registry | Pulse | `~/pulse/jobs.db` (NEW small SQLite) OR `wing.db.pulse_jobs` (extension table) | Pulse REST API; Wing UI reads via Pulse API |
| Agent run logs | Pulse | `~/pulse/runs/<run_id>/{stdout,stderr,prompt,response}.log` | Pulse API, Loki tail |
| Plugin runtime data | per-plugin | `~/anatomy/plugins/<name>/runtime/` | per-plugin contract |

**Operator decision** (resolved 2026-05-01): pulse jobs registry lives in **Wing's wing.db** as new tables (`pulse_jobs`, `pulse_runs`), NOT a separate Pulse SQLite. Reason: single audit trail, single backup target, single schema migration path. Pulse accesses these tables via the same Wing API as everyone else (no special privileges).

### 5.4 Auth wiring

Each actor (subsystem, agent profile, plugin) gets its own Authentik OIDC client (Track B precedent):

| Client_id | Actor | Scopes (minimum) |
|---|---|---|
| `nos-wing` | Wing → Bone | `nos:state:read`, `nos:migrations:read`, `nos:upgrades:read`, `nos:coexistence:read`, `nos:patches:read` |
| `nos-pulse` | Pulse → Wing/Bone (delegator) | `nos:agent:run`, `nos:pulse:write`, plus delegate-mint capability |
| `nos-conductor` | conductor agent | `nos:state:read`, `nos:migrations:apply`, `nos:upgrades:apply`, `nos:run-tag` |
| `nos-inspektor` | inspektor agent (post-PoC) | `nos:components:read`, `nos:remediation:write`, `nos:pentest:write`, `nos:advisories:write`, `nos:scan:write` |
| `nos-librarian` | librarian agent (post-PoC) | `nos:components:read`, `nos:upgrades:write` |
| `nos-scout` | scout agent (post-PoC) | `nos:observations:write`, `nos:logs:read` |
| `nos-plugin-gitleaks` | gitleaks plugin | `nos:plugins:gitleaks:write`, `nos:repos:read` |
| `nos-plugin-<name>` | each future plugin | per-plugin scope set |

**Per-actor identity is non-negotiable** (operator decision 2026-05-01, point #7). The audit trail (§13) depends on it.

### 5.5 The data flow

```
ansible-playbook run
        │
        ├─► callback_plugins/wing_telemetry.py
        │       ├─ HMAC POST 127.0.0.1:8099/api/v1/events ──► Bone ──HTTP──► Wing ──► wing.db.events
        │       ├─ append ~/.nos/events/playbook.jsonl
        │       └─ exec hooks/playbook-end.d/* (NOS_RUN_ID, NOS_PLAYBOOK_RECAP_*)
        │
        └─ (no other path)

Pulse loop (always-on, launchd-supervised)
        │
        ├─ tick (every 30s):
        │     read pulse_jobs from Wing API → compute due jobs
        │     for each due job:
        │       ├─ if agentic: mint per-profile JWT, exec claude -p, capture output, post results
        │       └─ if non-agentic: spawn subprocess, capture stdout, post to Wing
        │     write run record to wing.db.pulse_runs (HTTP via Wing API)
        │
        ├─ honor pause flag (read every tick from wing.db.pulse_jobs.paused)
        ├─ honor budget guards (per-tier monthly $ + per-run token cap)
        └─ emit telemetry events for each tick + each job start/end

conductor agent (the primary, PoC scope)
        │
        ├─ Pulse fires conductor every 4h (configurable in profile.yml)
        ├─ Phase 1: ansible-playbook --check via Bone /api/run-tag (--check mode)
        ├─ Phase 2: parse drift report, POST to Wing /api/v1/conductor/drifts
        ├─ Phase 3: check Wing /api/v1/approvals?actor=conductor for approved upgrades
        ├─ Phase 4: for each approved item, ansible-playbook --tags <tag> via Bone (apply mode)
        ├─ Phase 5: report run summary to Wing
        └─ on critical drift: trigger notification fanout (mail, ntfy, Wing inbox)

gitleaks plugin (the PoC plugin)
        │
        ├─ Pulse fires gitleaks weekly (Sunday 03:00, configurable)
        ├─ Skill exec: skills/run-gitleaks.sh --repos-from-wing
        ├─ Output: JSON list of findings
        ├─ POST to Wing /api/v1/plugins/gitleaks/findings
        ├─ Wing UI /plugins/gitleaks shows the findings
        ├─ Grafana scrapes plugin metrics counter → dashboards/gitleaks.json
        └─ on critical: ntfy + mail dispatch
```

### 5.6 Track A reversal

Track A (2026-04-26, commit chain `c1bb311..d3a9d35`) containerized Wing and Bone. This refactor reverses that for the platform-control plane, while keeping all other Track A wins:

**Reverted (Wing + Bone host-side):**
- Wing dual-service compose (wing + wing-nginx) → Wing as PHP-FPM via Homebrew
- Bone container in `infra` stack → Bone as Python launchd daemon
- Cross-mount writes to wing.db → HTTP-only access
- Bone's bundled ansible-core 2.18-2.20 → Bone uses operator's ansible-core 2.20.5

**Kept (Track A wins that survive):**
- Traefik file-provider routing for wing.<tld> (just upstream changes from container to `host.docker.internal:9000`)
- Authentik forward-auth via outpost (unchanged at Traefik layer)
- mkcert wildcard cert (Traefik terminates TLS)
- Loki labels for telemetry events (Alloy already tails Wing's PHP-FPM log path)
- Wing as a first-class Tier-1 service in `state/manifest.yml`
- Bone's HMAC events ingestion contract (just the listening address changes)

**Reversal cost: ~1 day** (phase A3 in §8). Net win because zero-trust + native ansible/docker access > containerization-for-its-own-sake.

---

## 6. Plugin system

### 6.1 Plugin model — what a plugin is (and is not)

A **plugin** is a unit of **anatomy auto-wiring**, not (necessarily) a service. The distinction matters and resolves a known tech debt:

- The **service** (a Tier-1 role like `pazny.grafana`, a Tier-2 manifest like `apps/myservice.yml`, or simply a host-installed binary like `gitleaks`) is the deployable artifact. Services live where Ansible/Tier-2 conventions put them: `roles/`, `apps/`, or `brew install`.
- The **plugin** is the *wiring layer* that connects a service (or a set of services) to **anatomy** (Wing UI, Pulse jobs, audit), to **infra** (Postgres/MariaDB/Redis storage, named volumes, secrets), and to **observability** (Prometheus scrape, Loki labels, Grafana dashboards, Tempo OTLP).

This split exists because **autowiring is the tech debt that keeps growing**. Today, when Grafana is installed, the dashboards live in `roles/pazny.grafana/files/dashboards/`, the Prometheus scrape config lives in `roles/pazny.alloy/templates/`, the database init lives in `tasks/stacks/core-up.yml`, and the OIDC config lives in `default.config.yml`. When we add `pazny.spacetimedb`, the wiring between Grafana and SpaceTimeDB ends up scattered across the same surfaces — usually buried in `tasks/post.yml` of one role or the other. **A plugin manifest collects all of that wiring into ONE file, owned by the integration, not by the services it integrates.**

The plugin loader is the central authority that applies these manifests; the services themselves do not know they have plugins.

### 6.2 Plugin types

Three shapes, each handled by the loader differently:

| Type | What it is | Service binding | Example | PoC scope? |
|---|---|---|---|---|
| **skill** | Pure capability addition; no service install (or just a brew binary) | none required | gitleaks (binary + capability) | ✅ ships in PoC |
| **service** | Wraps an existing role/apps with a complete autowiring spec | declares `requires: { role: pazny.X }` or `requires: { apps_manifest: apps/Y.yml }` | grafana-with-anatomy-defaults | post-PoC |
| **composition** | Cross-service wiring; activates only when ALL declared services are installed | declares multiple `requires` entries | grafana-spacetimedb (fires only when both grafana AND spacetimedb are on) | post-PoC |

Each plugin can declare any combination of capability sections (skill, scheduled-job, ui-extension, notifier). The **service** and **composition** types additionally support:

- **`infra:`** — declare a Postgres database, MariaDB database, Redis namespace, named Docker volume, or secret pull from Infisical. The loader creates these on activation; preserves on removal (the service plugin owns the data, not the role).
- **`observability:`** — extend the existing observability section with explicit Prometheus scrape entries, Loki labels, Tempo OTLP source URL, Grafana datasource registration, optional alert rules. (Today the gitleaks manifest's `observability:` block declares plugin-self-metrics; service/composition plugins extend that to declare wiring for the **service** they wrap.)

**The PoC schema is forward-compatible.** The gitleaks plugin.yml is a valid skill plugin AND a valid forward-spec for service/composition plugins (the loader simply doesn't activate the unused branches today). Post-PoC commits add the service + composition logic to the loader without breaking existing skill plugins.

### 6.3 Plugin manifest (skill type — the PoC shape)

A plugin is a directory under `files/anatomy/plugins/<name>/` with a `plugin.yml` manifest. The manifest declares **which capabilities the plugin exposes**, and Wing's plugin loader auto-wires them on `--tags anatomy.plugins`.

**Canonical manifest (gitleaks PoC):**

```yaml
# files/anatomy/plugins/gitleaks/plugin.yml
name: gitleaks
version: 0.1.0
description: Scan committed git repos for leaked secrets
upstream: https://github.com/gitleaks/gitleaks
license: MIT

# multi-shape: a plugin can declare any combination of these
type:
  - skill            # callable from agents
  - scheduled-job    # invoked by Pulse on cron
  - ui-extension     # adds Wing routes/views
  - notifier         # registers mail/ntfy templates

# host-side install (executed by pazny.anatomy on --tags anatomy.plugins)
requirements:
  binary: gitleaks
  install_via: brew
  brew_formula: gitleaks
  min_version: "8.0"

# skill: a runnable capability with a typed JSON output
skill:
  entry: skills/run-gitleaks.sh
  contract: contracts/gitleaks-output.schema.json
  network_required: false
  args_template:
    - "--source"
    - "{{ repo_path }}"
    - "--report-format"
    - "json"

# scheduled-job: Pulse will UPSERT this into pulse_jobs
scheduled-job:
  cron: "0 3 * * 0"
  jitter_min: 15
  command: skills/run-gitleaks.sh
  args:
    - "--repos-from-wing"
    - "--scan-history"
  max_runtime_min: 60
  max_concurrent: 1

# ui-extension: Wing plugin loader registers routes + views
ui-extension:
  routes:
    - path: /plugins/gitleaks
      presenter: App\Presenters\Plugins\GitleaksPresenter
      template: views/Plugins/GitleaksFindings.latte
  menu:
    parent: security
    label: "Git Leaks"
    icon: lock
    order: 30
  api_endpoints:
    - method: POST
      path: /api/v1/plugins/gitleaks/findings
      scope: nos:plugins:gitleaks:write
    - method: GET
      path: /api/v1/plugins/gitleaks/findings
      scope: nos:plugins:gitleaks:read

# Authentik OIDC client for the plugin's writes
authentik:
  client_id: nos-plugin-gitleaks
  scopes:
    - nos:plugins:gitleaks:write
    - nos:repos:read

# GDPR Article 30 register row
gdpr:
  data_categories: [git_history, secret_metadata]
  data_subjects: [developers, contributors]
  legal_basis: legitimate_interests
  retention_days: 365
  processors: []           # all processing is local

# Observability: Wing plugin loader registers Grafana dashboard
observability:
  metrics:
    - name: gitleaks_findings_total
      type: counter
      labels: [severity, repo, secret_type]
    - name: gitleaks_scan_duration_seconds
      type: histogram
  dashboard: dashboards/gitleaks.json

# Notifications: severity → channel mapping
notification:
  on_critical: [mail, ntfy, wing-inbox]
  on_high: [ntfy, wing-inbox]
  on_medium: [wing-inbox]
  templates:
    mail: notifications/mail-critical.txt
    ntfy: notifications/ntfy-critical.txt

# wing.db schema additions (idempotent CREATE TABLE IF NOT EXISTS)
schema:
  - migrations/0001_create_gitleaks_findings.sql
```

### 6.4 The plugin loader

> **Updated 2026-05-03 from V3 findings (`files/anatomy/docs/grafana-wiring-inventory.md`):** the loader needs **4 lifecycle hooks**, not a single linear pass, because plugin work depends on stack/role state that isn't all available at one moment. See `files/anatomy/docs/plugin-loader-spec.md` for the consolidated A6 implementation contract.

`pazny.anatomy --tags anatomy.plugins` runs the plugin loader, which moves through **4 lifecycle hooks** that interleave with the playbook's existing role-render → docker-compose-up → post-tasks pipeline:

#### Hook 1 — `pre_render` (runs early in main.yml, before any role render)

For every discovered plugin:

1. **Discover** every `files/anatomy/plugins/*/plugin.yml`.
2. **Validate** each manifest against `state/schema/plugin.schema.json` (covers all 3 types: skill / service / composition).
3. **Resolve `requires.role` / `requires.feature_flag` / `requires.apps_manifest`.** Skip plugin if its required role isn't enabled or required apps manifest isn't installed (composition plugins skip when ANY required service is off).
4. **Install host requirements** (`brew install gitleaks`; `docker pull <image>`; `url`+chmod+checksum).
5. **Register Authentik clients** — emit blueprint entries into the same blueprint stream that `tasks/stacks/core-up.yml` reconverges. **This must run BEFORE the Authentik blueprint apply step** (pitfall P4 from `role-thinning-recipe.md`).

#### Hook 2 — `pre_compose` (runs after role render, before `docker compose up <stack>`)

Per plugin (in dependency order):

6. **Ensure plugin-owned dirs exist** (`provisioning/`, etc., per manifest).
7. **Render compose-extension fragment** (the "vessel" — `files/anatomy/plugins/<n>/templates/<n>.compose.yml.j2` → `{{ stacks_dir }}/<stack>/overrides/<plugin-name>.yml`). Compose's existing `-f`-discovery loop in core-up.yml/stack-up.yml picks it up — **no orchestrator change needed** (verified during V3 inventory).
8. **Render provisioning files** (datasources, dashboards, scrape configs) into their target paths.
9. **Apply schema migrations** by running each `schema:` SQL file against wing.db (idempotent).

#### Hook 3 — `post_compose` (runs after `docker compose up <stack> --wait`)

Per plugin:

10. **Wait for plugin's target service to be healthy** (HTTP probe per manifest; default = role's primary health endpoint).
11. **API-side registrations:** Wing routes (write `files/anatomy/wing/config/plugins.neon`); Pulse jobs (POST `/api/v1/pulse_jobs`, UPSERT on plugin_name+job_name); Grafana dashboards (POST dashboard JSON, folder-isolated under "Plugins/<plugin-name>/"); ntfy/mail templates (write to `~/anatomy/notifications/templates/`).
12. **GDPR row UPSERT** via Wing API (`POST /api/v1/gdpr/processors`).
13. **Restart Wing** (graceful PHP-FPM reload — `brew services restart php@8.3`) so new routes/views are live.
14. **Restart Pulse** (launchd reload) so new jobs are scheduled.

#### Hook 4 — `post_blank` (runs only when `blank=true`)

Per plugin:

15. **Remove plugin-owned filesystem state** per manifest's `lifecycle.post_blank:` declarations (provisioning dirs, cached downloads).
16. **Audit log preserved** — `actor_id`-tagged rows in wing.db are NEVER cleared on blank (regulatory requirement). Plugin's data tables follow per-manifest `gdpr.retention_days`.

#### Critical ordering invariants

| Constraint | Why |
|---|---|
| Hook 1 step 5 (Authentik registration) MUST run before existing Authentik blueprint reconverge in `tasks/stacks/core-up.yml` | else blueprint apply fails because client doesn't exist (P4) |
| Hook 2 steps 6-9 MUST run before `docker compose up <stack>` | because compose-extension fragments + provisioning files must exist when compose merges (`grafana` won't see dashboards otherwise) |
| Hook 3 steps 10-12 MUST run after `docker compose up <stack> --wait` | because target service must be alive to accept API calls |
| Hook 3 steps 13-14 MUST run after step 11 | because Wing/Pulse reload picks up registered config |
| Hook 4 MUST run before role's data dir wipe | so plugin can do orderly cleanup before bulk `rm -rf` |

This is the "auto-wiring" — drop a plugin directory, run one tag, capability is live in <30 seconds. **The 4-hook split is what makes it actually work** — single-pass would have to either run before compose (no API access) or after (provisioning files arrive too late).

### 6.5 Plugin removal

`ansible-playbook --tags anatomy.plugins -e remove_plugin=gitleaks` runs the inverse:
- Pulse jobs deactivated (not deleted — kept for audit trail with `removed_at` timestamp)
- Wing routes/views dropped from generated NEON
- Grafana dashboard moved to "Plugins/Archived/"
- Authentik client disabled (not deleted)
- Schema tables retained (data preserved)
- Binary uninstall is OPT-IN (`-e remove_plugin_binary=true`) — operator may want gitleaks for ad-hoc CLI use even after plugin removal

### 6.6 Plugin development workflow

For an operator (or Claude) adding a new plugin:

```bash
# 1. Scaffold from template
cp -r files/anatomy/plugins/_template files/anatomy/plugins/myplugin
$EDITOR files/anatomy/plugins/myplugin/plugin.yml

# 2. Write the skill script
$EDITOR files/anatomy/plugins/myplugin/skills/run-myplugin.sh

# 3. (optional) Write the Wing UI Latte view
$EDITOR files/anatomy/plugins/myplugin/views/MyPluginFindings.latte

# 4. Validate manifest locally
python3 -m files.anatomy.scripts.validate_plugin files/anatomy/plugins/myplugin/

# 5. Apply
ansible-playbook main.yml -K --tags anatomy.plugins
```

For full PoC validation see §8 phase A7.

### 6.7 Plugin types beyond PoC scope

Once the gitleaks pattern (skill plugin) is proven, the plugin system extends to other tools and to the service + composition plugin types.

**Other skill plugins (~2-4h each, post-PoC):**

| Tool | Plugin type | Cadence |
|---|---|---|
| trivy | skill + scheduled-job | nightly per-image |
| grype + syft | skill + scheduled-job | nightly per-image (paired) |
| nuclei | skill + scheduled-job | weekly |
| semgrep | skill (called by inspektor) | per-area |
| lynis | scheduled-job | weekly |
| testssl.sh | scheduled-job | weekly |
| osquery | scheduled-job | daily |

Plus non-cybersec skill plugins:
- backup verification (scheduled-job)
- service-registry refresh (scheduled-job)
- GDPR weekly digest (scheduled-job + notifier)
- mailpit retention sweep (scheduled-job)

### 6.8 Service + composition plugin examples (post-PoC, sketch)

These two examples illustrate the post-PoC plugin shapes. They are **not** committed yet; the manifests below are forward-spec drafts to anchor the schema design.

**Service plugin (`grafana`).** Wraps the existing `pazny.grafana` role with a complete autowiring spec. The role itself is unchanged; the plugin manifest replaces the scattered wiring code that today lives in `roles/pazny.grafana/tasks/*.yml`, `default.config.yml`, and `tasks/stacks/core-up.yml`:

```yaml
# files/anatomy/plugins/grafana/plugin.yml (post-PoC sketch)
name: grafana
type: [service]
requires:
  role: pazny.grafana
  feature_flag: install_grafana

infra:
  postgres:
    db_name: grafana
    db_owner: grafana
    password_var: grafana_pw
  named_volumes:
    - { name: grafana_data, mount: /var/lib/grafana }
  secrets:
    pull_from: infisical
    keys: [grafana_admin_pw, grafana_oidc_client_secret]

observability:
  prometheus_scrape:
    - target: grafana:3000
      path: /metrics
      interval: 30s
  grafana_self_datasources:
    - { type: prometheus, url: http://prometheus:9090 }
    - { type: loki, url: http://loki:3100 }
    - { type: tempo, url: http://tempo:3200 }

ui-extension:
  wing_systems_link:
    label: "Grafana"
    url: "https://grafana.<tld>"
    tier: T1

authentik:
  oidc_app: grafana          # already in authentik_oidc_apps
```

**Composition plugin (`grafana-spacetimedb`).** Activates only when both `pazny.grafana` AND `pazny.spacetimedb` are enabled. Encodes cross-service wiring that today would be buried in `roles/pazny.spacetimedb/tasks/post.yml`:

```yaml
# files/anatomy/plugins/grafana-spacetimedb/plugin.yml (post-PoC sketch)
name: grafana-spacetimedb
type: [composition]
requires:
  - { role: pazny.grafana, feature_flag: install_grafana }
  - { role: pazny.spacetimedb, feature_flag: install_spacetimedb }

# When both are enabled, this plugin extends Grafana to consume SpaceTimeDB telemetry.
observability:
  prometheus_scrape:
    - target: spacetimedb:9000
      path: /metrics
      interval: 15s
  grafana_dashboards:
    - dashboards/spacetimedb-overview.json
    - dashboards/spacetimedb-queries.json
  loki_labels:
    service: spacetimedb

# Optional: extend Wing UI to surface SpaceTimeDB-specific anomalies under the Grafana view
ui-extension:
  wing_view_extension:
    target: /plugins/grafana
    snippet: views/spacetimedb-grafana-extension.latte
```

**Why this matters.** Today, the SpaceTimeDB→Grafana wiring would be authored in `roles/pazny.spacetimedb/tasks/post.yml` (or worse, split between that file and `roles/pazny.grafana/tasks/dashboards.yml`). When `pazny.spacetimedb` is removed in a future blank, the wiring leftovers are easy to forget. With composition plugins, the wiring is **owned by the integration**, not by either service. Removing the integration is `--tags anatomy.plugins -e remove_plugin=grafana-spacetimedb`. Adding it is dropping the directory and re-running the tag.

Migrating today's role-internal autowiring code into composition plugins is a **separate post-PoC effort** — see §13's note on "autowiring debt consolidation" (proposed **Track Q**, scope TBD).

---

## 7. Agent profiles

### 7.1 Conductor — the primary

**Cadence:** every 4h (default; configurable per profile.yml).
**Tier:** T2 (smart but not SOTA).
**Job:** run `ansible-playbook --check` on schedule, report drift, apply approved upgrades/migrations.

**Phases per run:**

1. **Drift scan.** Bone receives `POST /api/v1/run-tag` with `tags=core,stacks` and `extra_vars={ansible_check_mode: true}`. Bone shells out `ansible-playbook --check`, captures stdout, parses `changed:` lines per host.
2. **Drift report.** Conductor POSTs to Wing `/api/v1/conductor/drifts` with: run_id, timestamp, change_count, top-10 changes (task name + module + diff summary).
3. **Approval check.** Conductor GETs `/api/v1/approvals?actor=conductor&status=approved`. Returns: list of pending upgrade IDs, migration IDs, with operator-attached approval timestamps.
4. **Apply approved.** For each approved item:
   - upgrade: `POST /api/v1/upgrades/{id}/apply` (existing Bone endpoint) — Bone runs the recipe.
   - migration: `POST /api/v1/migrations/{id}/apply` (existing) — Bone runs the migration.
5. **Run summary.** Conductor POSTs run summary to Wing `/api/v1/conductor/runs` with phase-level success/failure.
6. **Critical-drift fanout.** If drift count > threshold (configurable, default 50 changes), fire notification fanout (mail + ntfy + Wing inbox).

**Profile YAML (canonical for conductor PoC):**

```yaml
# files/anatomy/agents/conductor/profile.yml
name: conductor
tier: T2
schedule:
  cron: "0 */4 * * *"
  jitter_min: 5
  cooldown_min: 200

runtime:
  command: claude
  args: ["-p", "{{ system_prompt_path }}", "--output-format=json"]
  max_runtime_min: 30
  max_tokens_per_run: 100000
  max_cost_per_run_usd: 2.50

authentik:
  client_id: nos-conductor
  scopes:
    - nos:state:read
    - nos:migrations:apply
    - nos:upgrades:apply
    - nos:run-tag

prompt:
  system: files/anatomy/agents/conductor/prompt.md
  user_template: |
    Last run summary: {{ last_run.summary | default('(no prior run)') }}
    Pending approvals: {{ approvals_pending_count }}
    Open critical drifts: {{ critical_drifts_count }}

skills:
  - api-call
  - run-tag

tool_allowlist:
  - "Bash(skills/api-call/api-call.sh:*)"
  - "Bash(skills/run-tag/run-tag.sh:*)"
  - Read
  - Glob
  - Grep

gdpr:
  data_categories: [system_state_metadata]
  legal_basis: legitimate_interests
  retention_days: 90
  processors: [anthropic]

pause:
  default: false
  reason: ""

guards:
  max_changes_per_run: 5            # never apply more than 5 approved items per run
  abort_on_drift_threshold: 200     # if drift > 200 changes, drift report only, no apply
  require_blank_test_within_days: 7 # if last successful blank > 7 days ago, drift report only, no apply
```

The system prompt (`files/anatomy/agents/conductor/prompt.md`) is operator-authored, ~150 lines, structured like pentest-task.md.

### 7.2 Post-PoC profiles

These ship after the conductor + gitleaks PoC is operator-validated. Each is a separate commit, ~2-4h work:

| Profile | Tier | Cadence | One-line job |
|---|---|---|---|
| **inspektor** | T1 | 2× daily | wire pentest-task.md as system prompt; existing flow Phases 1+2+2b+3 |
| **librarian** | T2 | daily | upstream version watcher → POST `/upgrades/pending` |
| **scout** | T4 | every 30 min | tail logs + telemetry → flag anomalies → POST `/observations` |

**Migrator and steward (from earlier sketch) are dropped.** Their work is folded into:
- Conductor (applies approved items — was migrator's apply phase)
- Librarian (drafts upgrade entries — was migrator's draft phase, simplified)
- Operator (reviews + approves via Wing UI inbox — was steward's triage)

If post-PoC operator notices steward-shaped work missing, add it then. YAGNI for PoC.

### 7.3 Per-agent identity

Every profile has its own `authentik.client_id` (e.g. `nos-conductor`, `nos-inspektor`). Pulse mints per-profile client_credentials JWTs at run-time (cached <55min). Every action attributable to a profile is **tagged with that client_id** at the wing.db row level.

This is the foundation for §13 (audit trail).

---

## 8. PoC phase plan

PoC = end-to-end one plugin (gitleaks) + one agent (conductor) + the platform skeleton that supports them. Sequential, ~12 days. Parallelization is possible (§8.2) but operator's expressed preference is sequential with their context-management help.

### 8.1 Sequential phases (happy path)

| # | Phase | What | Time |
|---|---|---|---|
| **A0** | anatomize-skeleton | Create `files/anatomy/` skeleton dirs (empty); update `.gitignore`; update `ansible.cfg` library/module_utils paths (pointing at empty dirs initially — won't break since CI doesn't run Ansible-modules tests yet); commit. | 0.5 d |
| **A1** | anatomize-move | Move existing dirs in batches: `migrations/` → `files/anatomy/migrations/`, `library/` → `files/anatomy/library/`, `module_utils/` → `files/anatomy/module_utils/`, `patches/` → `files/anatomy/patches/`. Update playbook `import_role`/`include_tasks` paths if any reference moved files. Move framework-internal docs from `/docs/` to `files/anatomy/docs/` per split rule (§4.2). Update `/CLAUDE.md` to reflect new paths. | 1 d |
| **A2** | wing-move | **Rescoped 2026-05-03** (was 'wing-submodule' — see §3.1 correction). `git mv files/project-wing/* files/anatomy/wing/` (Dockerfile + app/ + bin/ + www/ + tests/ + composer.json + .gitignore + .dockerignore). Update `roles/pazny.wing/tasks/main.yml` rsync source path. Update Dockerfile build context references. Run blank to verify Wing container builds + serves from new path. Future submodule consideration deferred (Wing source authoring is part of THIS repo; if it ever spins out to its own repo we can add the submodule then). | 0.5 d |
| **A3a** | bone host-revert | **2026-05-03** ✅: `pazny.bone` rewritten to host launchd: Python venv at `~/bone/venv`, source moved `files/bone/` → `files/anatomy/bone/`, `eu.thisisait.nos.bone` plist on uvicorn 127.0.0.1:8099. Track-A reversal cleanup task stops + removes legacy bone container + drops compose override. Traefik file-provider routes `api.<tld>` → `nos-host:8099` automatically (already in Tier-1 manifest). | 0.5 d |
| **A3.5** | wing host-revert via FrankenPHP | **Operator-chosen path 2026-05-03**: replace the FPM/nginx-sidecar pair with a single FrankenPHP binary on the host. FrankenPHP = PHP runtime + Caddy HTTP server in one process; serves Wing's index.php directly over HTTP (no FastCGI, no nginx). `brew install frankenphp` installs the binary; `frankenphp run` (or `php-server` mode) on `127.0.0.1:9000`. Traefik file-provider routes `wing.<tld>` → `nos-host:9000` directly. Eliminates wing-nginx container entirely. Migration: stop wing+wing-nginx containers via track-A reversal block (mirrors A3a Bone), retire compose-override fragments, render Caddyfile (or use FrankenPHP's `--listen` flag), launchd plist `eu.thisisait.nos.wing` running `frankenphp run` from `~/wing/app/`. **Risk:** new runtime; first wet run may surface PHP extension gaps (Wing's composer deps assume FPM environment). Mitigation: FrankenPHP supports the same PECL extensions, just verify gd/pdo_sqlite/etc. load. | 1.5 d |
| **A4** | pulse-skeleton | New `roles/pazny.pulse/` thin role: install Python venv at `~/pulse/venv`, copy `files/anatomy/pulse/*` to `~/pulse/`, manage launchd plist. Implement Pulse daemon: tick loop (30s), reads `wing.db.pulse_jobs` via Wing API, fires due jobs, logs runs to `wing.db.pulse_runs`. **No agentic runs yet** — only non-agentic subprocess shape. New wing.db tables `pulse_jobs`, `pulse_runs` via schema migration. | 1 d |
| **A5** | wing-exports | Write `files/anatomy/wing/bin/export-openapi.php` (introspects Nette router + presenter PHPDoc → OpenAPI 3.1 YAML). Write `files/anatomy/wing/bin/export-schema.php` (introspects wing.db at runtime → DDL). Commit outputs to `files/anatomy/skills/contracts/`. Add CI drift check that re-runs exports vs committed and diffs. | 1 d |
| **A6** | plugin-system | `state/schema/plugin.schema.json` JSONSchema for manifests — covers ALL three plugin types (skill / service / composition). Implement plugin loader (Python module under `files/anatomy/scripts/load_plugins.py`) called by `pazny.anatomy --tags anatomy.plugins`. Implements **all 4 lifecycle hooks** (`pre_render`, `pre_compose`, `post_compose`, `post_blank`) per §6.4 + `files/anatomy/docs/plugin-loader-spec.md`. Loader is wired into `tasks/stacks/core-up.yml` + `stack-up.yml` at the canonical hook points (immediately before existing role-render block, between role-render and compose-up, after compose-up --wait, on blank-reset). Loader code paths exist for all three plugin types (PoC only fires skill + one service path; composition stays untested-but-loadable). Includes `scaffold` subcommand: `python3 -m anatomy.load_plugins scaffold <n> --type {skill,service,composition}` → creates skeleton from per-type `_template`. | 2.5 d (was 2 d — bumped for 4-hook implementation surface) |
| **A6.5** | grafana-thin-role-pilot | **Doctrine proof point (§1.1).** Migrate `roles/pazny.grafana/` to thin shape: keep `defaults/main.yml` + `tasks/main.yml` (data dir + compose render only) + `templates/compose.yml.j2` + `meta/main.yml`. Move EVERYTHING else (dashboards, OIDC config block, Prometheus datasource, Loki/Tempo wiring, alert rules, notifier templates) into a NEW `files/anatomy/plugins/grafana-base/plugin.yml` (service plugin with `requires.role: pazny.grafana`). Loader applies the wiring on `--tags anatomy.plugins`. Document the recipe in `files/anatomy/docs/role-thinning-recipe.md` (the deterministic 6-step process: identify wiring → create plugin manifest → move dashboards → move OIDC → move scrape → smoke-test). **Exit:** fresh blank with thin grafana + grafana-base plugin produces byte-identical functional Grafana (dashboards, datasources, OIDC, scrape, alerts all green; `diff` between old `~/.nos/state.yml` snapshot and new shows only path drift). | 1.5 d |
| **A7** | gitleaks-poc | First skill plugin: gitleaks. Manifest, skill (`skills/run-gitleaks.sh` invokes gitleaks binary, parses output, normalizes JSON), Wing Latte view, Grafana dashboard, mail+ntfy templates, GDPR row, schema migration for `wing.db.gitleaks_findings`. End-to-end: `ansible-playbook --tags anatomy.plugins`, gitleaks runs Sunday 03:00 (or `--tags anatomy.plugins,run_now=gitleaks` for immediate test). | 1 d |
| **A8** | conductor-poc | Conductor profile + system prompt. Pulse runner harness for agentic mode (`bin/pulse-run-agent.sh` mints token, assembles prompt, exec's claude, captures output, posts results). Wing `/inbox` view: pending approvals, conductor drift reports, gitleaks findings (unified inbox). Wing `/approvals` view: approve/reject buttons for pending upgrades. Conductor first run end-to-end: drift scan → drift report → operator-creates-test-approval → conductor next run applies it. | 2 d |
| **A9** | notification-fanout | Notification dispatcher (Python module under `files/anatomy/wing/lib/notifications.py` — but Wing-PHP-side; Python module to be moved or rewritten as PHP). Wing `/inbox` is primary. ntfy: HTTP POST to ntfy container with topic `nos-critical`. Mail: SMTP to mailpit (Stalwart fallback when Track G ships). Templating uses notification template files from plugin manifest. Severity routing per manifest `notification:` block. | 1 d |
| **A10** | audit-trail | Schema migration: add `actor_id` (FK to authentik clients), `actor_action_id` (UUID per action), `acted_at` to all wing.db write tables. Wing `/audit` view: filter by actor, by data category, by time range. GDPR Article 30 view auto-aggregates from `gdpr_processors` + `audit_log`. Per-agent Authentik blueprints (conductor + plugin-gitleaks for PoC) via Track B framework. | 1 d |

**Total: 14.0 days** (was 14.5 — A2 rescoped from submodule 1d → path-move 0.5d after 2026-05-03 correction that Wing source IS in repo). Slack to 16 days realistic.

### 8.2 Parallelization (if operator wants multiple agents)

The PoC is small enough that parallelization saves <2 days. Sequential is recommended. If parallelizing:

- **A0 + A1** are strict-sequential (anatomize first, move second).
- **A2** depends on A1 (paths).
- **A3** depends on A2 (Wing source must be reachable).
- **A4 + A5** are parallel-friendly after A3 (different files, no cross-deps).
- **A6** depends on A4 (Pulse must exist for plugin loader to register jobs).
- **A7** depends on A6 (plugin loader is the dependency).
- **A8** depends on A4 + A6 (Pulse runner harness extends Pulse skeleton).
- **A9 + A10** are parallel-friendly after A8.

Recommended split if 2 agents: agent-A on A0-A6 main spine; agent-B on A5+A7 (exports + gitleaks plugin) once A4 lands.

### 8.3 PoC exit criteria

- `files/anatomy/` is the home for all bones-and-wings code; top-level `migrations/`, `library/`, `module_utils/`, `patches/` directories are gone.
- `external/wing/` submodule resolves; `pazny.anatomy --tags anatomy.wing` renders Wing source from submodule into `~/wing/`.
- Wing runs as PHP-FPM via Homebrew on host:9000; Bone runs as launchd Python on host:8099; Pulse runs as launchd Python on host:8090. No Wing/Bone containers in any compose stack.
- Traefik routes `wing.<tld>` → `host.docker.internal:9000` with Authentik forward-auth.
- `files/anatomy/skills/contracts/{wing,bone}.openapi.yml` + `wing.db-schema.sql` are committed; CI drift check passes.
- gitleaks plugin is installed via `--tags anatomy.plugins`; Wing UI shows `/plugins/gitleaks`; Grafana shows the gitleaks dashboard; ntfy delivers a critical-severity test message; GDPR row present.
- Conductor agent runs every 4h; first drift report visible in Wing `/inbox`; one operator approval round-trip verified end-to-end.
- Audit trail: every write to wing.db has `actor_id` + `acted_at`; `/audit` view filters work.
- All existing tests still pass (89 apps + 438 total as of 2026-05-03). New tests: ~30 for plugin schema (covers all 3 types) + ~15 for conductor profile + ~10 for Wing exports + ~10 for grafana thin-role parity check.
- **§1.1 doctrine proof:** thin `pazny.grafana` + `grafana-base` service plugin produces byte-identical functional Grafana vs. pre-Track-Q state. `files/anatomy/docs/role-thinning-recipe.md` documents the 6-step migration process. **If this exits red, the doctrine isn't shippable and Track Q is paused for redesign.**

---

## 9. Edge cases catalog

Organized by surface; each item has a one-line **mitigation** the implementing agent must respect.

### 9.1 Concurrency

- **Two pulse ticks fire same job.** Pulse acquires `wing.db.pulse_jobs.lock_token` per job via UPDATE-IF; second tick skips. *Test: simulated double-tick.*
- **wing.db locked during agent run.** SQLite WAL mode + Wing API uses short transactions. *Test: 100 concurrent /events POSTs while conductor fires.*
- **Bone restart during agent run.** Skill `api-call.sh` retries on 502/503 with exponential backoff (max 5 retries, max 5 min). *Test: kill bone mid-run; verify resume or clean fail.*
- **Authentik down during agent run.** Pulse caches client_credentials JWTs for 55 min; running runs complete with cached token; new runs fail-fast with `agent.run.error{auth_unavailable}`. *Test: stop authentik; verify scheduled run is suppressed not retry-looped.*
- **Wing PHP-FPM reload mid-request.** PHP-FPM graceful reload (SIGUSR2) drains in-flight requests before swap. *Test: `brew services restart php@8.3` while gitleaks plugin is POSTing 100 findings.*

### 9.2 Token budget / cost

- **Profile exceeds `max_tokens_per_run`.** Pulse passes `--max-tokens` to claude; runner intercepts SIGTERM-on-overrun, posts `agent.run.terminated{reason: budget}`.
- **Daily aggregate budget breach.** Per-tier monthly budget in `state/agent-budgets.yml`; pulse refuses to fire when projected month-to-date exceeds; emits `agent.budget.warn` at 80%, refuses at 100%. *Test: $1 monthly budget on T4; let scout run to refusal.*
- **Anthropic API rate limit.** Pulse honors `Retry-After`; telemetry distinguishes `rate_limit` from `error`.
- **Operator forgot to pause an agent before infra change.** `state/cron-jobs.yml` has `pause-all-agents-during-blank` on `playbook_start{blank=true}`. Approval workflow has "snooze for N hours" button.

### 9.3 Auth / token delegation

- **Per-profile JWT minted by pulse.** Pulse holds a "delegator" client_credentials grant; mints per-profile sub-tokens with restricted scopes via Authentik property mappings (Track B framework).
- **JWT compromised — leak in agent log.** Loki redacts `Authorization: Bearer .*` in callback regex; runner masks token in stdout. *Test: deliberately echo $TOKEN, verify Loki shows `[REDACTED]`.*
- **HMAC secret rotation.** New `migrations/2026-XX-rotate-bone-hmac.yml`: stop callback → swap secret → restart Bone → resume callback. *Today: rotates only on `blank=true`.*
- **Conductor with `nos:upgrades:apply` could mass-apply on bug.** Profile schema enforces `guards.max_changes_per_run: 5` (configurable, default 5); runner counts and aborts. *Test: malicious prompt "apply 1000 upgrades", verify abort at 5.*
- **Plugin-gitleaks's scope used to spam findings.** `nos:plugins:gitleaks:write` is plugin-scoped; can't write to other plugins' tables. Schema enforces table prefixing.

### 9.4 Prompt versioning / drift

- **DB schema changes; old prompt references missing column.** Each profile YAML has `schema_min_version: <int>`; if `wing.db-schema.sql` diverges past that, pulse refuses to fire and emits `agent.run.skipped{reason: schema_drift}`.
- **Two agents update prompt source simultaneously.** Prompts under git; pulse reads from disk. Conflicts resolve at git-merge time.
- **Prompt mid-edit.** Pulse reads with `flock(LOCK_SH)`; operator's Wing UI edits write a `.draft` sibling, atomic-rename on save.

### 9.5 Plugin loading

- **Plugin manifest schema invalid.** Loader rejects with line-number error before any side effect. *Test: malformed YAML.*
- **Plugin requires brew formula not on system.** Loader runs `brew install <formula>` first; failure aborts loading; Wing UI shows plugin as `disabled{reason: install_failed}`.
- **Plugin tries to register Wing route conflicting with core.** Loader checks `route` against existing route table; conflict → reject with `route_collision` error.
- **Plugin's schema migration breaks wing.db.** Loader runs migrations in a `BEGIN; … COMMIT;` block per migration file; failure rolls back; loader posts `plugin.install.failed{schema_migration: ...}`.
- **Plugin posts findings faster than Wing can index.** Wing's `/api/v1/plugins/<name>/findings` rate-limits to 100 POSTs/min per client; 429 with `Retry-After`.
- **Plugin's Grafana dashboard JSON is invalid.** Loader validates against Grafana schema before POSTing; rejects with `dashboard_invalid`.
- **Operator removes a plugin while a run is in flight.** Loader's remove path waits for in-flight runs to finish (max 5 min) before deactivating; force-remove (`-e remove_plugin_force=true`) cancels.

### 9.6 Agent loop / amplification

- **Conductor's apply triggers blank → wing.db wiped → audit lost.** **CRITICAL:** `conductor` profile guards include `require_blank_test_within_days: 7` AND `max_changes_per_run: 5` — conductor will never apply a `blank=true`. Blank is operator-only forever. *Test: prompt-injection attempt "apply blank=true", verify refusal.*
- **Inspektor's finding triggers librarian → conductor → migration apply.** Multi-step chain; break point is `/approvals` operator gate. *Test: chain happy path, verify operator must click 3 times (one per agent's output).*
- **Two agents POST same finding.** Wing API deduplicates on `finding_ref` → 409 Conflict.
- **Scout flaps an alarm; downstream replans repeatedly.** Scout (post-PoC) profile has `min_evidence_count: 3` for plan promotion.

### 9.7 Local model fallback

- **Operator switches `runtime.command` from `claude` to `ollama-cli` later.** Profile YAML validates `command` against allowlist; pulse adapts arg-construction per command. *Test: profile with `command: ollama-cli` parses; runner exec's right binary.*
- **Local model context too small.** Profile declares `min_context_tokens`; runner refuses if model card reports less.
- **Local model output format differs.** Profile declares `requires_structured_output: true`; runner adapts or refuses.

### 9.8 Data residency / GDPR

- **Anthropic API is non-EU.** Wing's GDPR view auto-includes a row for each agent profile with `processors: [anthropic]`. Operator-visible. (Tip: when local-LLM lands, processor list narrows.)
- **Source code excerpts sent to Anthropic.** Inspektor's prompt sends file:line excerpts (already does today). GDPR row covers; `data_categories: [source_code_excerpts]`.
- **Customer data in agent prompts.** Forbidden. Profile schema rejects `data_categories` containing `pii`, `health`, `financial`. Schema check at A6.
- **Run logs in Loki contain prompt + response.** Loki retention 30 days; metadata-only in `agent_runs` long-term.

### 9.9 Operational

- **Pulse launchd daemon crash-loops.** launchd `KeepAlive: { SuccessfulExit: false, Crashed: true }` + `ThrottleInterval: 30`. After 3 crash-loops in 5 min, daemon stays down with WARN to Wing inbox. *Test: artificial crash on tick #2.*
- **Operator pauses a profile mid-run.** Pause checked at next tick; mid-run cancel via Wing UI button → SIGTERM → runner cleanup.
- **wing.db corruption.** Nightly backup (existing `pazny.backup` framework). Recovery: stop wing+bone+pulse launchd, restore, restart.
- **`hooks/playbook-end.d/*` blocks for >60s.** Callback executor: `subprocess.run(..., timeout=60)`. *Test: hook script `sleep 300`, verify timeout.*
- **Pulse OOM during agent run.** launchd `MemoryLimit` per service (~512MB for pulse); agent run is forked subprocess so OOM-killer takes subprocess, parent restarts.
- **Wing PHP-FPM accepts wrong-host header (host.docker.internal spoof).** Wing checks `X-Forwarded-Host` against allowlist (`wing.<tld>` only); reject otherwise.

### 9.10 Track A reversal specifics

- **Wing volume from old containerized deploy.** Migration recipe extracts `wing.db` from named volume, copies to `~/wing/data/`, then deletes volume. *Test: pre-revert blank with old shape, run revert, verify wing.db preserved.*
- **Bone state.yml mount.** Bone container had `~/.nos/` mounted; new launchd Bone reads same path natively. No data move needed.
- **Existing `state/manifest.yml` rows** for `wing` and `bone` reference old container shape (image, port, healthcheck). Migration A3 rewrites these rows for host-shape (no `image`, no `healthcheck` Docker-style; `health_endpoint: http://host.docker.internal:8099/api/health` for Bone; same pattern for Wing).
- **Decommissioned `wing-nginx` sidecar.** PHP-FPM speaks FastCGI directly to Traefik via the `fastcgi` plugin. Verify Traefik fastcgi support. *If Traefik doesn't support FastCGI directly* (it does as of v3.0), fallback: install nginx via Homebrew on host as the FastCGI proxy listening on host:9001, Traefik routes to host:9001.

### 9.11 Repo reorg specifics

- **CI references moved paths.** Update `.github/workflows/ci.yml` for new module_utils path.
- **`callback_plugins/wing_telemetry.py` references `state/schema/event.schema.json`.** Schema stays where it is (top-level `state/`); callback path unchanged.
- **`module_utils/nos_app_parser.py` is imported by `library/nos_apps_render.py`.** Both move together to `files/anatomy/` (preserving relative import); ansible.cfg points at new dir.
- **Operator's muscle memory.** Update `CLAUDE.md` repo overview section (CRITICAL — operator reads this often). Add a `MOVED.md` at repo root pointing at new locations for ~6 months, then remove.

---

## 10. Notifications + observability

A consolidated section because operator emphasized this in decision #5.

### 10.1 Notification fanout

Three channels, severity-routed per plugin/agent manifest:

| Channel | Use | Implementation |
|---|---|---|
| **Wing /inbox** | Primary, all severities | DB-backed table `wing.db.notifications`; Wing UI displays unread; per-actor read state |
| **ntfy** | Push (severity ≥ high) | HTTP POST to ntfy container `topic=nos-<severity>`; ntfy push to operator phone |
| **Mail (Stalwart)** | Critical + daily digest | SMTP via Stalwart (Track G); template per plugin/agent in manifest |

Manifest declares routing:
```yaml
notification:
  on_critical: [mail, ntfy, wing-inbox]
  on_high: [ntfy, wing-inbox]
  on_medium: [wing-inbox]
  on_low: []                # silently logged only
```

### 10.2 Observability

**All-of-it to Grafana** is the operator constraint.

**Metrics (Prometheus):**
- Pulse: `pulse_ticks_total`, `pulse_jobs_due`, `pulse_jobs_fired_total`, `pulse_jobs_duration_seconds`
- Per-agent: `agent_runs_total{profile,outcome}`, `agent_tokens_used_total{profile}`, `agent_cost_usd_total{profile}`
- Per-plugin: declared in plugin manifest's `observability.metrics` block
- Wing: `wing_api_requests_total{endpoint,status}`, `wing_db_size_bytes`
- Bone: `bone_api_requests_total{endpoint,status}`, `bone_playbook_runs_total{tag,outcome}`

**Logs (Loki):**
- Pulse runs: structured JSON per tick + per job, `service=pulse`, `run_id=<uuid>`, `profile=<name>`
- Agent stdout: tagged `service=agent`, `profile=<name>`, `run_id=<uuid>`
- Plugin runs: tagged `service=plugin`, `plugin=<name>`, `run_id=<uuid>`
- Wing PHP-FPM access log: tagged `service=wing`, parsed by Alloy
- Bone access log: tagged `service=bone`

**Traces (Tempo):**
- Pulse → Bone → ansible-playbook → docker compose: full chain via OTLP propagation
- Plugin run end-to-end: skill → API call → DB write

**Dashboards (Grafana):**
- `dashboards/anatomy/overview.json`: high-level pulse + agent + plugin health
- `dashboards/anatomy/per-agent.json`: agent run rate, success rate, token spend per profile
- `dashboards/anatomy/audit.json`: audit log volume, by actor, by data-category
- Plus per-plugin dashboards from `plugin.yml`'s `observability.dashboard` field

---

## 11. Audit trail + per-agent identity

Operator decision #7: audit trail is non-negotiable.

### 11.1 Schema additions

Every wing.db write table gets three columns:
- `actor_id` — TEXT, FK to authentik client_id (e.g. `nos-conductor`, `nos-plugin-gitleaks`, `nos-wing` for Wing-self writes, `operator` for direct UI writes)
- `actor_action_id` — TEXT (UUID), unique per logical action (a multi-row write has one action_id across all rows)
- `acted_at` — INTEGER (unix ms), set by Wing API at write time

Schema migration `migrations/2026-XX-audit-columns.yml` adds these to existing tables (`events`, `components`, `remediation`, `pentest_targets`, etc.) and to all NEW tables (`pulse_jobs`, `pulse_runs`, `agent_runs`, `gitleaks_findings`, etc.).

### 11.2 The /audit view

Wing UI `/audit` provides:
- **By actor:** every write attributable to a given client_id, time-ordered
- **By data category:** filter to GDPR-relevant data only (e.g. `data_categories includes pii` — but no agent has `pii` scope, so this view is reserved for operator/Wing-self writes)
- **By time range:** classic
- **Forensic export:** CSV or JSON dump for compliance evidence

### 11.3 GDPR Article 30 register

Wing's `/gdpr` view auto-aggregates from:
- Each agent profile's `gdpr:` block (data_categories, processors, retention, legal_basis)
- Each plugin's `gdpr:` block
- The `audit_log` table (actual access counts per processor)

Operator can answer "who accessed which personal datum when" with three clicks: select data_category → select time range → see list of `(actor_id, action_id, acted_at, target)` tuples.

This is the operator's "agentic IT but compliant" thesis as code.

---

## 12. Resolved decisions

All §10 items from the previous draft are resolved (operator 2026-05-01):

| # | Question | Resolved as |
|---|---|---|
| 1 | Wing PHP source strategy | **B (submodule)** with `cp+jinja` rendering — Wing self-update writes back to submodule on operator approval |
| 2 | Compose project name | **N/A — no compose project** under all-local architecture; everything is launchd daemons |
| 3 | Local model timing | runtime.command pluggable per profile; default `claude`, swap when hardware permits, no hard date |
| 4 | Five profiles or four | **One** in PoC (conductor); inspektor + librarian + scout post-PoC, each ~2-4h |
| 5 | Approval inbox channel | **Wing /inbox primary; mail (Stalwart) for critical; ntfy for push; everything in Grafana** |
| 6 | FOSS tool order | **gitleaks first (only)** as PoC; trivy/grype/syft/nuclei/lynis/testssl/osquery as separate plugin commits post-PoC |
| 7 | GDPR processor list with Anthropic | **Yes, transparent and accurate**; per-actor identity foundation underpins audit trail |
| 8 | Architecture | **Local PHP-FPM via Homebrew + Python launchd daemons** (Variant L, full local) |
| 9 | Repo reorg | **`files/anatomy/` umbrella** — moves `migrations/`, `library/`, `module_utils/`, `patches/`, framework-internal `docs/`; top-level `state/manifest.yml` and `callback_plugins/` retained per Ansible convention |
| 10 | Roles location | **`/roles/pazny.{wing,bone,pulse,backup}/` thin role wrappers** stay in `/roles/` per Ansible convention; actual code lives in `files/anatomy/<sub>/` |

---

## 13. In scope: PoC + Track Q follow-on (this plan)

PoC ships the doctrine proof (A6.5: thin Grafana + grafana-base service plugin). Track Q applies the same recipe to every other Tier-1 role; see §13.1 for the seven-batch plan.

### 13.0 Out of scope (this plan)

- **Hermes integration** — Q3 follow-up after Hermes is audited (could become a Track O / P).
- **Multi-tenant agent profiles** — every operator/tenant runs their own pulse. No shared agent suite across tenants.
- **Custom local-LLM serving infra** — runtime is command-pluggable; spinning up a local model server is operator's choice.
- **Agent-authored Ansible roles** — agents draft migration recipes (after PoC); they do NOT author new Tier-1 roles.
- **Cross-host coordination** — pulse on host-A doesn't talk to pulse on host-B. Multi-host fleet mode is Track F territory.
- **CI integration of agent runs** — running scout/inspektor in CI on every PR is conceivable but expensive; revisit Q3.
- **Agent-driven incident auto-remediation** — agents observe, plan, draft. They don't auto-execute mitigations. Approval gate is non-negotiable.
- **A second scheduler runtime** (Temporal, Airflow) — pulse is a deliberately small APScheduler-style daemon. Larger workflow orchestration is a separate evaluation if ever needed.
- **Migrating `state/manifest.yml` itself into `files/anatomy/`** — manifest is the platform service catalog, referenced by Traefik, smoke tests, GDPR inventories. Stays top-level.
- **Tier-2 apps moving into anatomy** — `apps/<name>.yml` manifests stay where they are. Only platform-control-plane code moves to anatomy.

### 13.1 Track Q — autowiring debt consolidation (first-class follow-on, post-PoC)

**Status (2026-05-03):** promoted from "future candidate" to **first-class architectural follow-on** per §1.1 doctrine. Track Q is the realization of the "tendons & vessels" promise: every Tier-1 role gets thinned to install-only; all wiring lives in service + composition plugins under `files/anatomy/plugins/`.

The PoC ships the doctrine proof (A6.5: thin `pazny.grafana` + `grafana-base` service plugin). Track Q applies the same recipe to the rest of the body.

**Concrete batches (post-PoC, each ~3-5 days):**

| Phase | Batch | Roles thinned | Plugins added | Why this order |
|---|---|---|---|---|
| **Q1** | observability | `pazny.alloy`, `pazny.prometheus`, `pazny.loki`, `pazny.tempo` | `alloy-scrape`, `prometheus-base`, `loki-base`, `tempo-base`, plus 8-12 composition plugins (`grafana-prometheus`, `grafana-loki`, `grafana-tempo`, `alloy-host-metrics`, `alloy-docker-metrics`, `alloy-syslog`, ...) | observability is the densest wiring surface today; biggest LOC reduction; lowest blast radius (no user data) |
| **Q2** | IAM + secrets | `pazny.authentik`, `pazny.infisical`, `pazny.vaultwarden` | `authentik-base`, `infisical-base`, plus per-Tier-1 composition plugins for OIDC bindings (`authentik-grafana`, `authentik-outline`, `authentik-nextcloud`, …) — replaces today's central `authentik_oidc_apps` list | every other plugin depends on IAM; do this second so subsequent batches have stable plugin contracts |
| **Q3** | storage + DB | `pazny.mariadb`, `pazny.postgres`, `pazny.redis`, `pazny.rustfs` | `mariadb-base`, `postgres-base`, `redis-base`, `rustfs-base`, plus DB-binding compositions (`postgres-outline`, `mariadb-nextcloud`, `redis-authentik`, ...) replacing the central `tasks/stacks/core-up.yml` DB-init block | DB init is currently in `tasks/stacks/core-up.yml`; moving each to its consumer plugin localizes blast radius |
| **Q4** | comms | `pazny.smtp_stalwart`, `pazny.ntfy`, `pazny.mailpit` | `smtp-stalwart-base`, `ntfy-base`, `mailpit-dev-relay`, plus per-service notifier compositions | depends on Q1+Q2 (notifications need observability + identity) |
| **Q5** | content | `pazny.nextcloud`, `pazny.outline`, `pazny.bookstack`, `pazny.hedgedoc`, `pazny.wordpress`, `pazny.calibre_web`, `pazny.kiwix`, `pazny.jellyfin` | one base plugin per role, plus cross-content compositions (e.g. `outline-onlyoffice`, `nextcloud-onlyoffice`) | tenant-data services last; most blast-radius |
| **Q6** | dev/CI | `pazny.gitea`, `pazny.gitlab`, `pazny.woodpecker`, `pazny.code_server`, `pazny.paperclip` | base + composition plugins | parallel to Q5 if needed |
| **Q7** | misc + sweep | everything else (`pazny.uptime_kuma`, `pazny.home_assistant`, `pazny.n8n`, `pazny.node_red`, `pazny.miniflux`, `pazny.openwebui`, `pazny.firefly_iii`, `pazny.erpnext`, `pazny.freescout`, `pazny.metabase`, `pazny.superset`, `pazny.influxdb`, `pazny.qgis_server`, `pazny.freepbx`) + cleanup of any `tasks/post.yml` shells left over | base plugins per role | tail; low-density wiring per service |

**Per-batch checklist (deterministic, drawn from A6.5 recipe):**
1. Inventory wiring: `grep -rn "<service>" tasks/ default.config.yml roles/pazny.alloy/ templates/traefik/`
2. Create `files/anatomy/plugins/<service>-base/plugin.yml` with `requires.role: pazny.<service>`
3. Move dashboards, OIDC blocks, scrape entries, alert rules, notifier templates, schema migrations into the plugin
4. Strip role: delete `tasks/post.yml`, drop service-specific entries from `default.config.yml`, prune unused defaults
5. Run blank with the thinned role → verify byte-identical functional behavior (dashboards visible, OIDC works, scrape green, alerts firing as before)
6. Commit `feat(anatomy): thin pazny.<service> + extract <service>-base plugin (Q<N>)`

**Track Q exit criteria:**
- Every Tier-1 role under `roles/pazny.<service>/` has shape: `defaults/`, `tasks/main.yml` (data dir + compose render only), `templates/compose.yml.j2`, `meta/`. **No `tasks/post.yml` anywhere** unless the post-step is genuinely service-internal (e.g. database `pgcrypto` extension on first install).
- `default.config.yml` has zero per-service OIDC blocks (`authentik_oidc_apps` becomes a derived view from plugins).
- `tasks/stacks/core-up.yml` + `stack-up.yml` lose their DB-init + post-start blocks — replaced by plugin loader's own ordering.
- `roles/pazny.alloy/templates/scrape-config.yml.j2` becomes a Jinja loop over discovered plugin scrape entries, not a hardcoded list.
- Net LOC delta expected: **-2000 to -3500** (rough estimate; will refresh after Q1 actuals).

**Estimate:** 4-6 weeks total post-PoC, batched. Each batch is independently shippable; Q can pause mid-track without breaking anything.

**Gate to start Q1:** PoC A6.5 exits green — i.e., the doctrine is proven on Grafana before generalization.

---

## 14. Glossary

- **bones & wings** — operator-facing product name for the unified Wing + Bone + Pulse + Plugins platform.
- **anatomy** — internal/path-form name. Sources live in `files/anatomy/`. Ansible role: `pazny.anatomy`.
- **wing** — UI + read model + REST API (Nette PHP-FPM, local launchd via Homebrew).
- **bone** — operational API + playbook dispatch (FastAPI Python, local launchd).
- **pulse** (or **nos-pulse**) — local Python launchd daemon scheduling agentic and non-agentic jobs.
- **plugin** — directory under `files/anatomy/plugins/<name>/` with `plugin.yml`. The unit of **anatomy auto-wiring**, not the service itself. Auto-wires on `--tags anatomy.plugins`. Three types (§6.2):
  - **skill plugin** — pure capability addition, no service install (or just a brew binary). Example: gitleaks. **PoC ships this type only.**
  - **service plugin** — wraps an existing role/apps with complete autowiring spec (anatomy + infra + observability). Example: grafana base. Post-PoC.
  - **composition plugin** — cross-service wiring; activates only when ALL declared services are installed. Example: grafana-spacetimedb. Post-PoC.
- **autowiring** — the integration code that connects a service to anatomy/infra/observability subsystems. Today scattered across role-internal `tasks/post.yml` and adjacent surfaces; **plugin manifests are its permanent home** post-PoC.
- **tendons & vessels** (operator framing 2026-05-03, §1.1) — the autowiring layer made explicit. **Tendons:** plugin manifests connecting roles to anatomy (Wing UI, Pulse, audit, GDPR). **Vessels:** plugin manifests connecting roles to infra/observability (DB, Prometheus, Loki, Grafana, OIDC, notifiers). Both are **modular and removable**; the role they wire knows nothing about them. **Synapses** (composition plugins) fire only when multiple services co-exist.
- **thin role doctrine** (§1.1) — every Tier-1 `roles/pazny.<service>/` post-Track-Q contains ONLY `defaults/`, `tasks/main.yml` (data dir + compose render), `templates/compose.yml.j2`, `meta/`. No `tasks/post.yml`. No cross-service knowledge. Adding a new service = role + plugin (two files).
- **Track Q** (first-class follow-on, post-PoC) — autowiring debt consolidation: migrate scattered integration code from role internals into service + composition plugins. 4-6 weeks batched (Q1-Q7). Gate: A6.5 doctrine proof on Grafana exits green. See §13.1.
- **agent profile** — `files/anatomy/agents/<name>/profile.yml` declaring schedule, runtime, scopes, prompt path, skills, GDPR.
- **skill** — reusable capability under `files/anatomy/skills/<name>/`. Importable by agent profiles and plugins.
- **contract** — committed schema artifact under `files/anatomy/skills/contracts/`: `wing.openapi.yml`, `bone.openapi.yml`, `wing.db-schema.sql`. Single source of truth.
- **conductor** — primary agent profile (PoC scope). T2, every 4h. Runs `--check`, reports drift, applies approved upgrades/migrations.
- **inspektor / librarian / scout** — post-PoC profiles. Each ~2-4h work after PoC ships.
- **non-agentic job** — scheduled task that doesn't talk to an LLM (registry refresh, GDPR digest, retention sweep, gitleaks scan).
- **per-actor identity** — every agent + every plugin has its own Authentik OIDC client (e.g. `nos-conductor`, `nos-plugin-gitleaks`). Audit trail tags every write with actor_id.
- **approval inbox** — Wing UI `/inbox` view; primary surface for pending plans/upgrade-drafts/patch-drafts/critical-findings.
- **Variant L** (architecture) — full-local: Wing PHP-FPM + Bone Python + Pulse Python all as launchd daemons. **Decision: L.**

---

## Appendix A — Why this is one document, not three

The roadmap currently has three Track sections (K, L, M). Consolidated here because:

1. **The naming is shared.** "bones & wings" / "anatomy" is the mental object; K/L/M phases of the same refactor.
2. **The cross-cutting concerns are dense.** §9 edge cases cite all phases — one home avoids triplication.
3. **Operator's framing 2026-05-01** explicitly described it as "jeden ucelený systém" — one cohesive system.

The roadmap will be updated to point at this document. Original K/L/M phase IDs are obsolete; new phases A0-A10 in §8 are the current breakdown.

---

## Appendix B — Implementation tracking

When implementation starts, this section becomes a live tracker:

- Per-phase status (NOT STARTED / IN PROGRESS / DONE / BLOCKED)
- Commit references
- Open issues

For now, every phase row is `NOT STARTED`. The first commit to touch this section will replace this placeholder with a status table.

---

*Last revision: 2026-05-01 — second draft, all 7 architectural decisions resolved with operator. Awaiting Track G completion before phase A0 code-touch.*
