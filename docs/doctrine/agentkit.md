# AgentKit — how an agent runs, spends, and satisfies

> **PROPOSED, not settled.** ~25 commits since 2026-08-19 decided each of these
> rules ad-hoc, in commit bodies and file headers — the most expensive unwritten
> doctrine in the estate. This file collects them so the next decision cites a
> section instead of re-deriving one. §6 lists what the operator must settle;
> everything else is already enforced by a named gate or refusal and is recorded
> here, not invented here. Sibling of [`organs.md`](organs.md) in status.

Authorities this file points at, never copies: `state/schema/agent.schema.yaml`
(the manifest contract), `state/llm-backends.yml` (the orchestrator register,
binding gates 1–8 in its header), `docs/ait-runtime-architecture.md` (the essay
— stale in three places §6 names).

## 1. Mediation — the runner is the only door

- Every ceremony opens an AgentKit session through ONE runner
  (`tools/run-agent.sh` → `bin/run-agent.php`); raw `claude --print` is not a
  ceremony — no session, no cost accounting (`1a5b54b8`, `da881946`).
- A tool refuses the verb its scope does not name: mcp-wing split read/write,
  a GET scope may not serve a POST (`8e77cc4a`, `aa2a1add`).
- Write grants come from MEASURED use, never aspiration — grandfathering read
  the full `agent_tool_use` history; called nothing = granted nothing
  (`8e77cc4a`); and the gate pins WHO holds the write plane (`e5891c83`).
- No forge tool for the model: a session that can push can merge itself. The
  runner opens the MR from `metadata.path_written` (`f1ddef96`).
- The constraint sits at the point the model chooses: mcp-loop refuses `judge`
  BY NAME (`b80b0655`); judge satisfaction comes from `nos-loop judge --wait`,
  never the proposer's own client (`392fd6ee`).
- Attribution is stamped from ToolContext, model-supplied values never win
  (`0d7e515c`); an unattended run records `operator:pazny` (`6f76c1ee`).
- One agent-run lock, slots + PID reclaim (`b0383c8a`); lock windows derive
  from schedule + jitter + declared `max_runtime`, not measured averages
  (`1e986ef1`); a timeout must killpg or the grandchild leaks the slot
  (`f7543f37`).

## 2. Identity and scopes

- Three identity layers, never conflated: Authentik client `agent:<name>`
  (actor_id) · session uuid (actor_action_id) · W3C trace_id.
- Two scope vocabularies coexist BY DESIGN: `audit.capability_scopes` (AgentKit
  tool scopes) vs `capabilities` (Authentik `nos:*` OAuth scopes). The schema
  says so; do not unify them by renaming one.
- Per-agent principals: Wing token minted per `--agent`, Bone token via
  client_credentials asking only `NOS_AGENT_SCOPES`; every fallback announces
  itself (`3298ba04`, `d0d79575`).
- One spelling for a client secret: `secret:agent_<x>_client_secret`; the
  catalog refuses prefix-derived values (`95faa153`).
- A tool that reaches no data names no data scope (`contract-search` =
  `mcp.tool_use` alone); a tool that reaches a token-gated organ rides that
  organ's axis (`exec` = `cortex.exec`) and the "spendable" gate requires the
  mint to exist — a tool without its token is a 403 generator (`5a085b17`).
- Secrets live where the reading PROCESS runs, not where the workflow is
  described — judge tokens sit in bone.plist because Bone spawns judges
  (`a96ef4c5`). `secret_ref` is never plaintext; resolution at session-open.

## 3. Backends — a backend is not a provider

- `llm.provider` names the ADAPTER (fail-closed, adapter-first);
  `model.backend` names a ROW in `state/llm-backends.yml`. A new orchestrator
  joins as a row, never as per-agent free text (register header).
- Binding gates 1–8 (all fail-closed, register header): per-agent declaration ·
  row must exist · must be ARMED via `NOS_ARMED_BACKENDS` (disarmed degrades to
  default + audit event) · the agent's own `gdpr.processors` must name the
  backend's processor · `deferred` refuses any binding · opus-primary refuses
  foreign bindings · adapter must speak the wire protocol (`0d44bf29`) ·
  residency — `transfers_outside_eu: false` only when every backend that CAN
  serve is EU-resident (`38572e07`).
- Local/cloud is a SEPARATE AGENT, not a flag — a different Article-30 record
  (`f2f1d8e7`, `2969a475`).
- "Prepared, not armed": committing a row or agent.yml never half-arms a
  backend; arming is an operator config edit (`e43e9438`).
- The resolver reads `model_env`, not side labels (`e19a509d`); the CLI adapter
  serves tool-less ceremonies only and passes `--model` only when unbound
  (`fe775092`); no code authoring on MiniMax (ruling 1, `b75c2cbd`).

## 4. Ceremonies — satisfaction is a gate run

- Satisfaction is written by a GATE RUN, never by any model: `outcomes.gateset`
  required; grader == primary is refused; `rubric_path`/`model.grader` are
  FEEDBACK only (`392fd6ee`; schema: "a model asked to judge its own work
  agrees with itself").
- **A ceremony that filed nothing is not satisfied**: `outcomes.deliverable.event`
  names the event the session owes; absence unmakes satisfaction; the check
  requires a BODY and runs against a real database (`b5a8e62e`, `9a5d6d0f`,
  `af908a30`).
- The filing obligation goes in the TASK — the task is the turn the model
  answers, not line 175 of system.md (`c8ee8ebe`).
- An unrunnable judge is not failed work: peak 0 → `indeterminate`, and
  iteration-0 indeterminate stops the loop (`7b60d9ad`). Repair is
  deterministic parser → ONE format-only re-ask → UNPARSEABLE, always stamping
  `output_repaired` (`392fd6ee`).
- `one_shot`: one send, no tools, no retry, mandatory schema with
  `additionalProperties: false`; the verdict is the reader's — never the word
  "satisfied" (`443e1c57`, `c04431a7`).
- Exit trichotomy is the runner's: 0 clean · 1 HIGH operator-review ·
  2+ CRITICAL environment; sentinel `NOS_AGENT_EXIT: N` (schema).

## 5. Lineage and roster

- run_id == actor_action_id == session uuid == `events.actor_action_id` — one
  join key end to end (`ca884b0a` closed a 56k-row NULL vein). Every proposal
  names the session that wrote it; read-back refuses one that doesn't
  (`da881946`).
- The session row opens BEFORE the agent runs; every status a table declares
  has a writer (`791cc61f`). The answer lives as an `agent_message` event; the
  runner prints a summary, not the answer (`613d71cd`). Dashboards may not
  equate process-end with success (`f21dc718` — 72.7% claimed, 20.0% honest).
- `metadata.runner_status` ∈ unproven · scheduled · parked · deferred · proven;
  ABSENT renders as UNKNOWN (`b35a4038`). Retire = zero events ever + named
  successor; park = contract-only with a `plan_ref` that resolves (`b1661d3d`,
  `86a693ae`). No agent memory, no coordinator: KEAP is the estate's memory and
  a second store is a second truth (Q8=c, `c6271b0a`; gate
  `test_agent_memory_does_not_return.py`).
- An agent may not sign the operator's digest — a stale apex digest reporting
  AMENDED AFTER SIGNING is the system working (`f82ffdf3`).
- `gdpr:` is per-agent because records differ exactly where Article 30 cares;
  `processors: []` is a claim ("empty means NOBODY"); unverifiable processor
  facts are recorded UNVERIFIED, never asserted (schema; conductor agent.yml).

## 6. What the operator must settle (measured contradictions)

1. **URI provider enum drift** — the essay says `(anthropic|openclaw|openai|local)`
   with `openai-*` throwing; the schema says `(anthropic|claude|openai|openclaw)`
   and `openai-local-haiku` runs live (`e19a509d`). The schema is reality; the
   essay (and CLAUDE.md's A14 grader sentence, pre-`392fd6ee`) needs the edit.
2. **Scheduled-but-never-proven** — conductor carries `unproven` while a weekly
   pulse job schedules it; the enum holds both words and no rule picks one.
3. **The scope declared three times** (`d08abc81`) — agent.yml, mint task, live
   `api_tokens`; gates compare two. Name the single authority, as `95faa153`
   did for secrets.
4. **Grandfathered unrestricted tokens** — `api_tokens.scopes` NULL = unlimited
   for 6 incumbents, against the measured-use rule. When do they narrow?
5. **`bash-write` reserved-no-impl** — permitted, or must the tool enum track
   DI registration both ways (the `ask-operator` lesson: implemented but
   undeclarable for months)?
