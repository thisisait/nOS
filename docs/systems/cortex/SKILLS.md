# Cortex — Skills

> Callable actions on the Cortex reasoning organ. Base URL `http://localhost:8098` (loopback only). The two agent-surface routes need `Authorization: Bearer <CORTEX_TOKEN_RO>`; `/health` is unauthenticated. A tokenless daemon answers `503` on the agent surface (fail-closed).

## check-health

**Trigger:** "is cortex up", "cortex health", "check the reasoning organ", "cortex drift"
**Method:** API
**Endpoint:** `GET /health` (also `GET /agent/v1/health`)
**Auth:** none
**Output:** `{status:"OK", organ:"pazny.cortex", surface:"enabled|disabled", version, binding:{ontologyVersion, databaseId, opcodeRegistryHash}, store:{...}, corpus:{...}}` — `binding` carries the three drift axes.

## validate-program

**Trigger:** "typecheck a cortex-lang program", "validate cortex source", "check this program against the taxonomy"
**Method:** API
**Endpoint:** `POST /agent/v1/validate`
**Auth:** Bearer `CORTEX_TOKEN_RO` (read scope; the route has zero side effects)
**Input:**
```json
{
  "source": "<cortex-lang program text>",
  "ttlSeconds": 300
}
```
`ttlSeconds` is optional, clamped to `[60, 3600]`.
**Output:** A typecheck report — `{valid, phase, complete, scope, ast, errors, warnings, truncated}`. Returns `200` even for a malformed program (a bad program is data, reported as typed entries); only a malformed *request* is a `400`. The drift stamp lives under `ast.binding` (`ontologyVersion`, `databaseId`, `opcodeRegistryHash`, `validatedAt`, `expiresAt`, `ttlSeconds`).

## get-opcodes

**Trigger:** "list cortex opcodes", "opcode registry", "what verbs does cortex accept"
**Method:** API
**Endpoint:** `GET /agent/v1/validate/opcodes`
**Auth:** Bearer `CORTEX_TOKEN_RO`
**Output:** `{contract:<version>, registryHash:"...", opcodes:[...]}` — the published registry Wing compares against its handler map at boot/CI (handlers ⊉ opcodes ⇒ Wing refuses to start).
