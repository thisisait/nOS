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

## Why this dir exists today (before A0/A1)

Operator and Claude agreed 2026-05-03 to validate the §1.1 doctrine on
Grafana FIRST (research dry-run V3) before doing the structural move (V2).
This dir bootstraps with just enough scaffolding to hold the research output,
so the artifacts have a stable home and aren't moved a second time when A0/A1
run.

After A0/A1, the `library/`, `migrations/`, etc. above will be present here
and the top-level repo dirs will be gone. **No files outside `files/anatomy/`
will need moving in A6.5 implementation** — only role-internal modifications
(thinning) plus new files inside this dir.

## Pointers

- Doctrine: `docs/bones-and-wings-refactor.md` §1.1
- PoC plan: `docs/bones-and-wings-refactor.md` §8 (A6.5 = Grafana thin-role pilot)
- Track Q (post-PoC autowiring debt consolidation): `docs/bones-and-wings-refactor.md` §13.1
- Glossary: `docs/bones-and-wings-refactor.md` §14
