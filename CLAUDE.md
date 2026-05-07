# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**nOS** — Ansible playbook that automates a macOS development environment on Apple Silicon (M1+). A complete self-hosted **Agentic Home Lab** with ~46 Docker services organized into 59 Ansible roles under the `pazny.*` namespace, SSO (Authentik), secrets vault (Infisical), a web desktop (Puter), an AI agent (OpenClaw + Ollama MLX), observability (LGTM stack + InfluxDB), nightly backup to RustFS, and Tailscale remote access. Every service is FOSS; all data stays local. Fully replicable — `blank=true` wipes everything and reinstalls from scratch.

`nOS` is the open-source reference implementation behind [**This is AIT — Agentic IT**](https://thisisait.eu). Forked from geerlingguy/mac-dev-playbook → roles renamed under the `pazny.*` namespace.

## Git Workflow

**Development happens on `master`.** The `dev` branch was retired 2026-04-16. Short-lived `feat/*` / `fix/*` branches branch off `master` and merge back via fast-forward or PR. Create worktrees on top of `master`. Never resurrect `dev`.

## Commit Convention

- Format: **Conventional Commits** (`feat:`, `fix:`, `refactor:`, `docs:`, `chore:`, etc.)
- **No Co-Authored-By, no `--author` flag, no author-name override.** Git populates the author from `git config` automatically.
- Commit messages: concise, English, imperative. Body optional.

## Vision

An OS-agnostic "all-in-one PC" under the brand **This is AIT** (working engine name **nOS**, website [thisisait.eu](https://thisisait.eu)). All logic and data run on replicable self-hosted FOSS technologies. The Ansible playbook is the single source of truth. OpenClaw is the autonomous DevOps agent.

## Key Commands

```bash
# Full playbook run (prompts for sudo + password prefix)
ansible-playbook main.yml -K

# Clean reinstall (wipes data, resets all services, prompts for a new password prefix)
ansible-playbook main.yml -K -e blank=true

# Run a specific component by tag
ansible-playbook main.yml -K --tags "stacks,nginx"
ansible-playbook main.yml -K --tags "observability"
ansible-playbook main.yml -K --tags "ssh,iiab-terminal"

# Syntax validation
ansible-playbook main.yml --syntax-check
```

## Architecture

### Anatomy — the structural backbone

> **Doctrine source:** `docs/bones-and-wings-refactor.md` §1.1 + §6.

The core of nOS is the **anatomy** — a layered metaphor for how the platform is wired:

- **Bones** (`files/anatomy/bone/`) — Bone, the local FastAPI bridge between Ansible runs and Wing's SQLite store.
- **Wings** (`files/anatomy/wing/`) — Wing, the Nette PHP security-research dashboard + state-framework UI.
- **Pulse** (`files/anatomy/pulse/`) — Pulse daemon, the host-side scheduled-job runner.
- **Veins** (carriers) — Bone↔Wing HTTP, callback telemetry, plugin-loader hook channels.
- **Tendons** (cross-service wiring) — what each plugin's `lifecycle:` block declares (renders, dashboard provisioning, post-API setup).
- **Nerves** *(TBD)* — agentic feedback loops: A8 conductor → Pulse jobs → A10 audit trail.

When working within the anatomy use **surgeon-like commit messages**: name the exact tendon / vein / bone touched, the symptom that surfaced the issue, the structural change that closes it, and the test that pins it. See P0.x commit series (`12a7828..ca26bd7`) for examples.

### Role-based service delivery (59 roles under `pazny.*`)

Every Docker service is owned by an Ansible role in `roles/pazny.<service>/`. Each role follows the **compose-override pattern**:

```
roles/pazny.<service>/
  defaults/main.yml         # version, port, data_dir, mem_limit defaults
  tasks/main.yml            # data dir + compose-override render
  tasks/post.yml            # (optional) post-start API calls, DB setup, admin init
  templates/compose.yml.j2  # Docker Compose service fragment (no top-level networks:)
  handlers/main.yml         # (optional) service-specific restart handler
  meta/main.yml             # role metadata
```

**Compose-override merge:** each role renders `templates/compose.yml.j2` into `{{ stacks_dir }}/<stack>/overrides/<service>.yml`. Orchestrators (`core-up.yml`, `stack-up.yml`) use `ansible.builtin.find` to discover override files and pass them as `-f` flags to `docker compose up`. Base stack templates declare only `services: {}` + networks — the real service definitions come from role overrides.

**Role invocation with tag inheritance:** `include_role` needs both `apply: { tags: [...] }` **and** `tags: [...]` on the task itself so CLI `--tags` filtering actually reaches the inner role tasks.

**Non-Docker roles** (wing, openclaw, iiab_terminal, bone, hermes, opencode, backup, state_manager, dotfiles, `mac.*`): wired via `import_role` in `main.yml` — these install directly on the host, not through Docker Compose.

### Configuration layering (later overrides earlier)

1. **`default.config.yml`** — every variable with a default (committed)
2. **`default.credentials.yml`** — every secret as a `{{ global_password_prefix }}_pw_*` template (committed)
3. **`config.yml`** — your feature-toggle overrides (gitignored)
4. **`credentials.yml`** — your secret overrides (gitignored)

Passwords follow the pattern `{global_password_prefix}_pw_{service}`. A blank run prompts for the prefix. Ansible `vars_files` precedence outranks role `defaults/main.yml`.

### Playbook execution flow (`main.yml`)

1. **Password-prefix prompt** (when `blank=true`)
2. **Blank reset** — wipes Docker state, data dirs, and configs. Honors external-storage overrides via `tasks/stacks/external-paths.yml`, so data on `/Volumes/SSD1TB/` gets wiped rather than the empty `~/service` fallbacks.
3. **Auto-enable dependencies** — flips on PostgreSQL, Redis, MariaDB based on which `install_*` flags are set.
4. **Auto-generate secrets** — Outline, Bluesky, Authentik, Infisical, Vaultwarden, Paperclip.
5. **Host roles:** `osx-command-line-tools` → `pazny.mac.homebrew` → `pazny.dotfiles` → `pazny.mac.mas` → `pazny.mac.dock`.
6. **Host tasks:** macOS system prefs → SSH / IIAB Terminal → language runtimes → Nginx → external storage.
7. **`tasks/stacks/core-up.yml`** — `infra` + `observability` stacks (always first):
   - Role renders (compose-override templates)
   - `docker compose up infra --wait` + `docker compose up observability --wait`
   - DB setup (MariaDB databases, PostgreSQL databases + `pgcrypto`)
   - Post-start roles: Authentik blueprints + OIDC, Infisical init, Bluesky PDS, Portainer admin + OAuth.
8. **Service configs:** Nginx vhosts, data dirs, Alloy scrape targets, observability dashboards.
9. **`tasks/stacks/stack-up.yml`** — the remaining stacks (`iiab`, `devops`, `b2b`, `voip`, `engineering`, `data`):
   - Role renders
   - Loop: `docker compose up <stack> --wait` per stack
   - Post-start roles: admin init, OIDC configuration, DB migrations, onboarding
   - Authentik service-side OIDC setup, Bluesky PDS bridge.
10. **Post-provision:** stack-health verification → service registry.

**Key invariant:** infra + observability are **always required, always first**. Post-start tasks can assume MariaDB, PostgreSQL, Authentik, Infisical, Grafana, Loki, and Tempo are online.

### Docker stacks (8 compose projects in `~/stacks/`)

| Stack | Services (each owned by a `pazny.*` role) |
|-------|------|
| **infra** | MariaDB, PostgreSQL, Redis, Portainer, Traefik, Bluesky PDS, Authentik (server + worker), Infisical |
| **observability** | Grafana, Prometheus, Loki, Tempo |
| **iiab** | WordPress, Nextcloud, n8n, Node-RED, Kiwix, offline maps, Jellyfin, Open WebUI, MCP Gateway (mcpo), Uptime Kuma, Calibre-Web, Home Assistant, RustFS, Puter, Vaultwarden, ntfy, Miniflux |
| **devops** | Gitea, Woodpecker CI, GitLab, Paperclip, code-server |
| **b2b** | ERPNext, FreeScout, Outline, HedgeDoc, BookStack, Firefly III, OnlyOffice |
| **voip** | FreePBX (Asterisk) |
| **engineering** | QGIS Server |
| **data** | Metabase, Apache Superset, InfluxDB |

### Non-Docker applications

- **OpenClaw** — AI agent daemon via launchd, Ollama 0.19+ with the MLX backend
- **Hermes** — cross-channel messaging gateway
- **OpenCode** — agentic coding helper
- **IIAB Terminal** — Python Textual TUI, SSH `ForceCommand` for the `home` user
- **Wing** — security-research dashboard; source at `files/anatomy/wing/`, host launchd as of anatomy A3.5 (FrankenPHP single binary)
- **Bone** — local REST API bridge; source at `files/anatomy/bone/`, host launchd as of anatomy A3a
- **Pulse** — scheduled-job daemon; source at `files/anatomy/pulse/`, host launchd skeleton as of anatomy A4

### IAM & SSO (Authentik)

Central SSO via Authentik at `auth.<tld>` (default `auth.dev.local`). OIDC providers + applications are generated from per-plugin `authentik:` blocks in `files/anatomy/plugins/<svc>-base/plugin.yml`, harvested by `authentik-base`'s aggregator into `inputs.clients` and rendered into the live Authentik blueprint by the plugin loader (D1.2/D1.3 cutover, 2026-05-05). The legacy central `authentik_oidc_apps` list in `default.config.yml` was retired in D1.3 — only the empty stub survives as the Tier-2 apps_runner extension channel.

**β1.A (2026-05-05) doctrine — three SSO buckets, not two:**

- **`native_oidc`** — service consumes OIDC at app level. Operator clicks "Sign in with Authentik" inside the service. Per-user identity flows into the service.
  - **env-driven:** Grafana, Outline, Open WebUI, n8n, GitLab (omniauth), Vaultwarden, WordPress, FreeScout, Infisical, Miniflux, HedgeDoc, BookStack, Node-RED (β1.B passport-openidconnect)
  - **file/API-driven:** Gitea (Admin API), Nextcloud (`occ`), Portainer (`PUT /api/settings`), ERPNext (Frappe Social Login Key via bench), Home Assistant (auth_oidc HACS plugin), Jellyfin (SSO-Auth server plugin), Superset (`OAUTH_PROVIDERS` in superset_config.py)

- **`header_oidc`** — Authentik proxy outpost forwards `Remote-User` / `Remote-Email` headers; service auto-creates the local user from headers. True SSO from the user POV (no service-side login screen) but no per-app OIDC client.
  - Firefly III (β1.A 2026-05-05)

- **`forward_auth`** — pure access gate. Authentik session = "you're in"; service has no per-user state. Same Authentik provider object as header_oidc.
  - Uptime Kuma, Calibre-Web, Kiwix, Paperclip, Puter, Wing, code-server, ntfy, InfluxDB (OSS), ONLYOFFICE, Mailpit, Metabase, SpacetimeDB

- **No SSO:** FreePBX, QGIS
- **AT Protocol identity:** Bluesky PDS (the Authentik→PDS bridge auto-provisions `@user.bsky.<tld>` accounts)

The trichotomy makes the runtime semantics legible: native_oidc and header_oidc both grant true SSO with per-user identity; forward_auth is access control without per-user state. See `docs/native-sso-survey.md` for the full audit (verdicts, costs, edge cases) and `docs/upstream-pr-opportunities.md` for the FOSS contributions that would let nOS flip individual forward_auth services to native_oidc (rather than maintaining local sidecars / forks / hacks).

Cookie domain `.<tld>` enables cross-subdomain session sharing. Embedded outpost binds to every `header_oidc` + `forward_auth` provider via the `10-oidc-apps.yaml` blueprint render. The `authentik_app_tiers` map in `default.config.yml` survives as the per-slug → RBAC tier override; per-plugin `authentik.tier` is the new source of truth.

### RBAC (role-based access control)

Four access tiers bound to Authentik groups via expression policies (`authentik_rbac_tiers` + `authentik_app_tiers` in `default.config.yml`):
- **Tier 1 (admin):** Portainer, Infisical, Grafana — `nos-providers`, `nos-admins`
- **Tier 2 (manager):** Gitea, GitLab, n8n, Superset, Metabase, Paperclip, ERPNext, FreeScout — + `nos-managers`
- **Tier 3 (user):** Nextcloud, Outline, Open WebUI, Puter, Vaultwarden, Uptime Kuma, Calibre-Web, Home Assistant — + `nos-users`
- **Tier 4 (guest):** Kiwix, Jellyfin, WordPress — + `nos-guests`

Group names are configurable via `authentik_rbac_tiers`. Legacy installs provisioned before 2026-04-22 carry the old `devboxnos-*` prefix — migrate by updating group names in Authentik, or run `blank=true` to regenerate.

### Secrets management

- **Infisical CE** (`vault.dev.local`) — central vault for infra secrets, REST API + CLI
- **Vaultwarden** (`pass.dev.local`) — Bitwarden-compatible personal vault for tenants

### Observability (Apple Silicon optimized)

- **Metrics:** Grafana Alloy (`prometheus.exporter.unix`, ARM64-safe) → Prometheus
- **Logs:** Alloy tails Nginx / PHP / agent logs → Loki
- **Traces:** OTLP receiver (gRPC `:4317`, HTTP `:4318`) → Tempo

### State & Migration Framework

Declarative state and safe transitions for long-lived installs. Four surfaces:

- **State** — `state/manifest.yml` (committed, expected shape) vs. `~/.nos/state.yml` (runtime, generated per run by `pazny.state_manager`). Merged, never overwritten. `~/.nos/` is the runtime side-car — delete it and the next run regenerates.
- **Migrations** — one-shot global transitions (rename `devboxnos-*` → `nos-*`, move state dirs, rewrite identifiers) in `files/anatomy/migrations/<ISO-date>-<slug>.yml` (moved from `/migrations/` in 2026-05-03 anatomy A1). Ran automatically in `pre_tasks`. Idempotent: each step has `detect` / `action` / `verify` / `rollback`. Breaking migrations prompt for confirmation unless `-e auto_migrate=true`.
- **Upgrade recipes** — per-service version transitions in `upgrades/<service>.yml`. `pre` / `apply` / `post` / `rollback` phases. Invoked explicitly (`--tags upgrade -e upgrade_service=<svc>`) or via Wing. Covers breaking patterns like `pg_upgrade`, `mariadb-upgrade`, Grafana dashboard-preserving bumps.
- **Coexistence** — dual-version operation via `nos_coexistence` module. Provision a second track on a shifted port with cloned data, test, cut over via atomic Nginx reload, clean up after TTL. Supported: Grafana, Postgres, MariaDB, Authentik (special), Gitea, Nextcloud, WordPress.

Observability: a callback plugin (`callback_plugins/wing_telemetry.py`) emits structured events for every task + framework action to Bone → Wing SQLite (with `~/.nos/events.jsonl` fallback). Wing exposes `/migrations`, `/upgrades`, `/timeline`, `/coexistence` views. Custom Ansible modules: `files/anatomy/library/nos_state.py`, `nos_migrate.py`, `nos_authentik.py`, `nos_coexistence.py` (moved from `/library/` in 2026-05-03 anatomy A1; `ansible.cfg` declares the new path).

Authoring: see [files/anatomy/docs/framework-overview.md](files/anatomy/docs/framework-overview.md), [files/anatomy/docs/migration-authoring.md](files/anatomy/docs/migration-authoring.md), [files/anatomy/docs/upgrade-recipes.md](files/anatomy/docs/upgrade-recipes.md), [files/anatomy/docs/coexistence-playbook.md](files/anatomy/docs/coexistence-playbook.md), [files/anatomy/docs/wing-integration.md](files/anatomy/docs/wing-integration.md). Authoritative spec: [files/anatomy/docs/framework-plan.md](files/anatomy/docs/framework-plan.md). (All these were moved from `/docs/` to `files/anatomy/docs/` in anatomy A1 per the operator-runbook-vs-agent-contract split rule — `docs/bones-and-wings-refactor.md` §4.2.)

### Reverse proxy: Traefik (primary) + host nginx (opt-in fallback)

Traefik in a container is the default edge proxy as of C1 (2026-04-29). It binds 80/443 unconditionally and serves both Tier-1 and Tier-2 services through two providers:

- **File provider** — `traefik_dynamic_dir/services.yml` is auto-derived from `state/manifest.yml`. Every Tier-1 service with `domain_var` + `port_var` set in the manifest gets a router + service block. No per-role edits — one central YAML.
- **Docker provider** — Tier-2 apps in the `apps` compose stack emit Traefik labels in their compose service block. The runner (`files/anatomy/library/nos_apps_render.py`) auto-generates the labels from the manifest.

Authentik forward-auth is a file-provider middleware (`authentik@file`), applied via Tier-1 routers' `middlewares=` field or Tier-2 labels. TLS reads the same cert path nginx used (`{{ tls_cert_path }}` / `{{ tls_key_path }}`) — mkcert wildcards or LE wildcards Just Work.

`install_nginx: false` is the default. Host nginx remains as an opt-in fallback (`install_nginx: true`) for operators with bespoke vhost-level constraints — `tasks/nginx.yml` is fully gated behind the flag. Nginx vhost templates remain in `templates/nginx/sites-available/` for that path.

Authoritative guide: [docs/traefik-primary-proxy.md](docs/traefik-primary-proxy.md).

### Tier-2 apps_runner (manifest-driven onboarding)

For long-tail self-hosted apps that don't merit a full `pazny.<name>` role, drop a YAML manifest at `apps/<name>.yml` and re-run the playbook. `pazny.apps_runner` discovers manifests, validates them (via `files/anatomy/module_utils/nos_app_parser` — schema + GDPR Article 30 + TLS / SSO / EU-residency gates), resolves magic tokens, renders a single merged compose override, brings the apps stack up, and fires post-hooks (service-registry append, Wing systems ingest, Authentik blueprint reconverge, Bone HMAC `app.deployed` events, Portainer endpoint reg, Kuma monitor extension, GDPR upsert via Wing CLI, smoke catalog runtime extension).

GDPR enforcement is **mandatory** — the parser refuses any manifest without a complete `gdpr:` block (purpose, legal_basis enum, data categories, data subjects, retention horizon, processors, EU-residency flag). This is by design: GDPR Article 30 compliance is part of the deploy gate, not an afterthought.

Coolify (Apache-2.0) maintains ~280 compose templates that we can import via `tools/import-coolify-template.py` (rewrites their `${SERVICE_*}` token syntax to ours, scaffolds the `gdpr:` block with `TODO` sentinels the operator must fill in before the parser will accept the file).

Authoritative guides: [docs/tier2-app-onboarding.md](docs/tier2-app-onboarding.md), [docs/coolify-import.md](docs/coolify-import.md).

### Adding a new Docker service (Tier-1)

**Current pre-Track-Q workflow.** After bones & wings A6.5 + Track Q, the target workflow becomes thin role + `files/anatomy/plugins/<service>-base/plugin.yml`; see `docs/bones-and-wings-refactor.md` §1.1/§13.1 and `files/anatomy/docs/role-thinning-recipe.md`.

1. Create a role `roles/pazny.<service>/` following the compose-override pattern above.
2. Add an `include_role` call in the right orchestrator (`core-up.yml` or `stack-up.yml`) — remember both `apply: { tags: [...] }` **and** `tags: [...]` so `--tags` filtering works.
3. Add an `install_<service>` toggle in `default.config.yml`.
4. Add a row to `state/manifest.yml` with `domain_var` + `port_var` so Traefik file-provider auto-routes it.
5. (Optional, pre-Q only) Add an OIDC entry in `authentik_oidc_apps` + env vars in the compose template. Do not use this pattern for roles already migrated to plugin-based autowiring.

### Adding a new Docker service (Tier-2 — manifest-driven)

```bash
cp apps/_template.yml apps/myapp.yml
$EDITOR apps/myapp.yml          # fill meta + gdpr + compose blocks
python3 -m module_utils.nos_app_parser apps/myapp.yml   # smoke-parse
ansible-playbook main.yml -K
```

No code changes. The runner takes care of routing, secrets, and observability.

### Feature-toggle pattern

~78 `install_*` / `configure_*` boolean variables. `when:` conditions + tags for CLI filtering.

## Linting Rules

- **yamllint:** max line length 180 (warning)
- **ansible-lint:** skips `schema[meta]`, `role-name`, `fqcn`, `name[missing]`, `no-changed-when`, `risky-file-permissions`, `yaml`

## Lockfile discipline

**`composer.json` and `composer.lock` are always in sync. Same for any future Python lock (Pulse / Bone).**

Editing `files/anatomy/wing/composer.json` directly without running `composer update` ships a broken commit — the playbook's `pazny.wing/tasks/main.yml` task `[pazny.wing] Run composer install` exits 4 with a cryptic *"lock file is not up to date"* trace deep in a blank run. Two gates catch this BEFORE the playbook does:

1. **Pytest gate** — `tests/anatomy/test_lockfile_sync.py` runs `composer validate --strict --no-check-publish` against the wing tree. CI runs it on every PR/push (composer is installed in the `pytest` job). Local: `python3 -m pytest tests/anatomy/test_lockfile_sync.py`.
2. **Operator-side pre-flight** — `pazny.wing/tasks/main.yml` runs the same `composer validate` *immediately before* the install task. If lock is stale, the playbook fails at the validate step with a clear diagnosis.

Adding a Wing dep:

```bash
cd files/anatomy/wing
composer require <package> --no-install   # updates BOTH composer.json + composer.lock
git add composer.json composer.lock
```

Or for a manual edit you already made:

```bash
cd files/anatomy/wing
composer update <package> --no-install     # regenerates lock entry only
git add composer.lock
```

Never edit `composer.json` and commit without `composer.lock` updates. Same principle applies to any future `pyproject.toml` / `requirements.lock` for Pulse + Bone — when those gain explicit lock files, mirror these gates.

## Known Tech Debt

`README.md`, `TLDR.md`, inline comments, and task names are in **English**. The Czech-language legacy has been retired as part of the `nOS` rebrand. If you find residual Czech strings, translate them.

## Apple Silicon Constraints

- Target: ARM64 only (M1+). `homebrew_prefix: /opt/homebrew`.
- Ollama 0.19+: native MLX backend (57% faster prefill, 93% faster decode).
- Docker Desktop for Mac (not Colima / Lima).

## Known Tech Debt

- **ansible-core 2.24 jump (future):** Track J Phase 4 (commit `85b933b`) migrated `ansible_env` → `ansible_facts['env']` (9 occurrences); Track H Phases 1-6 (commits `6767e56..23d970b`) pinned the rest of the surface to 2.20 and verified forward-compat under 2.21.0rc1 (sandbox install, syntax + tests + ansible-lint production profile all clean). When upstream ships 2.24 stable, the actual upgrade is a single `requirements.yml` floor bump + collection version review + 1 blank — ~4 hours, not a Track. Floor today: ansible-core 2.20.5 (operator + CI matrix).
- Mattermost removed (no ARM64 FOSS image); config retained for the future.
- ERPNext migration occasionally fails on the first blank run (auto-retry implemented in `erpnext_post.yml`).
- Jellyfin / Open WebUI: known upstream bugs on fresh DB init — first run may restart-loop until data regenerates.
- Bluesky PDS federation not yet functional (the identity bridge creates accounts, but AT Protocol federation requires public DNS).
- Pre-2026-04-22 installs carry legacy `devboxnos-*` Authentik group names, `com.devboxnos.*` launchd bundle IDs, and the `~/.devboxnos/` state directory. Rebrand complete in-repo; migration on existing hosts needs a blank reset (or manual rename of the Authentik groups + `launchctl bootout` of the old plists).
- **Anatomy A3.5 — Wing host-revert ✅ DONE 2026-05-04:** Wing now runs as `eu.thisisait.nos.wing` launchd daemon backed by FrankenPHP (PHP 8.5 + Caddy 2.x in one binary). The wing FPM container + wing-nginx sidecar pair are gone. Traefik file-provider auto-derives `wing.<tld>` → `http://nos-host:9000` via the uniform host-mode code path. Closes the wing-nginx stale-IP 502 bug class structurally. FrankenPHP installed via Homebrew taps (`dunglas/frankenphp` + `shivammathur/php` for the php-zts dep). Composer + DB init now run host-native — `wing-cli` profile service retired.
- **Track Q autowiring debt** — **Q1+Q2 + D1 (central retirement) DONE 2026-05-05**. Phase 1 multi-agent batch shipped 33 plugins (Q1b composition + Q2 native_oidc/forward_auth). D1 series (2026-05-05) closed the central `authentik_oidc_apps` refactor: D1.0 fixed 4 mode mis-classifications (erpnext/HA/jellyfin/superset → native_oidc), β1.A added the `header_oidc` doctrine bucket + reclassified firefly, β1.B implemented true native OIDC for Node-RED via passport-openidconnect (first non-trivial native SSO upgrade — formerly forward_auth-only), β1.C/D documented metabase OSS limitation + roadmap for upstream PRs (`docs/upstream-pr-opportunities.md`), D1.1 added spacetimedb-base stub closing the last C1 blocker, D1.2 extended `run_aggregators` with template_vars (Jinja pre-render + feature_flag gating) and switched the 10-oidc-apps + 20-rbac-policies blueprints to iterate `inputs.clients`, D1.3 retired the 35-row central list (only an empty stub remains as Tier-2 apps_runner channel). Aggregator dry-run (`tools/aggregator-dry-run.py`) gates the cutover with 0 field-diffs. Tier-1 SSO source-of-truth = per-plugin authentik: blocks. **D2 next:** delete duplicate role-side OIDC env blocks (compose templates) — plugin compose-extensions are the live render path now. Long-term: extend aggregator with `from: app_manifest` source so Tier-2 apps land in inputs.clients alongside Tier-1.
- **Phase 1 multi-agent batch retro (2026-05-05) — DOCTRINE PINNED in [docs/multi-agent-batch.md](docs/multi-agent-batch.md).** Root cause of the cross-leak observed in Phase 1 (U6 wrote 7 plugin dirs to the parent worktree; U7's commit landed on `feat/u9-wing-docblocks-a`; U9 reported dirty state from siblings on first checkout) was **prompt engineering, not git**. Worker prompts opened with "Project root: `/Users/pazny/projects/nOS`" and agents took the absolute path literally — once they used `/Users/pazny/projects/nOS/...` paths, they bypassed the worktree's filesystem isolation. `git worktree` is filesystem-isolated, not namespace-isolated. Mitigation: the doctrine doc carries a worker-prompt template that mandates relative paths only, a CWD pre-flight assertion, throttled parallelism (≤5 until 3-worker trial passes), and a coordinator post-batch checklist. **Use the doctrine before spawning Phase 3 (U11-U14) or any A8 conductor sub-batches.**
- **Drift baseline staleness (security scan):** `docs/llm/security/scan-state.json` last_full_scan field can drift (>14 days = drift hook starts complaining). Resolved long-term by conductor agent (A8 phase) auto-running scans on schedule; manual interim refresh: see `hooks/playbook-end.d/20-cve-drift-check.sh` output for the diagnostic format.
- **Wing API endpoints for Pulse not yet implemented:** `/api/v1/pulse_jobs/due` and `/api/v1/pulse_runs/start|finish` are spec'd in `files/anatomy/docs/plugin-loader-spec.md` but missing PHP presenters in `files/anatomy/wing/app/Presenters/`. Pulse idle-tolerates 404 gracefully (warns once per minute, no crash-loop). Implementation lands alongside A7 (gitleaks plugin — first scheduled-job consumer).
- **Security remediation backlog:** see `docs/active-work.md` for the live count and phase plan. As of the 2026-05-04 morning snapshot there are **12 pending** `remediation_items` rows (was 14; REM-001 Portainer socket-proxy surface trim + REM-002 Woodpecker trusted-repos closed in the tune-and-thin pilot batch). Phase A is mechanical CVE pins; Phase B is `mem_limit`/`cpus` sweep; Phase C is hardening; Phase D is architectural. Vendor-blocked: Open WebUI ZDI CVEs, RustFS gRPC sigverify.
- **Mkcert CA regression class** (compose templates with unconditional `rootCA.pem` mounts breaking Authentik LE cert validation on public TLDs) — **CLOSED 2026-05-03** across **14 roles**: `pazny.{open_webui,grafana,vaultwarden,bookstack,code_server,freescout,gitlab,hedgedoc,miniflux,n8n,nodered,outline,paperclip,wordpress}`. Pattern: `{% if install_authentik | default(false) and (tenant_domain_is_local | default(true) | bool) %}` around the volume mount AND the matching `*_CA_CERTS` / `GF_AUTH...TLS_CLIENT_CA` env var. **Whenever a new role with Authentik OIDC is added, this gate MUST be applied** or LE chain validation breaks on the operator's public TLD.
- **Tier-2 manifest healthcheck gotcha:** `qdrant/qdrant:v1.13.x` (and likely other Rust-based slim images) ships with **no curl/wget/python** — only `bash` + the service binary. The standard `wget --spider` healthcheck logs `wget: not found` 1× per probe interval and marks the container unhealthy. Use `["CMD", "bash", "-c", ":>/dev/tcp/127.0.0.1/<port>"]` for TCP-level liveness, or skip the healthcheck entirely and rely on `restart: unless-stopped`. Surfaced live during operator's Qdrant verification blank 2026-05-04.
- **wing-nginx stale-IP after wing recreate** (2026-05-04): nginx resolves `wing:9000` once at config-load and caches the IP. When the wing container is recreated during a playbook run (new IP), wing-nginx still proxies to the OLD IP and serves 502s until manually restarted. Fixed structurally in `roles/pazny.wing/templates/wing-nginx.conf.j2` with a `resolver 127.0.0.11 valid=10s` directive + variable upstream (`map $host $wing_upstream { default wing:9000 }` + `fastcgi_pass $wing_upstream`). Pattern applies to any nginx sidecar talking to a Docker-named upstream — keep this shape if you add more sidecars.
- **LSIO code-server image is HTTP-only on 8443** (2026-05-04): `lscr.io/linuxserver/code-server` defaults to plain HTTP on 8443 unless the `--cert` CLI flag is passed (which we don't). Listing it in `traefik_https_upstream_ids` (in `roles/pazny.traefik/vars/main.yml`) was incorrect — Traefik sent a TLS handshake, the upstream answered with HTTP, and operator saw `tls_get_more_records: packet length too long` SSL errors → 502/404. Treat the LSIO image as HTTP upstream. The list is now `[]` by default; if you onboard a service that DOES bind HTTPS internally, add it explicitly.
- **Forward-auth vs. native-OIDC SSO**: services with `200 OK` on Traefik route (e.g., Gitea, Portainer, HedgeDoc) are NOT bypassing SSO — they have **native OIDC** with their own login page that surfaces a "Sign in with Authentik" button. Forward-auth (Traefik middleware `authentik@file`) is used for services WITHOUT app-level OIDC support. Don't try to add `authentik@file` middleware on top of native-OIDC services — operator gets a double-login UX for no security benefit.
- **Wing /events table schema mismatch — CLOSED 2026-05-05 (Anatomy P1):** the `events` table now carries a `source TEXT` column + index. Schema-extensions.sql declares it; init-db.php's idempotent ALTER sweep adds it to pre-existing DBs. Bone's `clients/wing.py::insert_event` reads `payload['source']` and writes the column; `query_events` accepts it as a filter. Wing's EventRepository + EventsPresenter mirror both. Callback plugin pins `source: "callback"` at write time. Free-text hint pre-A10 — A10 lands `actor_id` (FK Authentik clients) + `actor_action_id` (UUID) for cryptographic attribution alongside.
