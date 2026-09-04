# Kickoff brief — give nOS's DataTables one semantic, parallel-safe door

**For the agent picking up the `dtt` epic. Read the full spec first:
`docs/plans/datatables-subsystem.md`. This brief is the first movement — the
operator's priority — framed to be worth your attention, with the research the
build hinges on.**

## The mission, in one breath

nOS already keeps its own meta-work in DataTables (roadmap, apps, systems,
layouts, 18 in all). But an agent cannot really WORK them: the write door is an
upsert keyed on `slug` that silently duplicates any slug-less table, no MCP
tool writes tables at all, there is no way to find a row by MEANING, and there
is no per-principal access. Your mission: **make every agent — Cursor, Claude
Code, Codex, AgentKit/MiniMax, a local model — able to read, semantic-search,
claim and write nOS's DataTables through ONE tiny, uniform, RBAC-honoring
surface.** When you are done, a "dumber" agent asks *"what open work is about
the loop's WAL races"* and gets the row, claims it, and updates it — without
knowing a single column name.

This is the piece that turns the whole `currentState` vision (many agents
working one board in parallel) from a diagram into a thing that runs.

## What is already true — do not re-buy it (verify, then build on)

- The DataTable DEFINITIONS live in nOS git: `state/keap-tables/*.table.yml`
  (gated by `test_keap_table_concepts.py`). The STORE / upsert / row history /
  ref integrity / card materialisation live in KEAP.
- **libSQL is in the stack FOR VECTORS.** `roadmap`, `apps`, `systems` already
  declare a `kind: vector` column (dim 768); `keap-embed-sync` (a Pulse job)
  embeds the corpus; `GET /agent/v1/search/semantic?q=` is a live vector search
  over the libSQL corpus. Confirm whether that search already covers TABLE ROWS
  or only knowledge objects/taxonomy — that answer changes your search work
  from "wire it" to "extend it".
- There ARE MCP tools already (`files/anatomy/wing/app/AgentKit/Tools/`):
  `McpKeapTool`, `McpWingTool/Read/Write`, `McpBoneTool`, `McpLoopTool`. Read
  `McpKeapTool.php` — its `POST_ALLOWLIST` is the pattern to follow, and it is
  ALSO the proof of the gap: `tables/rows` is not in it.
- The MEASURED defects you are fixing (row `kpro-table-access`): the agent door
  `/agent/v1/tables/<t>/rows` is upsert-on-`slug` → a slug-less table gets
  silent DUPLICATE inserts; the human door answers GET+DELETE and 404s PATCH
  and PUT. So today a slug-less table is write-once from every automated door.

## The research that the build hinges on — settle these first, in writing

These are the interesting parts. Each has an existing estate position; your job
is to confirm it, not re-open it from zero.

1. **The two consumers, one store.** AgentKit agents (MiniMax/local) get an
   IN-PROCESS `McpTablesTool`. External coding agents (Cursor, Codex, Claude
   Code) speak MCP but do NOT run inside AgentKit — they need a STANDALONE MCP
   server (stdio/SSE). The estate already runs an **MCP Gateway (mcpo)** in the
   iiab stack. RESEARCH: can mcpo expose the fixed CRUD door as an MCP server to
   external agents, or does that need a small dedicated server? Both must hit
   the SAME store and honor the SAME access model.

2. **The "no confident match" floor — non-negotiable.** A cosine top-k ALWAYS
   returns k rows; the estate's cardinal sin is absence rendered as a result.
   `cortex-resolve.ts` already refuses RRF scoring on exactly these grounds, and
   the roadmap row `cortex-graph-borrowings` sets the doctrine: **embeddings are
   a RESOLVER (text → row id), never the store of relations, and the resolver
   MUST be able to return nothing.** So `search-rows` returns an EMPTY result
   below a declared threshold — a real negative — not the nearest wrong row.
   RESEARCH: where does the threshold live, and read `cortex-resolve.ts` /
   `cortex-ann.ts` for how the estate already draws this line.

3. **Embed-on-write freshness.** A row edited but not re-embedded is STALE, and
   the rot is INVISIBLE (the source changed, the vector did not, no date to
   compare). RESEARCH: does the write path re-embed on upsert, or does it lean
   on the nightly `keap-embed-sync`? A row a human just edited and an agent
   immediately searches for must be findable — decide the freshness contract.

4. **The access model it must honor (`dtt-share-model`).** Access is DECLARED
   PER TABLE, granular per (task_type × tool) — decided by the operator
   2026-09-04. `owner` + a `visibility` GRADE enum (private/owner/tier-N/system/
   public) + a `shared_with` ACL of principals (users AND agents). BOTH doors
   honor the same model — a share only the UI respects is not a share. Same
   shape as `cortex-caddy-transcript-visibility`. RESEARCH: start from the one
   coarse `visibility:` field tables carry today and design the grade + ACL as
   TABLE metadata (the seam `tables-system-flag` also needs).

5. **The verb set, and why it stays tiny.** `list-tables`, `read-rows`,
   `get-row`, `search-rows`, `claim-row`, `upsert-row`, `patch-field`,
   `release-row`. The whole point is a "dumber" agent never learns KEAP-vs-git-
   owned-vs-table-owned columns. RESEARCH the git-owned/table-owned split the
   roadmap seeds already use (`tools/roadmap-seed.py --sync`, and the row bodies
   there) so `upsert-row`/`patch-field` write the right half.

6. **Stable opaque ids (`kpro-ids`).** A row's identity must survive a rename/
   move; a physical id (`fs:<uid>:sha1(path)`) forks the corpus silently. The
   CRUD door keys on the opaque id, not the slug. Land this first — cheap now,
   expensive per row later.

## The first buildable movement + what "done" looks like

Ship in this order; each step is independently verifiable:

1. **Fix the door** (`kpro-table-access`): GET/POST/PATCH/PUT/DELETE on
   `/…/tables/<t>/rows`, keyed on the opaque id, not upsert-on-slug. DONE = a
   second write to the same id UPDATES (a probe today produces a duplicate row —
   re-run it and prove one row, not two).
2. **`search-rows` over the rows**, honoring the no-confident-match floor. DONE
   = a query about a known row returns it; a query about nothing returns EMPTY,
   not the nearest row (gate both directions).
3. **`McpTablesTool`** (in-process) with the tiny verb set, RBAC-honoring. DONE
   = an AgentKit agent reads, searches, claims, and patches a table row end to
   end, and the claim blocks a second agent.
4. **The external MCP server** (via mcpo) exposing the same verbs to Cursor/
   Codex/Claude Code. DONE = an external agent does the same round-trip.

## Invariants you must not violate (the estate's rules)

- **Detectors read artifacts, not prose.** Every gate you write parses the
  rendered structure / runs the real thing — never a substring that a comment
  could satisfy. Run every gate against its own BROKEN state before you trust it.
- **Success is written by a reader, not the attempting code.** A write that
  reports its own success is the defect; the reader confirms it landed.
- **Absence is never a result.** `search-rows` below threshold returns nothing.
  A door that can't read a table says UNKNOWN, never empty-as-fine.
- **No hand-poking the estate.** Everything installs via the playbook /
  converge; you edit source and gate it, the operator converges. Partial tagged
  converges are the operator's unless told otherwise.
- **The seed is git-owned, the status is table-owned.** Don't let a write blur
  the two (the roadmap's `--sync` is the reference).

## Where the deeper design continues

The routing-address grammar (`dtt-routing-address`, spec §15 —
`<WHERE>/<WHO>/<KAM>/<CO>/<KDY>`) may become the spine of BOTH this access model
and nos-planner; the `task_type` enum (`dtt-task-types`, in code, proposable) is
the contract a claimed row routes on; per-row-file seeds
(`dtt-seed-per-row-file`) make parallel editing conflict-free. This brief
delivers the door and the harness they all sit on. Build that, and the rest of
the epic has something real to stand on.
