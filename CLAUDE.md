# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**devBoxNOS** — Ansible playbook pro automatizované macOS development environment (Apple Silicon M1+). Kompletní self-hosted **Agentic Home Lab** s 40+ Docker službami organizovanými do 45 Ansible rolí, SSO (Authentik), secrets vault (Infisical), webovým desktopem (Puter), AI agentem (OpenClaw + Ollama MLX), observability (LGTM stack), a Tailscale remote access. Všechny služby jsou FOSS, data zůstávají lokálně. Replikovatelné — `blank=true` smaže vše a nainstaluje znovu.

Fork of geerlingguy/mac-dev-playbook → přejmenované role pod `pazny.*` namespace.

## Git Workflow

**Veškerý vývoj probíhá ve větvi `dev`.** Branch `master` je release branch — merge do masteru provádí výhradně uživatel ručně. NIKDY necommituj, nepushuj, nevytvářej PR ani worktree z `master`. Všechny operace MUSÍ vycházet z `dev`.

## Commit Convention

- Formát: **Conventional Commits** (`feat:`, `fix:`, `refactor:`, `docs:`, `chore:` atd.)
- **Žádný Co-Authored-By, žádný --author flag, žádné jméno autora.** Git autor se vyplní automaticky z git configu.
- Commit message: stručný, anglicky, imperativ. Tělo volitelné.

## Vision

OS-agnostic "All-in-One PC" pod pracovním názvem **devBoxNOS / Czechbot.eu**. Celá logika a data běží na replikovatelných self-hosted FOSS technologiích. Ansible playbook je single source of truth. OpenClaw (Inspektor Klepítko) je autonomní DevOps agent.

## Key Commands

```bash
# Full playbook run (prompts for sudo + password prefix)
ansible-playbook main.yml -K

# Clean reinstall (wipes data, resets all services, prompts for password prefix)
ansible-playbook main.yml -K -e blank=true

# Run specific component by tag
ansible-playbook main.yml -K --tags "stacks,nginx"
ansible-playbook main.yml -K --tags "observability"
ansible-playbook main.yml -K --tags "ssh,iiab-terminal"

# Syntax validation
ansible-playbook main.yml --syntax-check
```

## Architecture

### Role-Based Service Delivery (45 roles under `pazny.*`)

Every Docker service is owned by an Ansible role in `roles/pazny.<service>/`. Each role follows the **compose-override pattern**:

```
roles/pazny.<service>/
  defaults/main.yml      # version, port, data_dir, mem_limit defaults
  tasks/main.yml         # data dir creation + compose override render
  tasks/post.yml         # (optional) post-start API calls, DB setup, admin init
  templates/compose.yml.j2  # Docker Compose service fragment (no top-level networks:)
  handlers/main.yml      # (optional) service-specific restart handler
  meta/main.yml          # role metadata
```

**Compose-override merge**: Each role renders its `templates/compose.yml.j2` → `{{ stacks_dir }}/<stack>/overrides/<service>.yml`. Orchestrators (`core-up.yml`, `stack-up.yml`) use `ansible.builtin.find` to discover override files and pass them as `-f` flags to `docker compose up`. Base stack templates declare only `services: {}` + networks — actual service definitions come from role overrides.

**Role invocation with tag inheritance**: `include_role` needs both `apply: { tags: [...] }` AND `tags: [...]` on the task itself for `--tags` CLI filtering to work.

**Non-Docker roles** (glasswing, jsos, openclaw, iiab_terminal, boxapi): Wired via `import_role` in `main.yml` — these install directly on the host, not via Docker compose.

### Configuration Layering (later overrides earlier)

1. **`default.config.yml`** — all variables with defaults (committed)
2. **`default.credentials.yml`** — all secrets with `{{ global_password_prefix }}_pw_*` templates (committed)
3. **`config.yml`** — feature toggles override (gitignored)
4. **`credentials.yml`** — secrets override (gitignored)

Passwords follow pattern `{global_password_prefix}_pw_{service}`. Blank run prompts for prefix. Ansible `vars_files` precedence > role `defaults/main.yml`.

### Playbook Execution Flow (`main.yml`)

1. **Password prefix prompt** (if `blank=true`)
2. **Blank reset** — wipes Docker, data, configs. Honors external storage overrides via `tasks/stacks/external-paths.yml` so data on `/Volumes/SSD1TB/` gets wiped, not just empty `~/service` fallbacks.
3. **Auto-enable dependencies** — PostgreSQL, Redis, MariaDB based on `install_*` flags
4. **Auto-generate secrets** — Outline, Bluesky, Authentik, Infisical, Vaultwarden, Paperclip, jsOS
5. **Host roles**: osx-command-line-tools → pazny.mac.homebrew → pazny.dotfiles → pazny.mac.mas → pazny.mac.dock
6. **Host tasks**: macOS system → SSH/IIAB Terminal → languages/runtimes → nginx → external storage
7. **`tasks/stacks/core-up.yml`** — infra + observability stacks (always first):
   - Role renders (12 `include_role` calls: compose override templates)
   - `docker compose up infra --wait` + `docker compose up observability --wait`
   - DB setup (MariaDB databases, PostgreSQL databases + pgcrypto)
   - Post-start roles (7 calls): Authentik blueprints/OIDC, Infisical, Bluesky PDS, Portainer admin+OAuth
8. **Service configs**: nginx vhosts, data dirs, Alloy scrape targets, observability dashboards
9. **`tasks/stacks/stack-up.yml`** — remaining 6 stacks (iiab, devops, b2b, voip, engineering, data):
   - Role renders (26 `include_role` calls)
   - Loop: `docker compose up <stack> --wait` per stack
   - Post-start roles (15 calls): admin init, OIDC config, DB migrations, onboarding
   - Authentik service-side OIDC setup, Bluesky PDS bridge
10. **Post-provision**: stack health verification → jsOS → service registry

**Key invariant**: Infra + Observability are **always required, always first**. Post-start tasks can assume MariaDB, PostgreSQL, Authentik, Infisical, Grafana, Loki, Tempo are online.

### Docker Stacks (8 compose projects in `~/stacks/`)

| Stack | Services (each owned by a `pazny.*` role) |
|-------|----------|
| **infra** | MariaDB, PostgreSQL, Redis, Portainer, Traefik, Bluesky PDS, Authentik (server+worker), Infisical |
| **observability** | Grafana, Prometheus, Loki, Tempo |
| **iiab** | WordPress, Nextcloud, n8n, Kiwix, Jellyfin, Open WebUI, Uptime Kuma, Calibre-Web, Home Assistant, RustFS, Puter, Vaultwarden |
| **devops** | Gitea, Woodpecker CI, GitLab, Paperclip |
| **b2b** | ERPNext, FreeScout, Outline |
| **voip** | FreePBX (Asterisk) |
| **engineering** | QGIS Server |
| **data** | Metabase, Apache Superset |

### Non-Docker Applications

- **jsOS** — webový desktop (OS.js v3), Node.js via PM2 (port 8070)
- **OpenClaw** — AI agent daemon via launchd, Ollama 0.19+ s MLX backendem
- **IIAB Terminal** — Python Textual TUI, SSH ForceCommand pro `home` user
- **Glasswing** — Security research dashboard, PHP via Homebrew
- **BoxAPI** — local REST API bridge

### IAM & SSO (Authentik)

Centrální SSO přes Authentik (auth.dev.local). OIDC auto-setup vytváří providery + aplikace pro každou službu automaticky. Single source of truth: `authentik_oidc_apps` list v `default.config.yml`.

**Native OIDC (env vars):** Grafana, Outline, Open WebUI, n8n, GitLab (omniauth), Vaultwarden (SSO)
**Native OIDC (API/CLI):** Gitea (Admin API), Nextcloud (occ), Portainer (PUT /api/settings)
**Proxy auth (nginx forward_auth — access control only):** Uptime Kuma, Calibre-Web, Home Assistant, Jellyfin, Kiwix, WordPress, ERPNext, FreeScout, Infisical, Paperclip, Superset, Puter, Metabase
**No SSO:** FreePBX, QGIS
**AT Protocol identity:** Bluesky PDS (Authentik→PDS bridge auto-provisions @user.bsky.dev.lan accounts)

Proxy auth = gates access (Authentik login required), but service shows its own login form. Native OIDC = true SSO ("Login with Authentik" button). Embedded outpost auto-assigned to proxy providers in `authentik_oidc_setup.yml`. Cookie domain `.dev.local` enables cross-subdomain session sharing. Nginx `proxy_redirect` rewrites outpost Location header to public `auth.dev.local` URL.

### RBAC (Role-Based Access Control)

4 access tiers bound to Authentik groups via expression policies (`authentik_rbac_tiers` + `authentik_app_tiers` in `default.config.yml`):
- **Tier 1 (admin):** Portainer, Infisical, Grafana — `devboxnos-providers`, `devboxnos-admins`
- **Tier 2 (manager):** Gitea, GitLab, n8n, Superset, Metabase, Paperclip, ERPNext, FreeScout — + `devboxnos-managers`
- **Tier 3 (user):** Nextcloud, Outline, Open WebUI, Puter, Vaultwarden, Uptime Kuma, Calibre-Web, Home Assistant — + `devboxnos-users`
- **Tier 4 (guest):** Kiwix, Jellyfin, WordPress — + `devboxnos-guests`

### Secrets Management

- **Infisical CE** (vault.dev.local) — centrální vault pro infra secrets, REST API + CLI
- **Vaultwarden** (pass.dev.local) — Bitwarden-kompatibilní personal vault pro tenants

### Observability (Apple Silicon optimized)

- **Metrics**: Grafana Alloy (`prometheus.exporter.unix` ARM64-safe) → Prometheus
- **Logs**: Alloy tails nginx/php/agent logs → Loki
- **Traces**: OTLP receiver (gRPC :4317, HTTP :4318) → Tempo

### Nginx Auto-Enable

38 vhost templates in `templates/nginx/sites-available/`. Activate automatically based on `install_*` flags. Override with `nginx_sites_enabled` or extend with `nginx_sites_extra`.

### Adding a New Docker Service

1. Create role `roles/pazny.<service>/` following the compose-override pattern above
2. Add `include_role` call in the appropriate orchestrator (`core-up.yml` or `stack-up.yml`)
3. Add `install_<service>` toggle in `default.config.yml`
4. (Optional) Add OIDC entry in `authentik_oidc_apps` list + env vars in compose template
5. (Optional) Add nginx vhost template in `templates/nginx/sites-available/`

### Feature Toggle Pattern

51 `install_*` / `configure_*` boolean proměnných. `when:` condition + Tags pro CLI filtering.

## Linting Rules

- **yamllint**: max line length 180 (warning)
- **ansible-lint**: skips `schema[meta]`, `role-name`, `fqcn`, `name[missing]`, `no-changed-when`, `risky-file-permissions`, `yaml`

## Documentation Language

README.md, TLDR.md, inline comments, and task names are in **Czech**.

## Apple Silicon Constraints

- Target: ARM64 only (M1+). `homebrew_prefix: /opt/homebrew`
- Ollama 0.19+: nativní MLX backend (57% faster prefill, 93% faster decode)
- Docker Desktop for Mac (not Colima/Lima)

## Known Tech Debt

- `ansible_env` needs migration to `ansible_facts` before Ansible-core 2.24
- Mattermost removed (no ARM64 FOSS image), config retained for future
- ERPNext migration sometimes fails on first blank run (auto-retry implemented in `erpnext_post.yml`)
- Jellyfin / Open WebUI: known upstream bugs on fresh DB init — first run may restart-loop until data regenerates
- Bluesky PDS federation not yet functional (identity bridge creates accounts but AT Protocol federation requires public DNS)
