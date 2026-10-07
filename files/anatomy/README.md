# files/anatomy/

The source of nOS's own parts. The directory name stays (lexicon: legacy).
Each subdirectory is placed by its level in `state/genome/lexicon.yml`, smallest
to largest; the words are defined in `docs/glossary.md`.

## By level

| level | directory | what it holds |
|---|---|---|
| genome | `skills/` | declared procedure contracts every part inherits |
| cell | `agents/` | one model in one specialization: charter, tools, backend |
| organ | `bone/` | Bone, the host API bridge between runs and records |
| organ | `wing/` | Wing, the host dashboard and audit ledger (and AgentKit) |
| organ | `pulse/` | Pulse, the scheduler that runs every scheduled job |
| organ | `cortex/` | Cortex, the reasoning machinery (its store is declared debt) |
| organ | `face/` | Face, the web desktop |
| organ | `ears/` | Ears, the speech organ |
| organ | `apex/` | Apex, the public page of the organ systems |
| organ | `device-gateway/` | the device gateway daemon (`state/manifest.yml` row `device_gateway`) |
| reflex | `loops/` | loop manifests; Pulse runs each on its clock |
| plugin (cross) | `plugins/` | `plugin.yml` wiring of one service to the others |
| plugin (cross)* | `n8n/` | n8n workflow packs a plugin installs |
| internal | `library/`, `module_utils/` | custom Ansible modules and their shared code |
| internal* | `scripts/` | helper CLIs the roles and agents call |
| internal* | `secrets/` | the secret registry (names, never values) |
| procedure* | `migrations/`, `patches/` | state migrations and patch records a converge applies |

\* placed by what it does; the lexicon does not name it yet.

Not a level: `contracts/` holds interface files, some generated (OpenAPI, Wing
DDL; the list is `state/generated.yml`), some authored or vendored (event types,
face-wing, keap/); `docs/` holds the guides.

## Where the rest lives

- What exists, declared: `state/genome/` (the genome realm, `ssot/INDEX.yml`).
- Law: `ssot/doctrine/`, with its data companions listed in `ssot/INDEX.yml`.
- The anatomy graph: `state/anatomy-graph.json`, copied to
  `face/src/lib/anatomy/anatomy-graph.json` by `tools/anatomy-graph-gen.py`.
- Gates: `tests/anatomy/` (the directory name stays, lexicon: legacy).
