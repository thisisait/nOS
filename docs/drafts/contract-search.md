# Contract search — stop the agent from inventing endpoints

Measured: `jeff` asked "kolik je otevřených bezpečnostních nálezů", called a
made-up `/api/v1/security/findings/open/count`, got 404, reported it honestly.
The real endpoint, `GET /api/v1/remediation` (`?status, ?severity, ?component,
?limit`), is already described in `files/anatomy/skills/contracts/wing.openapi.yml`
(98 paths, 117 operations, 117/117 with a summary). The agent never saw it.

## 1. Tool or prompt block?

**Tool.** A prompt block means shipping some slice of 117 operations on
*every* turn of *every* agent that might need it, whether or not the turn
needs an endpoint at all — that's the wrong default cost, paid up front,
for a benefit needed occasionally. The measured turn was already 3695 input
tokens before this idea existed; a useful summary digest (name + summary,
~117 rows × ~15 tokens) is another ~1800 tokens EVERY call, dead weight on
the many turns that never touch the API surface at all.

A tool costs one extra round trip only on the turns that need it, and the
result is small (rung 2 below) — closer to the existing `mcp-wing` shape,
which already exists and already handles the "hit the real endpoint" half.
This tool is the missing "find the real endpoint" half in front of it.

## 2. The surface

New tool id `contract-search`, sibling to `McpWingTool`, added to the
enum in `state/schema/agent.schema.yaml::tools[].id`.

```
id: contract-search
scopes: ['mcp.tool_use']          # read-only, no wing.read needed —
                                   # it never touches wing.db or a bearer token
name: contract_search
description: >
  Search nOS's own OpenAPI contracts (Wing + Bone) for an operation matching
  a natural-language request. Returns up to 5 candidate endpoints — method,
  path, and summary. Call this BEFORE guessing an endpoint path; if nothing
  scores above the floor, say so — do not invent a path.
input_schema:
  type: object
  required: [query]
  properties:
    query: {type: string, description: "what you're trying to do, plain language, any language"}
    surface: {type: string, enum: [wing, bone, any], default: any}
```

Output — **top 5 max**, one line each, no full operation objects:

```
GET  /api/v1/remediation           list remediation items (?status, ?severity, ?component, ?limit)
GET  /api/v1/gitleaks_findings     list gitleaks findings (?severity, ?limit)
GET  /api/v1/advisories            list advisories (?date, ?limit)
```

If the top score is below a floor, return `no confident match — do not guess
a path; ask the operator or use mcp-wing on a path you can justify from a doc`.
An agent that receives 117 rows has learned nothing; 5 ranked rows is a
decision, not a dump.

## 3. Ranking: cheap first, upgrade only if it misses

Recommend: **token overlap over the openapi `summary` + `path` fields**,
lowercased, with a tiny EN/CZ synonym table for the handful of domain nouns
that recur in this estate (bezpečnost→security, nález→finding,
otevřený→open, uzavřený→closed, zranitelnost→vulnerability). This is
`array_intersect` over token sets, no model call, sub-millisecond, and it
already gets "otevřené bezpečnostní nálezy" within reach of `remediation` /
`gitleaks_findings` summaries once "nález"→"finding" is in the table.

Cost of the upgrade path (nomic-embed-text via the already-running Ollama,
same one KEAP uses): precompute embeddings for the 117 summaries once at
build time (or first-load, cached to disk), embed the query at call time,
cosine-rank. Honest cost: one Ollama round trip per call (~tens of ms
locally, no network egress) plus a build-time step that must be re-run
when the contract regenerates — a cache-invalidation surface a bag-of-words
approach doesn't have. Worth it only once the synonym table's maintenance
cost exceeds its value; not needed to fix the measured failure.

`ponytail:` naive token-overlap + small hand-written synonym table, ceiling
is queries whose words share no lemma with any summary; upgrade to
nomic-embed-text cosine ranking if the synonym table starts fighting itself.

## 4. The refusal that matters

`docs/idea/02-cortex-lang.md` refuses `kg:`/`ent:` at namespace granularity
so no timing signal about *tenant data* survives a query. This tool is
different in kind, not just degree: it searches **our own OpenAPI contract**
— a static, already-committed, non-secret artifact describing the shape of
the API, not its contents. Searching it can never answer "does entity X
exist" or "how many rows are in table Y"; it can only answer "what verb and
path would ask that question."

The line, stated for the gate below: **this tool must never execute a
request, never read `wing.db`, never accept or return row data, entity
IDs, counts, or any value that could only be known by having queried the
live estate.** Its input is a free-text query; its output is confined to
the static `path` / `method` / `summary` strings already sitting in the
three committed contract files. If a future version wants live-count
short-circuiting ("just tell me the number"), that is a DIFFERENT tool,
built with the same care as `mcp-wing`'s scope gate — not a quiet feature
add to this one.

## 5. The check it leaves behind

`tests/anatomy/test_contract_search_is_read_only.py` (or a small
`ContractSearchToolTest.php` beside the existing AgentKit tool tests):

- assert `ContractSearchTool::requiredScopes()` does NOT include
  `wing.read`, `bone.read`, or any scope that gates a live data call
  (regression pin for §4);
- assert calling `execute()` performs zero HTTP/DB calls — feed it a
  `HttpClient`/PDO double that throws on any invocation, confirm it's
  never touched;
- one substantive query — `execute(['query' => 'otevřené bezpečnostní
  nálezy'])` — asserts `remediation` appears in the top-5 result, pinning
  the actual bug this design fixes.

## What contradicts the brief

None of the three contract files (`wing.openapi.yml`, `bone.openapi.yml`,
`wing.db-schema.sql`) are wired into anything at runtime yet — they are
committed but currently unread by any tool or prompt. `state/schema/agent.schema.yaml`
already reserves `mcp-pulse` as an enum value with no `Tools/` implementation
file, so adding `contract-search` alongside it is following an existing
precedent (reserved-id-before-impl), not inventing one.
