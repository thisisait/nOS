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

## A0 + A1 status (2026-05-03)

- **A0 — skeleton** ✅ committed `c09fc52`. Empty subdirs created with `.gitkeep`; ansible.cfg declared dual-paths (legacy `./library` + new `./files/anatomy/library`).
- **A1 — anatomize-move** ✅ this commit. Top-level `migrations/`, `library/`, `module_utils/`, `patches/` physically moved to `files/anatomy/`. ansible.cfg dropped legacy paths. Framework-internal docs (framework-overview, framework-plan, migration-authoring, upgrade-recipes, coexistence-playbook, wing-integration) moved from `/docs/` per §4.2 split rule. CLAUDE.md updated. 434/434 tests green; ansible-playbook --syntax-check clean.

Top-level `migrations/`, `library/`, `module_utils/`, `patches/` directories
are GONE. Anything that referenced them via path string has been updated to
`files/anatomy/...`. Python imports of `module_utils.X` continue to work
because `tests/conftest.py` (NEW in A1) adds `files/anatomy/` to sys.path
in addition to repo root.

Phases A2-A10 (per `docs/bones-and-wings-refactor.md` §8) populate the
remaining empty subdirs (`wing/`, `bone/`, `pulse/`, `skills/contracts/`,
`agents/`, `scripts/`).

## Pointers

- Doctrine: `docs/bones-and-wings-refactor.md` §1.1
- PoC plan: `docs/bones-and-wings-refactor.md` §8 (A6.5 = Grafana thin-role pilot)
- Track Q (post-PoC autowiring debt consolidation): `docs/bones-and-wings-refactor.md` §13.1
- Glossary: `docs/bones-and-wings-refactor.md` §14
