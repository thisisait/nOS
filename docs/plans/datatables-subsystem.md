# DataTables as a first-class subsystem — the spec

**Status: spec, authored 2026-09-04. The last non-dtt spec by design — from here
the working contract lives in a DataTable, not a prose file.**

This is the authoritative plan for turning nOS's own working surfaces (roadmap,
ideas, currentState, active-work, face-layouts, and — under question — the
constitution) into a governed, RBAC'd, agent-ergonomic **DataTable subsystem**,
whose centerpiece is a live **`currentState`** table that many agents work on
in parallel. It absorbs and re-frames six roadmap rows that already exist
(`tables`, `kpro-table-access`, `kpro-ids`, `tables-system-flag`,
`plat-active-work-datatable`, `face-planner`) and adds the three pieces the
operator named on 2026-09-04 that none of them cover: a per-principal
share/RBAC model, an agent-ergonomic MCP harness, and a readable seed format.

## 1. The vision in one paragraph

nOS's meta-work — what is planned, what is in flight, what each agent is doing
right now — stops living in single-writer prose files (`roadmap-seed.py`'s
2000 lines, `active-work.md`, scattered `docs/idea/*.md` + `technosideas/*.md`
+ an ungoverned 55-row KEAP "ideas" table) and becomes a small set of
**DataTables** with one uniform access surface. The centerpiece, **`currentState`**,
is a unified contract/spec — a mini-roadmap of the work in flight — that
**Cursor, Claude Code, Codex, AgentKit (MiniMax), and local models** can all
read and write, optimally in parallel, without stepping on each other. It is
visualized in the `nos-cc` pane (TUI) and the face (web), and governed by the
constitution (apex).

## 2. The centerpiece: the `currentState` contract

`currentState` is where "who is doing what, against which plan step, right now"
lives. It is NOT the roadmap (the durable plan) and NOT active-work-as-prose;
it is the **live claim board** that binds a running agent to a roadmap step.

Each row is one work item:

- **`id`** — opaque + stable (see §5, `kpro-ids`): survives a rename/move.
- **`roadmap_ref`** — FK to ≥1 roadmap step. A currentState row with no
  resolvable step is refused (the join is the point — the operator's ruling on
  `plat-active-work-datatable`).
- **`task_type`** — the enum that routes the work (see §7): e.g. `code-fix`,
  `investigate`, `review`, `seed-edit`, `converge`, `design`, `doc`. Drives
  which agent/tool the planner assigns and which tools that agent should reach
  for. **This enum must be DESIGNED — it may not exist yet, and it is the key
  to nos-planner.**
- **`claim`** — who holds this row NOW (agent principal or human) + a lease
  timestamp. This is what lets several agents work the board in parallel
  without two grabbing the same item: claim-then-work, lease expires, no lock
  server. (Same shape as the AgentKit run lock, one level up.)
- **`status`** — claimed / in-progress / blocked / for-review / done. A CLAIM,
  written by whoever does the work; the *verification* is a separate column
  (the roadmap's status/verified split, kept here).
- **`evidence`** — a pointer to the artifact that proves the work (a commit, a
  gate run, a fee file) — never the attempting agent's own say-so (the estate's
  reader-not-writer rule).
- **`owner` / `visibility` / `shared_with`** — the access facet (§4).
- **`body`** — the work item's own notes; a short prose field, per-row (§6).

The invariant that makes parallel work safe: **one row = one file = one claim.**
Two agents editing two rows never conflict (per-row-file seeds, §6); two agents
never hold the same row (the claim lease); and neither can mark a row `done`
without the evidence column pointing at something a reader can check.

## 3. Pillar: the engine belongs to nOS (`tables`)

Today the DataTable DEFINITIONS live in nOS git (`state/keap-tables/*.table.yml`,
18 of them, gated by `test_keap_table_concepts.py`) but the ENGINE — store,
row upsert, row history, ref integrity, card/graph materialisation — lives in
KEAP. Operator direction 2026-08-31: the engine belongs to nOS and KEAP depends
on it like anything else. This is a move of the engine, not the vocabulary, and
it is the "mandatory system component" half: the DataTable engine is always
installed, and the meta-tables (roadmap/ideas/currentState) are **seeded on
every converge**, idempotently — not by a tool a human remembers to run.

## 4. Pillar: per-principal RBAC and sharing (the real gap)

Today a table carries one coarse `visibility:` field (roadmap = `tier-managers`).
There is no per-row RBAC, no owner, and no way to share a table or a row with a
specific user or a specific agent. This is the same shape as
`cortex-caddy-transcript-visibility` (operator ruling: visibility must be a
configurable GRADE set, not one hardcoded constant) — solve them with one
model:

- **`owner`** — the principal that created the row (user or agent id).
- **`visibility`** — a GRADE from an enum (`private` / `owner` / `tier-<n>` /
  `system` / `public`), not a single tier constant.
- **`shared_with`** — an explicit ACL: a list of principals (users AND agents)
  granted read or write, independent of tier. This is what "sharing with
  another user, and I think with agents too" means, and nothing today has it.

Both doors — the human door and the agent MCP — MUST honor the same model. A
share that only the human UI respects is not a share.

## 5. Pillar: stable opaque ids (`kpro-ids`)

A row's identity must survive being moved, renamed, or re-parented. Today some
ids are physical (`fs:<uid>:sha1(relPath)`), so moving the source forks the
corpus silently. KPro's docId is opaque and stable; the path is an ATTRIBUTE.
currentState and every meta-table adopt the opaque id — cheap now, expensive
per row later, so it is the first child to land.

## 6. Pillar: seeds are per-row files (readability + parallel-safety)

The single thing that makes "beautifully clear seeds" and "several agents work
in parallel" the SAME fix: **one row = one file**, markdown + frontmatter, like
the estate already does for memory (`memory/*.md`), devlog
(`docs/devlog/.../*.md`) and hidden fees (`docs/hidden_fees/*.md`). Frontmatter
carries the git-owned columns (title, parent, track, task_type, roadmap_ref);
the body is the prose. Benefits, all of them the operator asked for:

- **Readable** — a row is a short file, diffable, reviewable in isolation. The
  opposite of `roadmap-seed.py`'s giant inline strings (which broke twice under
  hand-editing on 2026-09-04).
- **Atomic for parallel agents** — two agents editing two rows touch two files;
  no merge conflict, no single-writer bottleneck (`active-work.md`'s 150-line
  gate was a symptom cap, not a fix).
- **The seeder becomes a reader-of-files**, not a monolith. Status/verified
  stay table-owned (moved by `roadmap-update.py`); title/body/refs stay
  git-owned (the files); `--sync` reconciles, exactly as roadmap does today.

## 7. Pillar: task-types + the minimalistic CLAUDE/AGENTS.md

The operator wants nOS to have a **minimalistic CLAUDE/AGENTS.md** giving clear,
small instructions on **which tools to use per task type** — and suspects the
task types are not yet designed. They are the load-bearing input to nos-planner.

- **Design the `task_type` enum first.** Candidates from how work actually flows
  here: `investigate` (read-only, returns findings), `code-fix` (edit + gate +
  retro), `seed-edit` (a per-row file change), `review` (adversarial verify),
  `converge` (operator-run, tagged), `design` (spec, no code), `doc`,
  `security-remediation`. Each type declares: the tools it may use, whether it
  writes, whether it needs the operator, and its "done" evidence shape.
- **CLAUDE/AGENTS.md shrinks to a router**: for task_type X, use tools Y, obey
  invariant Z, file evidence W. The current CLAUDE.md is a 600-line estate
  encyclopedia — keep that as reference doctrine, but the per-task tool contract
  is small and belongs where a dumb agent reads it first.
- This is what lets a "dumber" agent (MiniMax, a 3B local model) work the board:
  it reads its claimed row's `task_type`, looks up the tiny contract, and knows
  exactly which tools to reach for and what "done" means.

## 8. Pillar: two MCP consumers (the light harness)

"Do we have MCP?" — yes, several in-process AgentKit tools (`McpKeapTool`,
`McpWingTool/Read/Write`, `McpBoneTool`, `McpLoopTool`), but **none writes
DataTables** (KEAP's POST allowlist excludes `tables/rows`), and the raw door is
upsert-on-slug (silent dupes for slug-less tables) with no PATCH/PUT. So the
harness is two surfaces over ONE store:

1. **`McpTablesTool`** (in-process, AgentKit) — for MiniMax/local agents. A tiny
   verb set: `list-tables`, `read-rows`, `get-row`, `claim-row`, `upsert-row`,
   `patch-field`, `release-row`. Uniform across every table, RBAC-honoring,
   returns clean structured data. The agent never needs to know KEAP vs
   git-owned vs table-owned columns.
2. **A standalone MCP server** (stdio/SSE) — for **external** coding agents that
   speak MCP but do NOT run inside AgentKit: **Cursor, Claude Code, Codex**.
   Same verbs, same RBAC, same store. The estate already runs an **MCP Gateway
   (mcpo)** in the iiab stack — the likely host for exposing the DataTables door
   as MCP to external agents. This is the piece that makes "cursor, claude,
   codex work on it in parallel" literally true.

Both sit on the **fixed CRUD door** (`kpro-table-access`): GET/POST/PATCH/PUT/
DELETE on `/…/tables/<t>/rows`, keyed on the opaque id, not upsert-on-slug.

## 9. The constitution: revision, and whether it becomes a dtt

The operator wants to start with a **big revision of the constitution**
(`files/anatomy/apex/ruling.yml`) and asks whether to seed it into a dtt.

- **Revision**: the constitution should get the minimalistic-router treatment
  (§7) — clear, small, task-type-aware — while its heavier doctrine stays as
  reference.
- **Seed it into a dtt?** Possible and attractive (one governance surface for
  everything), BUT the constitution is **signed and immutability-load-bearing**:
  a row that IS the constitution must carry the signature discipline (the apex
  digest, re-signed only by the operator, gated by
  `test_apex_serving_is_signature_gated`). A signed dtt row is a real design —
  the signature covers the row's canonical form, and the seeder may add rows but
  never re-sign. RECOMMENDATION: treat "constitution as a dtt" as a LATER child
  of this epic, after the RBAC/sharing model exists (a signed row is a special
  case of an owned, write-restricted row) — do not block the epic on it.

## 10. Visualization

`currentState` (and the roadmap) render in two places, both reading the same
store:

- **`nos-cc` pane** (TUI, `tools/cc/panes/`) — a claim-board pane: rows by
  status, who holds what, what is stale. A reader that re-runs, per the pane
  doctrine (a tailed log looks healthy until its writer stops).
- **The face `nos-planner` app** — board / tree / timeline over the tables
  (`face-planner` already names this; `circle` (MIT) supplies two of the three
  readings). This is where a human assigns/re-prioritizes and watches the
  agents work.

## 11. nos-planner

The planner routes work from `currentState` to agents by `task_type`, and lets
a human assign/re-prioritize. Operator note: it may **first just live in the
roadmap/currentState tables themselves** (a claim + task_type + owner is already
a routable assignment) — the face app is the visualization, not the mechanism.
Design the routing (task_type → eligible agent kind → its tool contract) before
the UI.

## 12. Sequencing

Already on the roadmap, re-parented under this epic:
`kpro-ids` (do first, cheap now) · `tables` (engine → nOS) ·
`kpro-table-access` (CRUD door) · `tables-system-flag` (system-class facet) ·
`plat-active-work-datatable` (→ currentState) · `face-planner` (UI).

New children this spec adds:
- **`dtt-share-model`** — per-principal owner/visibility-grade/shared_with,
  honored by both doors (shares the grade enum with caddy-visibility).
- **`dtt-mcp-harness`** — `McpTablesTool` (in-process) + the external MCP
  server via mcpo (Cursor/Codex/Claude Code). The operator's PRIORITY and the
  cheapest high-value start once the door is fixed.
- **`dtt-seed-per-row-file`** — the markdown+frontmatter seed format; the
  readability + parallel-safety fix.
- **`dtt-task-types`** — the `task_type` enum + the minimalistic CLAUDE/AGENTS.md
  per-task tool contract; the input to nos-planner.

Suggested order: **task-types + share-model** (the two contracts everything
else honors) → **CRUD door + McpTablesTool** (unlock agent writes, the
priority) → **per-row-file seeds** (migrate roadmap first, prove it) →
**currentState** (the claim board) → **engine → nOS** + **external MCP server**
+ **Planner UI** → **constitution-as-dtt** (last, signed-row special case).

## 13. Open questions for the operator

1. **Naming**: a `class: system` FACET (my recommendation — no ref churn) vs a
   hard rename to `nos-dtt-*` (routed through the migration framework if truly
   wanted). The names capture a real category; the facet delivers the same
   governance without a migration.
2. **task_type enum**: is the candidate set in §7 right, and who owns adding a
   type — is it itself governed (a proposal), or free for any agent?
3. **External-agent identity**: Cursor/Codex hitting the MCP server need a
   principal for the RBAC/claim model. One shared "external-coding-agent" id, or
   per-tool ids? (This is the same identity question `identity.md` already
   answers for AgentKit clients — extend it.)
4. **Constitution-as-dtt**: agreed to defer to a signed-row child, or start the
   signature-in-a-row design earlier?

## 14. Operator decisions (2026-09-04) — supersede §13's open questions

1. **Naming — FACET, decided.** `class: system` facet, not a rename. No ref
   churn; delivers `tables-system-flag` (hide by default) for free.
2. **`task_type` — in code, PROPOSABLE.** The enum lives in code (the source of
   truth), and adding a type is a **proposal** through the loop (governed, not
   free-for-any-agent). So a new task_type is a reviewed change, same as any
   code contract.
3. **Access — declared per table, granular per (task_type × tool).**
   - **System tables**: each declares its OWN agent access — not one blanket
     policy. Per system table, per task_type, per tool.
   - **User tables**: same shape, and also **mostly in code** (the access is a
     code-declared contract on the table definition, not runtime UI config).
   - **Future — a separate access-rules dtt.** Fine-tuning per (table × user)
     with **regex rules** may become its own DataTable (`dtt-access-rules`) —
     the code-declared access is the floor, the rules table the per-deployment
     override. Deferred; a dig-deeper child.
4. **Constitution-as-dtt — deferred, but ON the roadmap** as a dig-deeper
   (`dtt-constitution`). Leave apex as-is for now; the signed-row design is a
   later child once the share model exists.

## 15. The routing address — a capability-addressed graph (operator idea, 2026-09-04)

The operator wants the planner (for the roadmap, but it MUST serve other
business logics too) to build a **graph of work-assignment addresses**,
URL-like. My reading of the sketch (stated so it can be corrected):

```
<WHERE>/<WHO>/<KAM/TARGET>/<CO/WHAT>/<KDY>
  WHERE  execution locus     : eu-cloud | ext-cloud | local        (which HW/tier runs it)
  WHO    principal           : <agent-type>/<agent-name>           (or a human)
  KAM    access scope (target): all | internet | repo | fs-dir | dtt | keap | cortex | …
  CO     task_type           : the §7 enum
  KDY    when                : schedule / trigger / deadline
```

Why this is powerful, and what it unifies — it is ONE grammar for two things
the epic otherwise builds separately:

- **A capability** (what an agent MAY do): a WHERE/WHO/KAM/CO tuple an agent
  holds — e.g. `local/agentkit:minimax/repo+dtt/code-fix` = "MiniMax, running
  locally, may do code-fix work touching the repo and DataTables." This IS the
  §4 RBAC/share model, expressed as an address instead of a column set.
- **An assignment** (what a currentState row NEEDS): the same shape on the work
  item. The planner MATCHES assignments to capabilities — prefix/glob matching
  on the address (`local/*/repo/code-fix/*`) is a readable, queryable router.

It is URL-like on purpose: hierarchical, human-legible, and glob-matchable, so
"who can do WHAT on WHERE touching KAM" is a path query, and the planner's
"graph" is the tree of these addresses with agents/work-items as leaves. It
connects cleanly to what already exists: WHERE ↔ the cloud/local execution
tiers and ADR-0003 network boundaries; WHO ↔ identity.md principals; KAM ↔ the
tool/scope model (bash.read, dtt.write, keap.read…); CO ↔ task_type; KDY ↔
Pulse.

**Open (for after compact — I may have read the sketch wrong):**
- Is the address a PERMISSION grammar, an ASSIGNMENT grammar, or (my reading)
  BOTH, matched by the planner?
- Is KAM a SET (touches repo AND dtt) or one target per address?
- Does WHERE encode a hard placement constraint (must run local) or a
  preference the planner optimizes?
- Is the separator really `/` (a real URI, routable/greppable) or just the
  mental model? A real URI scheme (`nos-work://…`) would make it addressable
  by tools and logs.

This belongs to nos-planner and is filed as `dtt-routing-address` (design-first,
dig-deeper) — it may become the spine of both the planner AND the access model.
