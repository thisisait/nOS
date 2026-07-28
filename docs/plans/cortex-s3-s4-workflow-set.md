# S3 → S4 as a workflow set — the steps to the first "second brain" release

Authored 2026-07-28. Companion to `docs/plans/cortex-self-core.md`, which holds the
doctrine; this holds the **order of operations**. Where the two disagree, the plan
wins and this file is stale.

---

## 0. The thing this document exists to prevent

"Second brain" is a capability claim, and the estate has four independent tracks
that each sound like they finish it: the nightly agreement streak, the index
decision, the consumer move, and the entity registry. They do not gate each
other, they compete for the same converges, and three of the four can be complete
while the system still is not one.

So the first statement has to be the unpleasant one:

> **The v0.10-beta release does not require S3 or S4.** It requires the nightly
> diff to agree three nights running. S3 and S4 are what make the organ *the*
> corpus rather than a second copy — which is the difference between a release and
> a second brain, but not the difference between a release and no release.

Conflating those is how a tag ships on a promise. The two lanes below are
therefore tracked separately and merged only at §5.

---

## 1. Lane A — the release lane (blocking, ~3 days, mostly waiting)

| # | Step | Gate | State |
| --- | --- | --- | --- |
| A1 | Referee agrees on all six clauses | manual verification | **done** 2026-07-27 |
| A2 | Night 1 — first honest `cortex-corpus-diff` | `AGREES: true` | fires 07:34 CEST 2026-07-28 |
| A3 | Night 2 | `AGREES: true` | 2026-07-29 |
| A4 | Night 3 | `AGREES: true` | 2026-07-30 |
| A5 | Docs review | operator-requested, pre-tag | not started |
| A6 | `dev → master` PR, tag `v0.10-beta` | CI green, `RELEASE.md` written | blocked on A4 |

**A2–A4 are wall-clock, not work.** Nothing accelerates them; a manual run is a
diagnostic, not a night. That is the whole reason the clock had to start before
the capability work, and it is why Lane B gets the next three days.

**One rule protects the streak: a converge that changes knowledge invalidates
nothing, but a converge that changes the *diff harness* restarts the count.** The
streak measures agreement under a fixed harness. Lane B work that touches
`cortex-corpus-diff`, the organ store, or the vendored tree must therefore land
*after* A4 or be measured as a deliberate restart.

---

## 2. Lane B — the capability lane (non-blocking, runs during A2–A4)

Three workflows, in this order, for reasons that are not preference:

### B1. `cortex-s3-index.js` — decide the index

**Exists.** Not yet run.

*Precondition:* host Ollama reachable, or the recall gate exits 4 and there is no
baseline. A skipped gate is not a pass.

*Why first:* S4 moves consumers onto the organ's index. Moving readers onto an
index that is about to be rebuilt means measuring twice and trusting neither.

*Known trap, already written into the workflow:* recall at ~3.5k vectors is close
to silent about `max_neighbors` at 10⁶. The workflow is required to say which of
its results are evidence and which are merely absence of evidence at this size.

### B2. `cortex-s4-readers-writers.js` — move the consumers

**Written 2026-07-28.** Four phases: Inventory → Contract → Move → Prove.

*Precondition:* B1 decided, and the **Contract** phase reports zero blockers. The
workflow stops itself if `/agent/v1` lacks a verb an inventoried consumer needs —
that gate exists because a writer moved onto an API that silently drops a field
corrupts the corpus, and a corpus is not restorable from a rerun.

*Scope boundary, stated up front so the outcome cannot overclaim:* B2 moves Pulse
jobs, AgentKit tools and the curator/librarian agents. It does **not** move the
~47 KEAP UI routes. Exit criterion 1 ("no consumer reaches KEAP's corpus")
therefore stays open at the end of B2, and the workflow is instructed to say so
rather than to declare S4 done.

*Two traps carried in from this week:*

- **The boot cache.** The organ caches its knowledge tree at process start. A
  consumer that writes taxonomy and reads it back in the same run reads stale
  data. The Contract phase must name those writers specifically; for them
  "move to `/agent/v1`" is not sufficient.
- **Long jobs.** Wing advances `next_fire_at` only on finish, so a job outliving
  one tick used to be dispatched twice — measured on `vulnerability-scan`, ~500 s
  against a 30 s tick, every night for four nights. Fixed in the daemon on
  2026-07-28; the workflow still records job runtimes, because an indexing job is
  exactly the shape that found it.

### B3. `ent:` against DataTables — see §3

Independent of B1/B2. It is the lane the operator's own data enters through, and
it has a blocker of its own.

---

## 3. Lane B3 — the entity registry, and the join that is missing

`cortex-self-core.md` §6b settled the question: **`ent:` resolves against
DataTables**, and `object_type_definitions` — created by migration 001, touched by
zero lines of code, never a row — gets dropped.

That decision has an immediate, concrete consequence, and it is the operator's
stated next task: filling core business data (tax, contact, invoicing, delivery
details; `nos-tenant-owner` end users) through face.

**The blocker is real and it is small.** `shared/contracts/table.ts` defines
eleven column kinds. Two of them already wire a row into the knowledge graph —
`taxonomyRef` (node id) and `objectRef` (knowledge object id). There is **no kind
that points at another row**. So a table can be anchored into the universe but
cannot be joined to a sibling table: an invoice cannot reference its customer.

Design: `docs/plans/datatables-relations.md`. Summary of the decision it argues:

- **Add a `rowRef` column kind** — the structural join. Declared in the column
  def with its target table, validated on write, rendered as a picker.
- **Do not** overload the existing `relations` table for it. That table already
  exists (`from_kind`/`to_kind` ∈ `node|object`, with `confidence`, `status`,
  `justification`, `source`) and it is the right home for *semantic, moderated,
  possibly agent-proposed* edges — including row↔node edges. Structural joins and
  proposed edges have different truth conditions; one table cannot enforce both.

*Sequencing against the release:* B3 touches KEAP's schema and the face UI, not
the diff harness. It is therefore safe to run during A2–A4 — but it produces a
KEAP tag, and a KEAP pin bump is a knowledge change, which needs a daemon restart,
which needs a converge. **Land the pin after A4.** Develop during, ship after.

---

## 4. What is deliberately not scheduled

- **S5 (KEAP becomes data-only)** — needs S4 complete including the UI routes.
- **S6 (weights)** — needs the corpus rebalanced first; §6 of the plan records
  that 67 % of nodes sit in 2 of 12 domains and Law is a childless stub, which is
  a precondition, not a detail.
- **The executor / graph engine** — the operator classed it nice-to-have pending
  a graph-engineering decision. Forward arc, not a v0.10 gate.
- **On-behalf-of identity** — §6b names it as the one piece of the identity design
  with no existing answer in the estate or in Authentik's current configuration.
  Research, not assembly; it must not be scheduled as if it were implementation.

---

## 5. The merge point

The release ships on Lane A. Lane B lands after the tag, in the order B1 → B2,
with B3 developed in parallel and pinned post-A4.

The honest description of `v0.10-beta` is therefore: **the corpus is measurably
one corpus, verified by three consecutive independent nights.** Not "the organ is
the source" — that is S4 — and not "the second brain reasons over it" — that is
S6 and the executor.

Writing the claim down now is the point. It is much harder to overstate a release
whose exact wording was fixed before the tag existed.
