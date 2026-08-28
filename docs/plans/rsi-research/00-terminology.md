# Terminology — proposed for approval

Status: PROPOSAL. Nothing below is renamed in code yet. Grep evidence (Judge A §4): `nos-bi`,
`nos_bi`, `nos-sere`, `nos_sere` have **zero hits** in the checkout — every name here is still
free, so the rename cost is a docs-and-memory edit today and a `devboxnos-*`-style migration
later. Decide now.

## The one collision that forces a decision

CLAUDE.md (Architecture / Vocabulary, settled 2026-08-07, `docs/doctrine/layers.md`):
**"`tier` means RBAC and nothing else."** The operator's phrase "two tiers on top of the
runtime" cannot survive into code — the word carried four meanings once and the estate paid to
retire three of them. Both judges used "tier" loosely; neither may.

## The vocabulary

Ordering: shared runtime → identity → agent-level → loop-level → the split.

### 1. Runtime — **AgentKit** (keep)
The one shared agentic runtime: agent / session / thread / iteration / vault / webhook,
`files/anatomy/wing/app/AgentKit/`, doctrine `docs/ait-runtime-architecture.md`.
- NOT: a per-agent thing; there is exactly one, both planes run on it.
- Rejected: "nos-runtime" — renaming working, gated code buys nothing (estate rule: do not
  rename what already works).

### 2. Agent — **agent** (keep)
A directory: `files/anatomy/agents/<name>/{agent.yml,system.md,rubric.md}`, schema-gated
(`test_agent_schema.py`). Judge A: "the best-shaped thing here — keep unchanged."
- NOT: a process, a model, or a session. An agent is declaration; a session is execution.
- Rejected: "worker", "bot" — both imply the process, not the declaration.

### 3. Identity — **principal**
The verified identity a run presents: the per-agent Authentik client (`client_credentials`,
`nos-<agent>`, capabilities as OIDC scopes — enforced today only on the claude-CLI path,
`pulse-run-agent.sh:251-281`) plus, after the architecture's item 2, the per-agent scoped Wing
token. Settled IAM literature word (OAuth2/OIDC: the authenticated client is the principal).
- NOT: the `--actor` argv string (`bin/run-agent.php:114` → `Runner.php:260`), which is an
  assertion. `actor_id` stays as the *recorded* field name in `events`; a principal is what
  *proves* the actor_id.
- Rejected: "actor" — already load-bearing in the audit schema as the recorded (possibly
  asserted) identity; reusing it would let assertion keep masquerading as grant. Rejected:
  "client" — collides with the customer sense of nos-ops.

### 4. Intent — **charter**
The machine-readable statement of what an agent is for: what it reads, what artifact it may
produce, how it differs from its siblings. Today this is 24 lines of prose no compiler reads
(`surveyor/agent.yml:1-24`, local research §A); the charter promotes it to structured fields
(`reads:`, `produces:`, plus the existing `capability_scopes`) so the graph can render it.
- NOT: the system prompt (that is `system.md`, the *how*), and NOT `description` prose.
- Rejected: "role" — collides fatally with 76 Ansible `pazny.*` roles and Authentik RBAC
  roles. Rejected: "mission" — no literature anchor, pure flavor.

### 5. Tool grant — **grant**
A scope issued to a principal and enforced by the tool at call time (`requiredScopes()` →
refusal). OAuth scope semantics — the settled word.
- NOT: `capability_scopes` as it works today — `ToolRegistry.php:37-54` compares one block of
  agent.yml against another block of the same file; that is a *consistency check*, not a grant
  (local research §2, both judges). The word "grant" is reserved for the enforced thing.
- Rejected: keeping "capability" — the old word would let the old asserted meaning survive the
  fix. `capability_scopes` stays as the YAML key (schema stability) but prose says "grant"
  only when something external enforces it.

### 6. Routing decision — **binding** (keep)
Which orchestrator serves a run: `state/llm-backends.yml` + `model.backend` +
`BindingResolver`, fail-closed, armed via `NOS_ARMED_BACKENDS`. Already named, already the
doctrine ("backends as BINDINGS, not providers", `docs/minimax-groundwork.md`).
- NOT: a "provider" — the estate explicitly retired that framing.
- Rejected: "route" — Traefik owns that word here.

### 7. Loop — **the loop** / **nos-loop** (keep); scheduled run — **ceremony** (keep)
The loop: weakness → proposal → judge → verdict → MR (`docs/idea/11-agentic-loop-contract.md`).
A ceremony: one scheduled agent run through `tools/run-agent.sh`. Both are estate words that
work. Organ, tendon, vein, bone, gate: all keep — they are the anatomy doctrine.
- NOT: the in-session grader iteration (that is explicitly a contract non-goal, contract
  §562-587).

### 8. Loop iteration — **cycle** (loop-level) vs **iteration** (session-level, keep)
One full propose(01:30) → drive(06:10) → review(06:50) pass of the loop's Pulse cadence is a
**cycle**. `agent_iterations` inside a session keeps **iteration** — it is a table name.
- Rejected: "round" — no anchor; "generation" — imports evolutionary-search framing the
  contract's non-goals refuse.

### 9. Proposal — **proposal** (keep); Verdict — **verdict** (keep)
`loop_proposals` / `loop_verdicts` with `CHECK (actor='engine:judge-runner')` (`ledger.py:323`).
The literature's nearest terms (candidate / fitness score) are worse: a verdict here is written
only by a code reader, which "fitness" does not imply. Keep the estate's words.

### 10. Gate / oracle — **gate** (keep), with one borrowed refinement
A gate is nOS's word for a code check that pins a fact. The literature's word for the same
thing when it decides success is **oracle** (SWE-Gym, arXiv:2412.21139: every task ships its
own unit tests; Batch 7). Usage rule: a *gate* pins shape at CI time; an *oracle* is the gate
run that writes `outcome_satisfied`. Same corpus (`state/judge-sets.yml`), two moments of use.
- NOT: a grader LLM. arXiv:2510.16657 (Batch 10, the corpus's strongest result): an imperfect
  verifier sharing the generator's identity plateaus and reverses.

### 11. The split — **plane**, not tier
The axis (Judge A §4, adopted): **what the gate corpus proves about.**
- **sere plane** (`nos-sere`) — gates are proofs about the estate's own declarations
  (ansible-lint, pytest tests/anatomy, nos-smoke, genome-codegen).
- **ops plane** (proposed name `nos-ops`; final name = questionnaire Q1) — gates are proofs
  about a client's operational data (labelled sample sets, reconciliations, exception rows).
- NOT: an RBAC tier (reserved), not a layer (L0–L3 is dependency-derived), not an F-tier
  (face-app complexity). "Plane" has settled infra semantics (control/data plane) and no
  collision in the repo.
- Rejected: "tier" — doctrine-reserved. "track" — used for work tracks (Track Q/H/J).
  "nos-bi" — names a domain (warehouse/CRM) on a different axis than nos-sere's relation
  word, and forecloses the operator's own embryo case: a client-side agent that also improves
  its estate would have no name (Judge A §4).

### 12. Shipping unit — **embryo** (keep, operator's word), defined
A prepared-not-armed nOS configuration for a market segment: agents + bindings + **sample
sets** (the ops plane's gate corpus, one per agent — an agent without one is refused by the
parser, exactly as a manifest without a GDPR block is refused today) + notification routing.
Arrives with `NOS_ARMED_BACKENDS` empty and every removal/merge path dry-run.
- NOT: a running system. The repo is not the running system; an embryo is a repo.

### 13. Maturity — **runner_status**, promoted to a schema enum
`unproven | scheduled | parked | deferred` (+ proposed `proven`: has at least one
oracle-written `outcome_satisfied`). Today prose-in-YAML rendered nowhere (local research §C).
Keep the field name; make it an enum in `agent.schema.yaml` and a rendered fact.
