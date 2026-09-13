# AgentKit — how an agent runs, spends, and satisfies

> **PROPOSED, not settled.** This file mines rules the tree already enforces.
> It does not invent a second runtime. The operator settles §6 before anything
> cites this file. Sibling of [`organs.md`](organs.md) in status.
>
> Authorities this file points at, never copies: `state/schema/agent.schema.yaml`,
> `state/llm-backends.yml`, `docs/ait-runtime-architecture.md` (essay; stale
> where §6 names it).

There is one AgentKit: `files/anatomy/wing/app/AgentKit/`, opened by
`tools/run-agent.sh` → `files/anatomy/wing/bin/run-agent.php`.

## 1. Mediation — the runner is the only door

- A ceremony is a session the runner opens. The shell wrapper exists because
  `bin/run-agent.php` cannot inherit the daemon env from a terminal
  (`tools/run-agent.sh:4-30`). Raw `claude --print` is not a ceremony.
- A tool loads only if every scope it requires is in
  `audit.capability_scopes` (`ToolRegistry.php:16-20,48-53`). Unknown tool
  id refuses the session (`ToolRegistry.php:42-46`).
- Verb and scope match: one Wing tool used to carry GET and POST behind
  `wing.read` (`McpWingTool.php:13-16`). Read is GET + `wing.read`
  (`McpWingReadTool.php:10-23`); write is POST + `wing.write`
  (`McpWingWriteTool.php:10-33`). A GET scope may not serve a POST.
- A tool that reaches no data names no data scope
  (`ContractSearchTool.php:68-76` → `mcp.tool_use` only). A tool that
  reaches a token-gated organ rides that organ's axis
  (`ExecTool.php:61-69` → `cortex.exec`); the token still decides the call.
- Constraint A sits where the model chooses: `McpLoopTool` allowlists
  `propose` and refuses `judge` by name (`McpLoopTool.php:28-45,37-45`).
  Satisfaction is `nos-loop judge` via `GateOracle`, never the proposer's
  client (`GateOracle.php:8-18`).
- The schema enum and DI-registered `id()` returns must match both ways
  (`test_the_tool_enum_tracks_registration.py:1-10`). Intent is a roadmap
  row, not a reserved enum member.

## 2. Identity, scopes, vault

- Three layers, never conflated: Authentik client `agent:<name>` (actor_id) ·
  session uuid (`actor_action_id`) · W3C `trace_id` (`Runner.php:34-35,875`).
- Two scope vocabularies coexist **by design**: `audit.capability_scopes`
  (AgentKit tool scopes) vs `capabilities` (Authentik `nos:*`)
  (`agent.schema.yaml:256-269,516-519`). Do not unify them by renaming one.
- Wing principal: `NOS_AGENT_WING_TOKEN` first; `WING_API_TOKEN` fallback
  **announces itself** (`McpWingTool.php:31-47`).
- `secret_ref` is a pointer, never a value. Resolution is session-open,
  function-local, instance-cached, never disk
  (`CredentialResolver.php:10-46`). Schemes: `env:`, `infisical:`, `nos:`
  (`CredentialResolver.php:114-146`). Backend `auth_secret` uses the same
  rule (`llm-backends.yml:94-97`; `dereferenceRef` at
  `CredentialResolver.php:99-111`).
- NULL-scope Wing tokens ratchet down only
  (`test_unrestricted_tokens_only_ratchet_down.py:1-27`; `CEILING = 0`).

## 3. Backends — a backend is not a provider

- `llm.provider` names the **adapter** (fail-closed, adapter-first).
  `model.backend` names a **row** in `state/llm-backends.yml`
  (`agent.schema.yaml:103-120`; `llm-backends.yml:16-30`). A new
  orchestrator joins as a row, never as per-agent free text
  (`llm-backends.yml:11-14`).
- Binding gates in `BindingResolver.php` (header still says six;
  `llm-backends.yml:32-53` lists 1–6; gates 7–8 are in the resolver):
  declaration · row exists · armed via `NOS_ARMED_BACKENDS` (disarmed
  degrades to default + audit event) · agent's `gdpr.processors` names the
  backend's processor · `deferred` refuses · opus/empty model-id refuses ·
  adapter must speak the row's `protocol` (`BindingResolver.php:68-85`) ·
  `transfers_outside_eu: false` only against EU-resident rows, no degrade
  (`BindingResolver.php:117-139`).
- Committing a row or `agent.yml` does not arm a backend
  (`llm-backends.yml:36-41`).
- URI load: `Factory::fromUri` (`Factory.php:49-79`). Pattern the loader
  accepts: `^(anthropic|claude|openai|openclaw)-…`
  (`agent.schema.yaml:63`; `AgentLoader.php:400-403`).

## 4. Ceremonies — satisfaction is a gate run

- `outcomes.gateset` is required; membership checked at load
  (`agent.schema.yaml:190-207`; `AgentLoader.php:159-172`).
- Grader is optional **feedback**. It does not decide satisfaction. Same
  URI as primary/backend is refused (`agent.schema.yaml:68-81`;
  `AgentLoader.php:105-120`). Gate:
  `tests/anatomy/test_satisfaction_is_written_by_a_gate_run.py`.
- `GateOracle` shells to `nos-loop` so Bone stays the only judge
  implementation (`GateOracle.php:12-18`). Indeterminate ranks below fail
  (`GateOracle.php:41-42`).
- A named `outcomes.deliverable.event` must exist **with a body**, keyed to
  this session, or satisfaction is unmade (`Runner.php:853-879`;
  `agent.schema.yaml:208-237`). `filed_by: runner` is for ceremonies with
  no write plane (`agent.schema.yaml:218-226`).
- `one_shot`: schema-validated answer; the verdict is the reader's
  (`agent.schema.yaml:140-146`).
- Exit trichotomy is the runner's (`run-agent.php:14-17`).

## 5. Lineage and roster

- One join key: session uuid = `events.actor_action_id` (`Runner.php:875`).
- `metadata.runner_status` ∈ `unproven | parked | deferred | proven`.
  Absent renders UNKNOWN. `scheduled` is not a value — cadence is a pulse
  edge, not an evidence label (`agent.schema.yaml:348-369`).
- No agent memory, no coordinator: KEAP is the estate's memory
  (`test_agent_memory_does_not_return.py:1-11`).
- `gdpr:` is per-agent. `processors: []` is a claim that nobody processes.

## 6. Axes the operator still settles

The tree does **not** agree with itself here. Do not pick in this file.

| axis | question | today |
|---|---|---|
| URI first segment | vendor, wire protocol, or adapter name? | Pattern + loader: anthropic, claude, openai, openclaw (`agent.schema.yaml:63`, `AgentLoader.php:402`). Schema **description** still lists `local` (`agent.schema.yaml:64-67`). Factory **header** still says `openai-*` throws and `local-*` is reserved (`Factory.php:14-19`); `fromUri` then implements `openai` as a protocol (`Factory.php:62-67`). Essay `docs/ait-runtime-architecture.md` is a third spelling. |
| tool FS path-scope | does a tool refuse a path outside the agent's tenant/user tree? | `BashReadOnlyTool` is argv-allowlisted read-only; path-scope is **not** implemented. Named as P3 in `docs/archive/fs-doctrine.md:151-157,175-178`. |
| BindingResolver gate count | is the law "six gates" or the eight checks the file runs? | Header: six (`BindingResolver.php:14-16`). File: protocol + residency after the six (`BindingResolver.php:68-139`). Register header documents 1–6 (`llm-backends.yml:32-53`). |
