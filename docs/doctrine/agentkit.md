# AgentKit — how an agent runs, spends, and satisfies

> **v1 — settled.** ~25 commits since 2026-08-19 decided each of these rules
> ad-hoc, in commit bodies and file headers; this file collected them, and the
> operator ruled on the five open contradictions on 2026-09-02 (§6). Every rule
> is enforced by a named gate or refusal and is recorded here, not invented
> here.

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
- A ceremony with NO write plane declares `deliverable.filed_by: runner`: the
  model writes, the RUNNER files (the `f1ddef96` shape). The reader still reads
  the event back, still refuses empty, and the gates still decide — filing is
  not satisfying. Added 2026-09-02: conductor owed an event its own system.md
  forbade it to write, and passed its gates twice unsatisfiable.
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

## 6. Rulings of 2026-09-02 (were the open contradictions)

1. **The URI's first segment names the WIRE PROTOCOL, not the vendor.**
   `openai-*` is anything speaking the OpenAI API — a local model, a DGX on the
   LAN, a hosted endpoint; WHO serves it is the backend row's business, and "who
   holds the data" is answered by `gdpr.processors` + the residency gate, never
   by the URI. The schema was reality; the essay and CLAUDE.md are corrected.
   The string may grow more protocol families as they arrive — a new family is
   a new enum member PLUS its adapter, together (fail-closed, adapter-first).
2. **`scheduled` left the `runner_status` enum.** It named INTENT on an
   EVIDENCE axis — a scheduled-but-always-failing agent read as fine. Whether a
   pulse job fires an agent is DERIVED (pulse→agent graph edges); the enum
   keeps `unproven | parked | deferred | proven`, and a reader joins the axes.
3. **Scopes follow [`identity.md`](identity.md):** the manifest is the one
   authority, the mint is a projection of it, and a reader compares the live
   `api_tokens` row both directions (MISSING / UNDECLARED). Implementation is a
   roadmap row; the ruling is settled.
4. **Grandfathered unrestricted tokens ratchet DOWN.** Measured 2026-09-02:
   7 active NULL-scope tokens (one more than the register's 6 — reality beat
   the doc). Narrowing is driven by measured `agent_tool_use` history, tuned by
   manual loop runs simulating the night; new tokens are never NULL. Gate:
   `test_unrestricted_tokens_only_ratchet_down.py` — the ceiling may only fall.
5. **The tool enum tracks DI registration both ways.** `bash-write` and
   `mcp-pulse` (declarable, no implementation) are out; `ask-operator`'s
   inverse (implemented, undeclarable) can't recur either. Intent lives in the
   roadmap table, not the contract. Gate:
   `test_the_tool_enum_tracks_registration.py`.
