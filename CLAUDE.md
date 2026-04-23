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

**Non-Docker roles** (glasswing, jsos, openclaw, iiab_terminal, boxapi, hermes, opencode, backup, state_manager, dotfiles, `mac.*`): wired via `import_role` in `main.yml` — these install directly on the host, not through Docker Compose.

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
4. **Auto-generate secrets** — Outline, Bluesky, Authentik, Infisical, Vaultwarden, Paperclip, jsOS.
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
10. **Post-provision:** stack-health verification → jsOS → service registry.

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

- **jsOS** — web desktop (OS.js v3), Node.js via PM2 (port 8070)
- **OpenClaw** — AI agent daemon via launchd, Ollama 0.19+ with the MLX backend
- **Hermes** — cross-channel messaging gateway
- **OpenCode** — agentic coding helper
- **IIAB Terminal** — Python Textual TUI, SSH `ForceCommand` for the `home` user
- **Glasswing** — security-research dashboard, PHP via Homebrew
- **BoxAPI** — local REST API bridge

### IAM & SSO (Authentik)

Central SSO via Authentik at `auth.<tld>` (default `auth.dev.local`). OIDC auto-setup creates providers + applications for every enabled service. Single source of truth: the `authentik_oidc_apps` list in `default.config.yml`.

**Native OIDC (env vars):** Grafana, Outline, Open WebUI, n8n, GitLab (omniauth), Vaultwarden (SSO)
**Native OIDC (API / CLI):** Gitea (Admin API), Nextcloud (`occ`), Portainer (`PUT /api/settings`)
**Proxy auth (Nginx forward_auth — access control only):** Uptime Kuma, Calibre-Web, Home Assistant, Jellyfin, Kiwix, WordPress, ERPNext, FreeScout, Infisical, Paperclip, Superset, Puter, Metabase
**No SSO:** FreePBX, QGIS
**AT Protocol identity:** Bluesky PDS (the Authentik→PDS bridge auto-provisions `@user.bsky.<tld>` accounts)

Proxy auth gates access (Authentik login required) but the service still renders its own login. Native OIDC is true SSO (a "Sign in with Authentik" button). The embedded outpost is auto-assigned to proxy providers in `authentik_oidc_setup.yml`. Cookie domain `.dev.local` enables cross-subdomain session sharing. Nginx `proxy_redirect` rewrites the outpost `Location` header to the public `auth.dev.local` URL.

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
- **Migrations** — one-shot global transitions (rename `devboxnos-*` → `nos-*`, move state dirs, rewrite identifiers) in `migrations/<ISO-date>-<slug>.yml`. Ran automatically in `pre_tasks`. Idempotent: each step has `detect` / `action` / `verify` / `rollback`. Breaking migrations prompt for confirmation unless `-e auto_migrate=true`.
- **Upgrade recipes** — per-service version transitions in `upgrades/<service>.yml`. `pre` / `apply` / `post` / `rollback` phases. Invoked explicitly (`--tags upgrade -e upgrade_service=<svc>`) or via Glasswing. Covers breaking patterns like `pg_upgrade`, `mariadb-upgrade`, Grafana dashboard-preserving bumps.
- **Coexistence** — dual-version operation via `nos_coexistence` module. Provision a second track on a shifted port with cloned data, test, cut over via atomic Nginx reload, clean up after TTL. Supported: Grafana, Postgres, MariaDB, Authentik (special), Gitea, Nextcloud, WordPress.

Observability: a callback plugin (`callback_plugins/glasswing_telemetry.py`) emits structured events for every task + framework action to BoxAPI → Glasswing SQLite (with `~/.nos/events.jsonl` fallback). Glasswing exposes `/migrations`, `/upgrades`, `/timeline`, `/coexistence` views. Custom Ansible modules: `library/nos_state.py`, `nos_migrate.py`, `nos_authentik.py`, `nos_coexistence.py`.

Authoring: see [docs/framework-overview.md](docs/framework-overview.md), [docs/migration-authoring.md](docs/migration-authoring.md), [docs/upgrade-recipes.md](docs/upgrade-recipes.md), [docs/coexistence-playbook.md](docs/coexistence-playbook.md), [docs/glasswing-integration.md](docs/glasswing-integration.md). Authoritative spec: [docs/framework-plan.md](docs/framework-plan.md).

### Nginx auto-enable

50 vhost templates in `templates/nginx/sites-available/`. Activated automatically based on `install_*` flags. Override with `nginx_sites_enabled` or extend with `nginx_sites_extra`.

### Adding a new Docker service

1. Create a role `roles/pazny.<service>/` following the compose-override pattern above.
2. Add an `include_role` call in the right orchestrator (`core-up.yml` or `stack-up.yml`) — remember both `apply: { tags: [...] }` **and** `tags: [...]` so `--tags` filtering works.
3. Add an `install_<service>` toggle in `default.config.yml`.
4. (Optional) Add an OIDC entry in `authentik_oidc_apps` + env vars in the compose template.
5. (Optional) Add an Nginx vhost template in `templates/nginx/sites-available/`.

### Feature-toggle pattern

~78 `install_*` / `configure_*` boolean variables. `when:` conditions + tags for CLI filtering.

## Linting Rules

- **yamllint:** max line length 180 (warning)
- **ansible-lint:** skips `schema[meta]`, `role-name`, `fqcn`, `name[missing]`, `no-changed-when`, `risky-file-permissions`, `yaml`

## Documentation Language

`README.md`, `TLDR.md`, inline comments, and task names are in **English**. The Czech-language legacy has been retired as part of the `nOS` rebrand. If you find residual Czech strings, translate them.

## Apple Silicon Constraints

- Target: ARM64 only (M1+). `homebrew_prefix: /opt/homebrew`.
- Ollama 0.19+: native MLX backend (57% faster prefill, 93% faster decode).
- Docker Desktop for Mac (not Colima / Lima).

## Known Tech Debt

- `ansible_env` needs migration to `ansible_facts` before Ansible-core 2.24.
- Mattermost removed (no ARM64 FOSS image); config retained for the future.
- ERPNext migration occasionally fails on the first blank run (auto-retry implemented in `erpnext_post.yml`).
- Jellyfin / Open WebUI: known upstream bugs on fresh DB init — first run may restart-loop until data regenerates.
- Bluesky PDS federation not yet functional (the identity bridge creates accounts, but AT Protocol federation requires public DNS).
- Pre-2026-04-22 installs carry legacy `devboxnos-*` Authentik group names, `com.devboxnos.*` launchd bundle IDs, and the `~/.devboxnos/` state directory. Rebrand complete in-repo; migration on existing hosts needs a blank reset (or manual rename of the Authentik groups + `launchctl bootout` of the old plists).
