# files/anatomy/

> **Status:** in-flight platform tree (2026-05-03 evening). A0-A4 and A6
> foundation have landed: this directory now holds Wing source, Bone source,
> Pulse source, custom Ansible modules, plugin-loader code, internal docs, and
> the first draft service plugin. A3.5/A5/A6.5/A7-A10 remain the active PoC work.
>
> **Doctrine source:** `docs/bones-and-wings-refactor.md` §1.1 + §6.

## Current contents

```
files/anatomy/
├── README.md                                         # this file
├── wing/                                             # Wing PHP/Nette source (A2)
├── bone/                                             # Bone FastAPI source (A3a)
├── pulse/                                            # nos-pulse daemon source (A4)
├── library/                                          # custom Ansible modules (A1)
├── module_utils/                                     # shared module utilities + plugin loader (A1/A6)
├── migrations/                                       # moved framework migrations (A1)
├── patches/                                          # moved patch artifacts (A1)
├── skills/
│   └── contracts/                                    # A5 outputs land here
├── docs/
│   ├── grafana-wiring-inventory.md                   # V3 — consumer-shape inventory (A6.5)
│   ├── authentik-wiring-inventory.md                 # V4 — source/aggregator-shape inventory (Q2 prep)
│   ├── role-thinning-recipe.md                       # 6-step deterministic process (v0.1; v0.2 needs V4 deltas)
│   └── plugin-loader-spec.md                         # A6 implementation contract — 4 hooks + DAG + aggregator
└── plugins/
    └── grafana-base/                                 # A6.5 doctrine PoC artifact (consumer plugin)
        ├── README.md
        └── plugin.yml                                # draft manifest
```

## Target contents (per refactor doc §4.2)

```
files/anatomy/
├── README.md
├── wing/                       # Wing PHP/Nette source; A3.5 switches runtime to FrankenPHP
├── bone/                       # Bone Python source (FastAPI)
├── pulse/                      # Pulse Python source
├── skills/                     # Reusable agent skills + contracts
│   └── contracts/              # wing.openapi.yml, bone.openapi.yml, wing.db-schema.sql
├── plugins/                    # Plugin manifests (gitleaks, grafana-base, ...)
├── agents/                     # Agent profile YAMLs (conductor, inspektor, ...)
├── migrations/                 # MOVED from /migrations/
├── upgrades/                   # MOVED from /upgrades/
├── patches/                    # MOVED from /patches/
├── library/                    # MOVED from /library/
├── module_utils/               # MOVED from /module_utils/
├── scripts/                    # Future validators/exporter CLIs; loader runtime is in module_utils/
└── docs/                       # Internal anatomy docs (framework-* etc., MOVED here)
```

## A0 — A6 status (2026-05-03)

- **A0 — skeleton** ✅ `c09fc52`. Empty subdirs + dual-path ansible.cfg.
- **A1 — anatomize-move** ✅ `2abbb5d`. migrations/library/module_utils/patches → files/anatomy/.
- **A2 — wing-move** ✅ `4202f40`. files/project-wing/ → files/anatomy/wing/.
- **A3a — bone host-revert** ✅ this commit. Bone container → host launchd. Source moved files/bone/ → files/anatomy/bone/. New plist + venv install in pazny.bone role.
- **A3.5 — wing host-revert** ✅ 2026-05-04. Wing FPM container + wing-nginx sidecar → host FrankenPHP launchd daemon (`eu.thisisait.nos.wing` on 127.0.0.1:9000). pazny.wing role refactored: Track-A reversal cleanup + Caddyfile + plist + bootstrap. Composer + DB init host-native; `wing-cli` profile retired. Traefik file-provider auto-derives `wing.<tld>` through the uniform host-mode path. Closes the wing-nginx stale-IP 502 bug class structurally.
- **A4 — pulse skeleton** ✅ `b101a0d`. roles/pazny.pulse + Python source + 16 tests.
- **A6 — plugin loader foundation** ✅ this commit. JSON Schema + Python loader + Ansible custom module + 4 lifecycle hooks wired into core-up.yml/blank-reset.yml + 25 tests. Hook side effects beyond filesystem primitives landed with A6.5.
- **A6.5 — Grafana thin-role pilot** ✅ 2026-05-04. Plugin loader gains real `render` / `render_compose_extension` / `copy_dashboards` / `wait_health` / `conditional_remove_dir` actions backed by Jinja2 + a manifest dotted-path resolver. `nos_plugin_loader` module wrapper now passes `template_vars: "{{ vars }}"` to render context. `pazny.grafana` thinned: provisioning artifacts (datasources/all.yml.j2 + dashboards/all.yml.j2 + 18 dashboard JSONs) moved to `files/anatomy/plugins/grafana-base/provisioning/`. OIDC env block + mkcert CA conditional + GF_INSTALL_PLUGINS + extra_hosts authentik moved to `templates/grafana-base.compose.yml.j2`. core-up.yml drops 2 datasource/dashboard render tasks; observability.yml drops the in-repo dashboard enumerate+copy pair. 48/48 anatomy tests green (+7 new for the new actions). **Track Q is now unblocked.**
- **Track Q1 — observability sweep partial** ✅ 2026-05-04 (same batch as A6.5). Plugin loader gains a sixth action `render_dir` (whole-directory render with .j2 → bare-name idempotent write). New plugins: `prometheus-base` (master config + 6 recording-rule files), `loki-base` (master config), `tempo-base` (master config). All 3 master configs + 6 prometheus rule files moved from `files/observability/<service>/` → `files/anatomy/plugins/<service>-base/provisioning/`. core-up.yml drops 4 imperative deploy tasks (Prometheus + recording-rules + Loki + Tempo) — replaced by 1 declarative manifest entry per plugin. 8 plugins now live (grafana-base + 4 sibling tune-and-thin drafts + 3 Q1 plugins). Remaining Q1: alloy host-side runtime (different pattern — Homebrew brew service, not docker) + 8-12 composition plugins (grafana-prometheus / grafana-loki / grafana-tempo cross-wiring) for Q1b.

Remaining: A5 (Wing OpenAPI/DDL exports),
(Grafana thin-role pilot), A7 (gitleaks plugin), A8 (conductor + agent
runner), A9 (notifications), A10 (audit trail).

## Pointers

- Doctrine: `docs/bones-and-wings-refactor.md` §1.1
- PoC plan: `docs/bones-and-wings-refactor.md` §8 (A6.5 = Grafana thin-role pilot)
- Track Q (post-PoC autowiring debt consolidation): `docs/bones-and-wings-refactor.md` §13.1
- Glossary: `docs/bones-and-wings-refactor.md` §14
