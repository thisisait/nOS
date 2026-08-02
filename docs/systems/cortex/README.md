# Cortex

> The reasoning organ — a loopback Node daemon that typechecks agent-authored cortex-lang programs against the curated taxonomy and the controlled verb vocabulary, and reports ontology/opcode/database drift on `/health`.

## Quick Reference

| | |
|---|---|
| **Toggle** | `install_cortex: true` (`default.config.yml`) |
| **Kind** | Host launchd daemon (Node 22) — NOT a Docker service |
| **Bind** | `127.0.0.1:8098` (loopback only; `CORTEX_BIND_HOST` default `127.0.0.1`) |
| **Port** | `8098` (`cortex_port`) |
| **Stack** | `host` (manifest `stack: null`) |
| **launchd label** | `eu.thisisait.nos.cortex` |
| **Package** | `nos-cortex` `0.1.0`, vendored KEAP v1.27.0 cortex port (`engines.node >= 22`) |
| **Working dir** | `files/anatomy/cortex` (`cortex_src_dir`) — runs in-place from the playbook tree |
| **Store** | `~/cortex/data/keap.db` (`cortex_store_path` = `~/cortex/data`) |
| **Logs** | `~/cortex/log` (`cortex_log_dir`) |

The daemon runs in-place from the playbook tree deliberately: its self-model half resolves `state/manifest.yml`, `files/anatomy/plugins/` and `docs/systems/` relative to its own module path, so the code must live where the estate's descriptors live. The store lives outside the tree so neither `git clean` nor a re-clone wipes reasoning history.

## Routing

Cortex has **no Traefik route and no Authentik provider at all** — by design (`docs/archive/nos-cortex-organ-design.md` §5, pure loopback default). Its id is in `traefik_skip_ids` ("Reasoning organ: pure loopback by design"). `cortex_domain` (`cortex.<tenant_domain>`) exists in defaults only for the day a route becomes an explicit opt-in — it is not wired today. Callers are host-side: Wing's executor, host AgentKit, and (later) Pulse.

## Authentication

Fail-closed Bearer service tokens (`files/anatomy/cortex/server/tokens.ts`), set via the launchd env:

- `CORTEX_TOKEN_RO` → aliased onto `KEAP_AGENT_TOKEN_RO` at boot — read scope (`agentAuth('ro')`), gates `/agent/v1/validate` and `/agent/v1/validate/opcodes`.
- `CORTEX_TOKEN_RW` → `KEAP_AGENT_TOKEN_RW` — read+write scope (unused by the C1 validate surface, which has zero side effects).

Token comparison is `timingSafeEqual` over a `sha256` of the presented bearer. **Tokenless ⇒ the agent surface answers `503`** (fail-closed): `/health` reports `surface: "disabled"` but the process stays up. `/health` itself is unauthenticated.

## API / Health

- **Base URL:** `http://localhost:8098/`
- **Liveness (unauth):** `GET /health` (also `GET /agent/v1/health`) — returns `{status:"OK", organ:"pazny.cortex", surface:"enabled|disabled", binding:{ontologyVersion, databaseId, opcodeRegistryHash}, store:{...}, corpus:{...}}`. The `binding` triple is the three drift axes.
- **Typecheck (RO):** `POST /agent/v1/validate` — typecheck a cortex-lang program; zero side effects.
- **Opcode registry (RO):** `GET /agent/v1/validate/opcodes` — the published registry Wing gates its handler map against.
- Any other path returns `404` in the `{success,error}` envelope. `contracts` declares `cortex` only (no `selfmodel`/corpus — that is KEAP's C2 scope, not this organ's).

## Dependencies

- Node ≥ 22 (nvm default; `tasks/node.yml` installs it).
- Its own libsql store at `~/cortex/data/keap.db`, materialised on boot from the repo spine + canonical tree + generated nOS self-model (`CORTEX_SELFMODEL=1`).
- KEAP (separate iiab Docker service, `nos.iiab.keap`) — Cortex is NOT KEAP; it is a distinct organ with its own store and `db_identity`. Embeddings/recall (`cortex_ollama_url`) are C2 scope, not served by the C1 daemon.
