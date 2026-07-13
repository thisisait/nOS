# KEAP Curator — a recursive self-improving taxonomy reconciler

**Status:** P0 BUILT (2026-07-14), awaiting deploy + first run.

> ### P0 build state (2026-07-14)
> **Implemented, committed, gates green — NOT yet deployed/run.**
> - **nos-keap `feat/curator`** (commits `74bf84a` work-log+frontier API, `794a1dd` anchor):
>   `curator_runs`+`curator_visits` in `server/db.ts` SCHEMA[] + accessors
>   (`curatorVisitMap`/`start`/`finishCuratorRun`/`recordCuratorVisit`); agent routes
>   `GET /agent/v1/curator/anchor` (L0-2 frame, §7), `GET .../frontier` (staleness-first,
>   cooldown-skipped), `POST .../run/start|finish` + `.../visit`. desc rewrites ride the
>   existing `proposeDescription` seam — zero new proposal seams. tsc + `build:server` clean.
> - **nOS `dev`** (commits `4b9aac78` profile+runner+client, `6785b4e2` anchor wiring):
>   flat `files/anatomy/agents/curator.yml` (sweep procedure, house style, propose-only,
>   `NOS_AGENT_EXIT` sentinel, paused `curator-sweep` Pulse job); AgentKit
>   `curator/{agent.yml,system.md,rubric.md}` (passes `test_agent_schema` +
>   `test_agent_exit_semantics`, `emits_sentinel=true`); `tools/run-curator.sh`;
>   `nos-curator` Authentik client + `curator_wing_api_token`. Full anatomy suite 1778 pass.
> - **The linter in P0 is the agent's LLM judgment** guided by the system prompt (house-style +
>   boundary lint over the frontier). Deterministic `lint.ts` checks (stub-description,
>   name-hygiene, relation-desert, cross-domain-bridge-candidate, misparented) are **P1** —
>   they drive node-edit/relation proposals whose seams don't exist yet.
>
> **Remaining to first-run (the 04:40 timer's job):** FF `feat/curator`→`main` on nos-keap →
> annotated tag **`v1.4.0`** → bump nOS `keap_repo_ref`+`keap_version` to `1.4.0` →
> `tools/nos-stacks.sh keap` (rebuild image; `initDb` creates the two tables) → a targeted
> playbook run so the `curator-sweep` Pulse job + `nos-curator` client land in wing.db →
> **backup KEAP db first** (`docker exec iiab-keap-1 sqlite3 /app/data/keap.db ".backup …"`) →
> `bash tools/run-curator.sh --dry-run` then a real `tools/run-curator.sh`. Verify
> `curator_runs`/`curator_visits` rows + desc proposals in Admin › Moderace as
> `proposed_by=agent:curator`. Container `iiab-keap-1` is healthy as of the build.

**Original author trigger:** operator wants an autonomous
overnight agent that walks the KEAP taxonomy from L≥3, acts as (1) an advanced
linter and (2) a node repairer, and proposes *edit / create / delete / rewire*
changes into the moderation panel for approval — polishing the DB and re-embedding
whenever tokens are spare, as a "most thoughtful recursive self-improving loop."

---

## 1. Name

The agent is the librarian's more active sibling: the librarian *fills* (briefs,
describes, judges lint); this one *reshapes* (lint → propose rename / rewrite /
rewire / renumber / create / delete). Shortlist:

- **Curator** *(recommended)* — tends the collection, decides what belongs and how it's presented. Clean, museum/gallery metaphor, sits naturally beside `librarian`.
- **Cartographer** — refines the *map* of the knowledge cosmos; ties to the cosmology explorer (stars/nebulae) and the relation web.
- **Gardener** — prunes, grafts, tends "grown stars"; matches the `taxonomy_nodes_ext` "grown node" language.
- **Reconciler** — the operator's own coinage; evokes reconciling the map with reality. Slightly ops-flavored.

Recommendation: **`curator`** (agent id `curator`, identity `agent:curator`,
Authentik client `nos-curator`). This doc uses `curator` throughout.

## 2. Identity — new sibling, reuse the librarian machinery

**Do NOT overload the librarian.** The librarian's contract is *fill + judge,
never modify* (`librarian.yml:173` "Never delete or modify… you judge, humans
merge"). The curator's whole point is to *propose modifications*. Keep them
separate; the curator **reuses**:

- the flat-profile runner path (`pulse-run-agent.sh` → `claude --system-prompt`),
- the `/agent/v1` RW token + `mcp-keap` tool,
- the `promotions` table as the proposal bus,
- the `ModerationPanel` as the approval surface,
- the nightly `embed-sync → lint` re-embedding cadence.

Ship both a flat `files/anatomy/agents/curator.yml` (live runner spec, like
librarian's) **and** an AgentKit `files/anatomy/agents/curator/{agent.yml,
system.md,rubric.md}` (contract, validated by `test_agent_schema.py`).

## 3. The recursive self-improving loop

One overnight **run** = many **passes**; one pass = a batch of node **visits**;
each visit = lint → (maybe) propose → checkpoint. The loop is *recursive*
because approved proposals re-embed → sharpen semantic neighborhoods → improve the
next pass's lint + relation judgments, and rejected proposals teach taste.

```
run(budget):
  load cursor + house-style memo + recent approve/reject outcomes
  while budget.remaining() and not backpressure():
     batch = next_nodes()                 # §4 traversal
     for node in batch:
        facts   = mcp-keap GET node + ancestors + children + relations + embedding-neighbors
        findings = LINT(node, facts)      # §5.1 deterministic + LLM
        propose  = REPAIR(node, findings) # §5.2 → promotions (moderated)
        write curator_visits row (cursor, findings, proposals, cost)
     if surplus and queue_not_flooded:
        POLISH()                          # §6 re-embed stale, tighten, add cross-links
  write curator_runs summary; emit A9 if proposals await
```

Nothing auto-applies. Every change is a **proposal** in the operator's
moderation panel (ties to memory `feedback-destructive-op-safety` +
`agents-drive-operator-supervises`).

## 4. Traversal — systematic sweep + ε random hops

- **Frontier:** all nodes with `level ≥ min_level` (default **3** = the votable
  zone and below; L0–2 are the anchor core, handled in §7).
- **Order:** staleness-first — never-visited, then oldest `last_visited_at`
  (from the work-log). "From zero" ⇒ first index visits every L≥3 node in id
  order (root-first, mirrors the librarian brief sweep).
- **ε random hops** (`epsilon_random_hop`, default 0.1): with prob ε, jump
  instead to a random node biased toward *low quality* (short desc, no relations,
  stub name) or *high connectivity* (hub nodes whose fixes ripple). Serendipity +
  cross-pollination the linear sweep misses.
- **Cooldown:** a node isn't revisited within `revisit_cooldown_days` (default 14)
  unless it changed (content-hash moved) — keeps re-runs cheap and convergent.

## 5. The two roles

### 5.1 Advanced linter (extends `server/lint.ts`)
Deterministic checks (cheap, run in the script, no LLM) + LLM judgment. New
checks beyond the existing registry (`note-on-unknown-node`, `broken-anchor`,
`near-duplicate`, `orphan-object`, `embedding-backlog`, …):

- **stub-description** — desc < N chars or template-ish ("… an approach to …").
- **name-hygiene** — casing, ampersand/entity residue, redundant parent-prefix.
- **ordinal-gap / mis-sort** — sibling `ordinal` gaps or non-topical ordering.
- **relation-desert** — a well-embedded L≥3 node with 0 typed relations (the
  reconciler's richest signal — most of the map is within-domain-only today).
- **cross-domain-bridge-candidate** — high embedding similarity to a node in
  another domain with no relation between them (math↔physics↔chem↔bio bridges).
- **duplicate-subtree / near-synonym-node** — two nodes that should merge.
- **misparented** — a node whose embedding sits closer to a different parent.

Findings land in `lint_findings` (stable `id=sha1(check+refs)`, existing
lifecycle). The LLM only adjudicates the ambiguous ones (like the librarian's
overlap-review), keeping token cost down.

### 5.2 Node repairer (proposals)
For each actionable finding the curator emits a **proposal** carrying
`{rationale, evidence, confidence, diff}`. Proposal kinds (⚠ = new app-side seam
to build, §8):

| kind | action | seam |
|---|---|---|
| `desc` / `brief` | rewrite description / brief | **exists** |
| `node` | create a missing child/sibling | **exists** (zone-gated) |
| `node-edit` ⚠ | rename / re-describe / renumber (ordinal) an existing node | new |
| `node-delete` ⚠ | delete / merge a redundant or wrong node | new |
| `relation` ⚠ | add / retype / remove a `concept_relations` edge | new |
| `anchor-edit` ⚠ | propose a change to an L0–2 node (§7) | new, high-scrutiny |

Only proposals with `confidence ≥ proposal_confidence_floor` are queued, capped
at `max_proposals_per_run` so the panel never floods.

### 5.3 Cross-domain relation weaver (a first-class curator edit)
The deep-import epic (memory `keap-domain-deep-import-epic`) grafted math, chem,
and bio to physics-level depth, but **every domain's relations are within-domain
only** — math has no edge to the ToE physics cluster, chem none to bio, etc. That
missing inter-domain web is the real "AI brain" payoff, and closing it is an
**explicit curator responsibility**, not a byproduct of polish:

- **What it edits:** `relation`-kind proposals (§5.2 / §8.3) whose `from` and `to`
  live in *different top-level domains* — the math↔physics↔chem↔bio bridges (and
  any future domain pair: CS↔math, earth-sci↔physics, …).
- **How it finds them:** the `cross-domain-bridge-candidate` lint check (§5.1) —
  high embedding similarity across a domain boundary with no existing edge — is
  the primary signal; ε random hops (§4) biased toward hub nodes surface the rest.
  Every proposal carries the concrete bridge rationale (shared structure /
  shared-math / duality / limit / conflict) as its typed `type`, same palette the
  ToE overlay already renders.
- **Guardrails:** cross-domain proposals are tagged `scope=cross-domain` and
  counted under a **separate cap** `max_cross_domain_proposals_per_run` (default
  15) so a single run can't flood the panel with speculative bridges; they favor
  `explored=barely` (frontier) so the operator sees them as hypotheses to confirm,
  not settled facts. `enable_cross_domain_relations` (default **true**) gates them.

This makes weaving the inter-domain graph a named deliverable of the curator, land-
ing in P1 alongside the `relation` seam (§13) — the sweep doesn't just clean each
domain in isolation, it stitches them into one navigable cosmos.

## 6. Token-surplus polish + re-embed
When a sweep pass finishes with budget left (or the queue is at back-pressure and
awaiting the operator), switch to **polish mode**:

1. **Re-embed** — drive `keap-embed-sync` for any `markCorpusDirty` backlog so the
   next pass reasons over fresh vectors.
2. **Tighten** — micro-`node-edit` proposals that sharpen already-decent
   descriptions toward the house style.
3. **Weave** — `relation` proposals for the strongest missing typed cross-links,
   prioritizing **cross-domain bridges** per §5.3 (the real "AI brain" payoff).
4. **Re-lint** — `POST /agent/v1/lint/run` to surface what the fresh state reveals.

## 7. L0–2 anchor core — in the system prompt, proposable
The anchor tree (L0–2) is **rendered into the curator's system prompt** as the
fixed reference frame, so every judgment stays consistent with the top ontology
(and it's small — ~a few hundred nodes). The curator **may** propose changes to
L0–2, but as `anchor-edit` proposals — a distinct high-scrutiny class, because an
anchor change alters the U1 layout bake (existing stars re-bake, `layoutVersion`
moves) and must be rare + deliberate. `enable_anchor_proposals` defaults **false**.

## 8. App-side seams to build (KEAP)
The librarian proved the propose→moderate→materialize loop for `node/desc/brief`.
The curator needs three more, each = *propose fn + materialize fn in
`promotions.ts` + `decide()` dispatch branch + `/agent/v1` RW POST +
`ModerationPanel` render case*:

1. **`node-edit`** — `materializeNodeEdit(node_id, {name?, description?, ordinal?})`
   updates `taxonomy_nodes_ext` (or `node_descriptions`) + `markCorpusDirty`.
2. **`node-delete`** — `materializeNodeDelete(node_id, {mode: delete|merge_into})`;
   refuses if the node has approved children unless `merge_into` reparents them;
   **zone-guarded** (anchor refuses, like `proposeNode`).
3. **`relation`** — the missing `concept_relations` write path:
   `materializeRelation({from,to,type,explored,op: add|retype|remove})` with
   `source='agent:curator'`. (Today `concept_relations` is written only by the
   internal seed importer — `db.ts:1393`.) Either a `kind='relation'` promotion
   **or** a guarded RW endpoint `POST /agent/v1/relations` (proposal-mode).

All edits/deletes stay **proposal-only** (no auto-apply); approval remains
admin-only via `POST /api/promotions/:id/decide`.

## 9. Work-log DB tables (KEAP schema-extensions)
- **`curator_runs`** — `run_id, started_at, ended_at, params_json, budget_tokens,
  tokens_spent, nodes_visited, proposals_made, proposals_approved, status`.
- **`curator_visits`** (the cursor + progress) — `node_id, run_id, pass,
  visited_at, content_hash, findings_count, proposals_count, action`. Resume =
  read the max cursor; staleness order = `ORDER BY visited_at NULLS FIRST`.
- **House-style memo** — a single `agent_memory_stores` row (the AgentKit Dreams
  table) the curator maintains: distilled operator taste from approve/reject
  history, injected into the next run's context (the recursive-learning signal).

## 10. Recursive self-improvement signals
- **Approve/reject feedback:** each run reads recent `promotions.status` for
  `proposed_by='agent:curator'`; rejected proposals become negative exemplars +
  update the house-style memo. Convergence: the curator proposes less of what the
  operator rejects.
- **Re-embed compounding:** approved edits → fresh vectors → better neighborhoods
  → better next-pass relation/misparent judgments.
- **Self-tuning (gated):** the curator may propose edits to its *own* rubric /
  param defaults as a special proposal — meta-improvement, `enable_self_tuning`
  default false.

## 11. Autonomy / overnight wiring
A Pulse job in `keap-base` plugin (`pulse:jobs:`), sibling of `keap-embed-sync`:

```yaml
- name: curator-sweep
  command: "{{ playbook_dir }}/tools/run-curator.sh"
  schedule: "30 1 * * *"          # 01:30 — long night window before 04:15 consolidate
  max_runtime_s: 9000             # ~2.5h wall budget (parameterizable)
  max_concurrent: 1
  paused: true                    # on-demand doctrine; operator flips on
  env: { KEAP_API_URL, KEAP_AGENT_TOKEN_RW, NOS_AGENT_*, WING_*, OLLAMA_URL }
```

`tools/run-curator.sh` mirrors `run-librarian.sh`: KEAP health pre-flight → source
env → loop `pulse-run-agent.sh` in budget-bounded batches, checkpointing
`curator_visits` between batches so a kill/OOM resumes cleanly. Exit contract same
as librarian (`0` clean, `1` proposals await moderator, `2` pre-flight fail),
propagated via the `NOS_AGENT_EXIT:` sentinel.

## 12. Parameterization (agent.yml `metadata` + job env)
`min_level`(3) · `max_level`(9) · `epsilon_random_hop`(0.1) ·
`revisit_cooldown_days`(14) · `proposal_confidence_floor`(0.7) ·
`max_proposals_per_run`(40) · `token_budget` / `max_runtime_s` ·
`enable_node_edit`(true) · `enable_node_delete`(**false**) ·
`enable_relation_proposals`(true) · `enable_cross_domain_relations`(true) ·
`max_cross_domain_proposals_per_run`(15) · `enable_anchor_proposals`(**false**) ·
`enable_self_tuning`(**false**) · `polish_when_surplus`(true) ·
`reembed_on_surplus`(true) · `subtree_scope`(e.g. `02.01.04` to sweep one domain) ·
`lint_checks`(per-check on/off) · cost tiers `model_lint`(haiku) /
`model_repair`(sonnet) / `model_anchor`(opus).

## 13. Phasing
- **P0 (read-only pilot):** curator agent + work-log tables + traversal + linter,
  emitting `desc`-kind proposals only (reuses existing seam). Proves traversal,
  cursor, cost, taste — zero new app-side risk.
- **P1 (repair):** build `node-edit` + `relation` seams (§8.1/§8.3) + panel cases;
  enable rename/redesc/renumber + relation weaving, including the §5.3 cross-domain
  bridge weaver as a named P1 deliverable (math↔physics↔chem↔bio).
- **P2 (structural):** `node-delete`/merge seam, guarded + off by default.
- **P3 (recursive):** house-style memo, approve/reject learning, `anchor-edit`,
  self-tuning — the full self-improving loop.

## 14. Safety recap
Propose-only; deletes + anchor edits off by default + zone-guarded; per-run
proposal cap; every action audited as `actor_id=agent:curator`,
`actor_action_id=<run uuid>` (AgentKit lineage); operator supervises via the
moderation panel. The agent drives *through the machinery*, never pokes the live
DB (memory `machinery-purpose-and-no-hacks` + `agents-drive-operator-supervises`).
