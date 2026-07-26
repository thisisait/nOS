# Cortex — Agent Definition

## CortexAgent

**System:** Cortex (host organ, `nos.host.cortex`)
**Bind:** `http://localhost:8098` (loopback only — no domain, no SSO)
**Role:** The reasoning organ. Typechecks agent-authored cortex-lang programs against the curated taxonomy and the controlled verb vocabulary, and publishes the ontology/opcode/database drift axes. It reasons and validates; it does not mutate — the validate surface has zero side effects.

### Context

- API base: `http://localhost:8098/`
- `/health` is unauthenticated; `/agent/v1/validate` and `/agent/v1/validate/opcodes` need `Authorization: Bearer <CORTEX_TOKEN_RO>`.
- Tokenless daemon ⇒ agent surface answers `503` (fail-closed); `/health` still reports `surface:"disabled"`.
- Store: `~/cortex/data/keap.db`; source + working dir: `files/anatomy/cortex/`.
- Callers are host-side only: Wing's executor, host AgentKit, later Pulse.

### Capabilities

- Validate (typecheck) a cortex-lang program and return a typed report (`POST /agent/v1/validate`).
- Publish the opcode registry + registry hash that Wing gates its handler map against (`GET /agent/v1/validate/opcodes`).
- Report liveness plus the three drift axes — ontology version, database identity, opcode registry hash (`GET /health`).

### Cautions

- `req.agentName` is a self-asserted, unbound header — it may be logged, never believed; no scope or filter keys on it.
- This organ serves cortex validation ONLY. It does NOT serve KEAP's taxonomy/search/objects/capture endpoints — those return `404`. Talk to the KEAP service (`nos.iiab.keap`) for the corpus.

### Skills Reference

See [SKILLS.md](SKILLS.md) for callable actions.
