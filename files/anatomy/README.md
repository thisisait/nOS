# files/anatomy/

> **Status:** seed (2026-05-03). Today this directory holds A6.5 research
> artifacts only. Phases A0-A1 will materialize the full skeleton; phases
> A2-A10 (and post-PoC Track Q) populate it.
>
> **Doctrine source:** `docs/bones-and-wings-refactor.md` §1.1 + §6.

## Current contents (research-only)

```
files/anatomy/
├── README.md                                         # this file
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

## Eventual contents (post-A1, per refactor doc §4.2)

```
files/anatomy/
├── README.md
├── wing/                       # Wing PHP-FPM rendered configs + jinja
├── bone/                       # Bone Python source (FastAPI) — moved from files/bone/
├── pulse/                      # Pulse Python source (NEW, A4)
├── skills/                     # Reusable agent skills + contracts
│   └── contracts/              # wing.openapi.yml, bone.openapi.yml, wing.db-schema.sql
├── plugins/                    # Plugin manifests (gitleaks, grafana-base, ...)
├── agents/                     # Agent profile YAMLs (conductor, inspektor, ...)
├── migrations/                 # MOVED from /migrations/
├── upgrades/                   # MOVED from /upgrades/
├── patches/                    # MOVED from /patches/
├── library/                    # MOVED from /library/
├── module_utils/               # MOVED from /module_utils/
├── scripts/                    # Plugin loader, validators, exporters
└── docs/                       # Internal anatomy docs (framework-* etc., MOVED here)
```

## A0 — A4 status (2026-05-03)

- **A0 — skeleton** ✅ `c09fc52`. Empty subdirs + dual-path ansible.cfg.
- **A1 — anatomize-move** ✅ `2abbb5d`. migrations/library/module_utils/patches → files/anatomy/.
- **A2 — wing-move** ✅ `4202f40`. files/project-wing/ → files/anatomy/wing/. (Rescoped from "submodule" after discovering source IS in repo.)
- **A4 — pulse-skeleton** ✅ this commit. New `roles/pazny.pulse/` thin role + `files/anatomy/pulse/` Python source + launchd plist + 16 unit tests + wing.db schema (`pulse_jobs` + `pulse_runs`). PoC scope: non-agentic subprocess runner only; agent runner is A8.

Phases A3 (track-A-reversal — Wing+Bone container → host launchd), A5
(wing exports), A6 (plugin loader), A6.5 (grafana thin-role pilot), A7
(gitleaks plugin), A8 (conductor + agent runner), A9 (notifications),
A10 (audit trail) remain.

## Pointers

- Doctrine: `docs/bones-and-wings-refactor.md` §1.1
- PoC plan: `docs/bones-and-wings-refactor.md` §8 (A6.5 = Grafana thin-role pilot)
- Track Q (post-PoC autowiring debt consolidation): `docs/bones-and-wings-refactor.md` §13.1
- Glossary: `docs/bones-and-wings-refactor.md` §14
