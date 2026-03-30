# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Ansible playbook for automated macOS development environment setup (Apple Silicon M1+). Builds a self-contained **Agentic Home Lab** — dev stacks, web server, self-hosted AI agent (OpenClaw + Ollama), observability (LGTM stack), 25+ Docker services, and Tailscale remote access. All services are FOSS, data stays local. Designed for replicability — `blank=true` wipes and reinstalls from scratch.

Fork of geerlingguy/mac-dev-playbook.

## Git Workflow

**Veškerý vývoj probíhá ve větvi `dev`.** Branch `master` je release branch — merge do masteru provádí výhradně uživatel ručně, až bude repo a CI stabilní. NIKDY necommituj, nepushuj, nevytvářej PR ani worktree z `master`. Všechny operace (commity, worktrees, feature branches) MUSÍ vycházet z `dev`.

## Vision

OS-agnostic "All-in-One PC" — entire logic and data layer runs on replicable self-hosted FOSS technologies. The Ansible playbook is the single source of truth. OpenClaw (Inspektor Klepítko) acts as the autonomous DevOps agent managing the system.

## Key Commands

```bash
# Full playbook run (prompts for sudo password)
ansible-playbook main.yml -K

# Clean reinstall (wipes data, resets all services)
ansible-playbook main.yml -K -e blank=true

# Run specific component by tag
ansible-playbook main.yml -K --tags "observability"
ansible-playbook main.yml -K --tags "nginx,php"

# Dry run / Syntax validation
ansible-playbook main.yml -K --check
ansible-playbook main.yml --syntax-check

# Linting (must pass before merge)
yamllint .
ansible-lint

# Install/update Galaxy dependencies
ansible-galaxy install -r requirements.yml
```

## CI Pipeline

GitHub Actions runs three stages: **Lint** (yamllint + ansible-lint on Linux) → **Syntax Check** (on Linux) → **Integration** (full playbook + idempotence check on macOS 14/15). Integration runs on pushes to `master` and `claude/**` branches, and on non-draft PRs. CI uses `tests/config.yml` which disables heavy services (Docker, Ollama, Tailscale).

The idempotence check runs the playbook twice — the second run must produce `changed=0 failed=0`.

## Architecture

### Configuration Layering (later overrides earlier)

1. **`default.config.yml`** — all variables with defaults (read-only reference)
2. **`config.yml`** — feature toggles (gitignored, created from `config.example.yml`)
3. **`credentials.yml`** — secrets only (gitignored, created from `credentials.example.yml`)

All default passwords follow pattern `changeme_pw_[service]`.

### Playbook Execution Flow (`main.yml`)

1. **Blank reset** (if `-e blank=true`) — wipes Docker, data, configs
2. Loads config layers and gathers facts
3. Runs Galaxy **roles**: osx-command-line-tools → homebrew → dotfiles → mas → dock
4. Runs **tasks**: macOS system → power management → languages/runtimes → nginx → external storage → Docker stacks → networking → shell extras → AI agent (OpenClaw) → observability → stack-up → mariadb_setup → nextcloud_post → gitea_post → uptime-kuma-monitors → stack_verify → service registry

**Ordering matters**: PHP before Nginx (socket), external-storage before IIAB (data paths), mariadb_setup before stack_verify (DB must exist for Nextcloud onboarding).

### Docker Stacks (8 compose files in `~/stacks/`)

| Stack | Services |
|-------|----------|
| **infra** | MariaDB, PostgreSQL, Redis, Portainer, Traefik, Bluesky PDS |
| **observability** | Grafana, Prometheus, Loki, Tempo |
| **iiab** | Nextcloud, n8n, Kiwix, Jellyfin, Open WebUI, Uptime Kuma, Calibre-Web, Home Assistant, RustFS |
| **devops** | Gitea, Woodpecker CI, GitLab |
| **b2b** | ERPNext, FreeScout, Mattermost, Outline |
| **voip** | FreePBX (Asterisk) |
| **engineering** | QGIS Server |
| **data** | Metabase, Apache Superset |

### Observability (Apple Silicon optimized)

- **Metrics**: Grafana Alloy (`prometheus.exporter.unix` with ARM64-safe collectors) → Prometheus
- **Logs**: Alloy tails nginx/php/agent logs → Loki
- **Traces**: OTLP receiver (gRPC :4317, HTTP :4318) → Tempo
- **No standalone node_exporter** — Alloy's in-process exporter replaces it (avoids thermal/rapl/hwmon errors on ARM64)

### Nginx Auto-Enable

Nginx vhosts activate automatically based on `install_*` flags. 24 vhost templates in `templates/nginx/sites-available/`. Override with `nginx_sites_enabled` or extend with `nginx_sites_extra`.

### Tailscale Remote Access

Services accessible via ports (`services_lan_access: true`). Homepage (`tailscale_hostname`) → Grafana. Dashboard tiles have clickable subdomain (local) + port (Tailscale) links.

### Feature Toggle Pattern

Every component is gated by an `install_*` or `configure_*` boolean variable. The `when:` condition on each `import_tasks` controls inclusion. Tags allow CLI-level filtering.

### Handlers

15+ centralized handlers in `main.yml` (nginx, php-fpm, mariadb, grafana, alloy, prometheus, dnsmasq, ssh, openclaw, etc.).

### Static Files vs Templates

- **`files/`** — static configs (observability, openclaw persona SOUL.md/AGENTS.md/TOOLS.md)
- **`templates/`** — Jinja2 templates (`.j2`) rendered with variables (nginx vhosts, docker-compose, dashboard)

## Linting Rules

- **yamllint**: max line length 180 (warning), extends default (`.yamllint`)
- **ansible-lint**: skips `schema[meta]`, `role-name`, `fqcn`, `name[missing]`, `no-changed-when`, `risky-file-permissions`, `yaml` (`.ansible-lint`)

## Documentation Language

README.md, TLDR.md, inline comments, and task names are in **Czech**. Maintain this convention.

## Apple Silicon Constraints

- Target: ARM64 only (M1+). No x86 compatibility needed.
- `homebrew_prefix: /opt/homebrew` (not `/usr/local`)
- node_exporter collectors: only ARM64-safe set (cpu, diskstats, filesystem, loadavg, meminfo, netdev, netstat, vmstat)
- Docker Desktop for Mac (not Colima/Lima)

## Known Tech Debt

`ansible_env` usage needs migration to `ansible_facts` before Ansible-core 2.24 (see `TODO.md`).
