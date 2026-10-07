# nOS architecture — the longer tour

`CLAUDE.md` carries the brief; this is the next level down. Per-service detail lives in
`docs/systems/<service>/README.md`; the body-plan words in
[ssot/doctrine/body-plan.md](../ssot/doctrine/body-plan.md) and [anatomy.md](anatomy.md).

## Role services — the compose-override pattern

Every Docker service is owned by `roles/pazny.<service>/`:

```
roles/pazny.<service>/
  defaults/main.yml         # port, data_dir, mem_limit defaults (version pins live in default.config.yml only)
  tasks/main.yml            # data dir + compose-override render
  tasks/post.yml            # (optional) post-start API calls, DB setup, admin init
  templates/compose.yml.j2  # Docker Compose service fragment (no top-level networks:)
  handlers/main.yml         # (optional) service-specific restart handler
  meta/main.yml             # role metadata
```

Each role renders `templates/compose.yml.j2` into
`{{ stacks_dir }}/<stack>/overrides/<service>.yml`. The orchestrators (`core-up.yml`,
`stack-up.yml`) `find` the override files and pass them as `-f` flags to
`docker compose up`. Base stack templates declare only `services: {}` + networks.

- **Tag inheritance:** `include_role` needs both `apply: { tags: [...] }` **and**
  `tags: [...]` on the task, or CLI `--tags` never reaches the inner tasks
  (gate `tests/anatomy/test_stacks_tag_inheritance.py`).
- **`--tags <svc>` also brings the container up (A17):** every compose-up task carries
  `tags: ['stacks'|'core', 'always']`, so `--tags woodpecker` renders AND recreates.
  `--skip-tags stacks` (or `core`) gives a render-only pass.
- **Cross-service wiring** (SSO clients, dashboards, notifications) lives in plugins,
  `files/anatomy/plugins/<service>-base/plugin.yml`; the block-by-block contract is
  `files/anatomy/docs/plugin-wiring-capabilities.md`, the thin-role target
  `files/anatomy/docs/role-thinning-recipe.md`.
- **Non-Docker roles** (wing, bone, pulse, cortex, openclaw, hermes, opencode,
  iiab_terminal, backup, state_manager, dotfiles, `mac.*`) are wired via `import_role` in
  `main.yml` and install on the host.

## Playbook execution flow (`main.yml`)

1. Password-prefix prompt — only on a confirmed removal (`remove=data|deep|all` + `confirm=true`).
2. Removal reset — wipes Docker state, data dirs and configs, honouring external-storage
   overrides (`tasks/stacks/external-paths.yml`).
3. Auto-enable dependencies — PostgreSQL, Redis, MariaDB follow the `install_*` flags.
4. Auto-generate secrets.
5. Host roles: command-line tools → Homebrew → dotfiles → mas → dock.
6. Host tasks: system prefs → SSH / IIAB Terminal → language runtimes → Nginx (opt-in) → external storage.
7. **`tasks/stacks/core-up.yml`** — `infra` + `observability`, always first: renders,
   `docker compose up -d`, health-wait, DB setup, then post-start roles (Authentik
   blueprints + OIDC, Infisical, Bluesky PDS, Portainer).
8. Service configs: vhosts, data dirs, Alloy scrape targets, dashboards.
9. **`tasks/stacks/stack-up.yml`** — the remaining stacks: renders, compose up, health-wait,
   post-start roles (admin init, OIDC, migrations, onboarding).
10. Post-provision: stack-health verification → service registry.

**Invariant:** infra + observability are always required and always first. Post-start
tasks may assume MariaDB, PostgreSQL, Authentik, Infisical, Grafana, Loki and Tempo are up.

### Stack bring-up (A19)

Bring-up is non-blocking `docker compose up -d`; `tasks/stacks/wait-stacks-healthy.yml` →
`files/anatomy/scripts/stack-health-probe.py` then prints a per-stack readiness line every
tick (`iiab: 17/18 ready (waiting: jellyfin[starting])`). The wait is **strict** — every
container must reach healthy. Tuning vars in `default.config.yml`:

| var | default | meaning |
|---|---|---|
| `stack_up_parallel` | `true` | `false` = one stack at a time (contention-free cold blank) |
| `stack_up_wait_timeout` | `540` | per-stack health budget, seconds (all-on profile: 1200) |
| `stack_wait_tick_interval` | `15` | heartbeat cadence, seconds |

`profiles/all-on.yml` enables every known-good service (excludes erpnext /
spacetimedb) and forces sequential bring-up.

## Docker stacks (compose projects in `~/stacks/`)

| Stack | Services |
|-------|------|
| **infra** | MariaDB, PostgreSQL, Redis, Portainer, Traefik, Bluesky PDS, Authentik (server + worker), Infisical |
| **observability** | Grafana, Prometheus, Loki, Tempo, InfluxDB |
| **iiab** | WordPress, Nextcloud, n8n, Node-RED, Kiwix, offline maps, Jellyfin, Open WebUI, MCP Gateway, Uptime Kuma, Calibre-Web, Home Assistant, RustFS, KEAP, Vaultwarden, ntfy, Miniflux |
| **apps** | manifest apps run by `pazny.apps_runner` (Documenso, 2FAuth, Roundcube, …) |
| **devops** | Gitea, Woodpecker CI, GitLab, Paperclip, code-server |
| **b2b** | ERPNext, FreeScout, Outline, HedgeDoc, BookStack, Firefly III, Dolibarr, OnlyOffice |
| **engineering** | QGIS Server |
| **data** | Metabase, Apache Superset |

The list moves; `state/manifest.yml` and `ls roles/` are the truth.

## Host applications (not Docker)

- **Bone** — FastAPI bridge between Ansible runs and Wing's SQLite (`files/anatomy/bone/`).
- **Wing** — Nette PHP dashboard + state-framework UI, FrankenPHP under launchd/systemd (`files/anatomy/wing/`).
- **Pulse** — scheduled-job runner (`files/anatomy/pulse/`).
- **Cortex daemon** — loopback Node daemon serving `/agent/v1/validate` from the vendored
  KEAP port (`files/anatomy/cortex/`, `roles/pazny.cortex`). Distinct from **KEAP**, the
  Docker-served knowledge layer (`roles/pazny.keap`, external repo `thisisait/nos-keap`).
- **OpenClaw** (agent daemon, Ollama MLX), **Hermes** (cross-channel agent gateway),
  **OpenCode** (coding helper), **IIAB Terminal** (Textual TUI as SSH `ForceCommand`).
- **Conductor** and the other AgentKit agents — `files/anatomy/agents/`, see
  [ait-runtime-architecture.md](ait-runtime-architecture.md).

## Edge, observability, state

- **Traefik** is the edge proxy (binds 80/443). File provider: `services.yml` derived from
  `state/manifest.yml` (`domain_var` + `port_var`). Docker provider: labels on manifest
  apps. Authentik forward-auth is the `authentik@file` middleware. Host nginx is an opt-in
  fallback (`install_nginx: true`). Guide: [traefik-primary-proxy.md](traefik-primary-proxy.md).
- **Observability:** Alloy (`prometheus.exporter.unix`) → Prometheus; Alloy tails logs →
  Loki; OTLP (`:4317` gRPC, `:4318` HTTP) → Tempo.
- **State & migration framework:** `state/manifest.yml` (expected) vs `~/.nos/state.yml`
  (runtime); one-shot migrations in `files/anatomy/migrations/`; per-service upgrade
  recipes in `upgrades/` (`--tags upgrade -e upgrade_service=<svc>`); dual-version
  coexistence via `nos_coexistence`. Every task streams to Bone → Wing through
  `callback_plugins/wing_telemetry.py` (fallback `~/.nos/events.jsonl`). Guides:
  `files/anatomy/docs/framework-overview.md`, `migration-authoring.md`,
  `upgrade-recipes.md`, `coexistence-playbook.md`, `wing-integration.md`.
- **Secrets:** Infisical (`vault.<tld>`) for infra secrets; Vaultwarden (`pass.<tld>`)
  for people.
