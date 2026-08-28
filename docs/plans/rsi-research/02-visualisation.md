# Seeing the loops — model changes vs rendering changes

The complaint: the anatomy graph "says nothing about how the agents work." The local research
(§A) located it precisely: **there is no `agent` node kind.** An agent enters the graph only
as the cron owner of a Pulse job, and five of those nine nodes are structurally identical —
distinguishable only by their id string. The two fixes are different in kind: model gaps are a
compiler edit plus an address-space decision; rendering gaps are a Svelte edit. This estate
derives its graph (`tools/anatomy-graph-gen.py`) — nothing below is hand-authored.

## 1. What must enter the MODEL

New node kind (14th): **`agent:<name>`** — one per directory under `files/anatomy/agents/`.
Emitted by the compiler from files it either already opens and discards, or must newly read:

| Node/edge | Derived from | Compiler status today |
|---|---|---|
| `agent:<name>` node | `files/anatomy/agents/*/agent.yml` (already in `JOB_SOURCES`, `:130`) | opens the file, reads only `pulse:` |
| attrs: charter summary, `runner_status` (enum per arch item 8), `mode` | same file — `description`, `metadata.runner_status` | unread |
| `agent → tool` edges (kind: `data`) | `agent.yml` `tools:` roster | unread |
| `agent → authentik:<client>` edge — the principal | `default.config.yml` `authentik_agent_clients` (10 declared; zero in graph — "an agent has an SSO identity in the estate and no address in the address space") | source not opened |
| `agent → backend` edge — the binding | `agent.yml` `model.backend` + `state/llm-backends.yml` | `llm-backends.yml` not among sources at all |
| `pulse:<owner>:<job> → agent:<name>` edge (kind: `trigger`) | job's `command_name: run-agent.sh` + owner | derivable from data already parsed |
| `agent → gateset` edge — the oracle (arch item 3) | `agent.yml` `outcomes.gateset` | field is new; compiler reads it when it exists |
| `agent → weakness` edges — loop membership | today underivable: `loop_proposals.proposer_id` is a string, not a session. **Lands with arch item 5** (`session_uuid` column) — the edge is derived from the joined ledgers, not hand-authored | blocked on item 5 |
| rubric / `max_iterations` attrs | `agent.yml` `outcomes:` | unread |

What stays OUT of the model, deliberately: cost and outcome. The artifact is build-time by
design (`graph.ts:6-13`); runtime state joins at render (below). Do not put `agent_sessions`
rows into a committed JSON.

Face side: `NodeKind` in `files/anatomy/face/src/lib/anatomy/graph.ts:28-41` enumerates the
same thirteen kinds — add `agent` there or the face cannot render what the compiler emits.

Gate (ships with the compiler change): `test_every_agent_directory_has_a_node.py` — a detector
reading the emitted `state/anatomy-graph.json` against the filesystem: every agent dir yields
a node, every `tools:` entry an edge, every `authentik_agent_clients` row with a matching
agent an identity edge. Editing the test emits no node.

## 2. What is a RENDERING change only

- **Live state on agent nodes.** The pattern exists: pulse nodes join live state at 60s
  (`GraphView.svelte:10-12`, `joinLive`). Extend the same join to `agent:` nodes from
  `agent_sessions` (last outcome, tokens, `trace_id` Tempo deep-link) via the BFF — which is
  an allow-list projection, never a proxy (memory `nos-face-epic`).
- **Default filters.** `service`/`authentik` nodes are filtered out by default
  (`GraphView.svelte:52-55`) — modelled, one chip away. Agent principals should default ON
  when the agent lens is active.
- **The mutex is already drawn.** `claims: [agent-run-lock]` → 21 mutex edges, computed and
  rendered — "the single most operationally important fact about the five agent ceremonies is
  modelled and drawn" (local research §A). Nothing to do; noted so nobody rebuilds it.

## 3. Recorded and unrendered — the surfaces an operator decides on

Ranked by decision value (from local research §B):

1. **The decision queue — `/questions`.** `agent_questions` (schema-extensions.sql:846-875):
   severity, `expires_at`, `default_on_expiry`, `answered_by/via`, session lineage. Four gates
   pin its semantics; **no presenter, no panel, no face view reads it**. This is the
   human-in-the-loop surface every "three independent YES" argument presumes (Judge B,
   graveyard: FINISH). One Wing `QuestionsPresenter` + route: open questions, who answered,
   how many expired into their default. Expired-into-default is the number that tells the
   operator the loop is outrunning them.
2. **The run thread.** One session, end to end: `agent_sessions` → `agent_iterations`
   (grader *feedback text* — the estate grading its own agents, today one page deep) →
   `events` by `actor_action_id` → (post item 5) the `loop_proposals` row it authored → the
   verdict → the MR. The face's WingView already renders the event stream; the join to
   proposals is what item 5 buys.
3. **The roster.** Agent cards: charter, grants, binding, `runner_status`, last outcome,
   sample-set presence (ops plane). Makes "the roster reads much fuller than it runs" (§6i)
   visible instead of archaeological — two of four "live" agents have never produced a report,
   and the graph should say so.
4. **Honest rates.** Grafana 22-ai-agents "Success rate" computes `status='idle'` over all
   rows, all time, no window — "a number that will read low forever without saying why"
   (local research §B). Re-key it on oracle-written `outcome_satisfied` (arch item 3) with a
   window, or delete the panel; a stat that cannot move is not a stat.
5. *(later, queued with the drift probe)* drift/cost per ceremony over time.

## 4. Order

Model first (compiler + gate), then the `/questions` presenter, then the render joins. The
graph model change is a prerequisite for nothing in `01-architecture.md` items 1–5 and must
not block them; it runs parallel-safe.
