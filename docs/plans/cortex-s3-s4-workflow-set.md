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
| A2 | Night 1 — first honest `cortex-corpus-diff` | `AGREES: true` | **done** 2026-07-28 05:34 UTC, all six clauses, `agreeStreak: 1` |
| A3 | Night 2 | `AGREES: true` | **done** 2026-07-29 05:32 UTC, all six clauses, `agreeStreak: 2` |
| A4 | Night 3 | `AGREES: true` | 2026-07-30 05:30 UTC — **first night at a real denominator** |
| A5 | Docs review | operator-requested, pre-tag | not started |
| A6 | `dev → master` PR, tag `v0.10-beta` | CI green, `RELEASE.md` written | blocked on A4; CI green since 2026-07-29 |

**The streak's denominator, quoted from the harness itself.** Night 1 passed all
six clauses and the report still closed with:

> This run does not show that ingestion is correct. It shows that two near-empty
> corpora are equally near-empty.

`realUserDocs: 2` against a disclosure floor of 25. Nine behaviours went
unexercised — prune, move/rename, multi-user attribution, visibility flip, the
20 000-file cap, EACCES truncation, more than one tenant, bodies over `BODY_CAP`,
non-ASCII paths. Three green nights therefore license exactly one sentence:
**the two corpora agree, under a fixed harness, repeatedly.** They do not license
"ingestion is correct", and §5's release wording is written to stay inside that.

The harness disclaiming itself is the feature. It is also the argument for §3's
ordering: real user documents arrive with the operator's business data, so the
floor is crossed by doing the work, not by waiting.

**The denominator was crossed on 2026-07-29, between night 2 and night 3.**
`tools/cortex-seed-fixtures.sh` seeded 26 well-behaved Markdown notes into
`akadmin`'s tree: `realUserDocs` **2 → 28**, above the disclosure floor of 25.
The two pre-existing "real user docs" were *both binaries* (a PNG and a PDF), so
until this landed no user-side text had ever exercised body hashing, `BODY_CAP`
or embedding — those clauses were carried entirely by the `nos-docs` self-model
tree. A `--no-ledger` run immediately afterwards returned **AGREE** with
`knowledge_objects[fs:]` at 317/317 exact, so night 3 is expected to agree at the
new denominator rather than the old one.

This is a change of *input*, not of harness, so the streak legitimately continued
at 2 rather than restarting — the rule below is about the harness. But it does
make the streak **heterogeneous**, and §5's wording is written to say so rather
than to imply three nights of equal weight.

One consequence to expect in the report and not to misread: every DataTable is a
KEAP-only `knowledge_objects` row (`type: table`, no `fs:` id), classified
`not-a-mirror-row` and withdrawn from the fs clause. There were four; seeding
added a fifth. The count grows with each table created until S4 moves them, and
`knowledge_objects` will read DIFFER for that reason alone.

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
one corpus, verified by three consecutive independent nights — the last of which
was the first measured above the disclosure floor (28 user documents against 2
for the two before it).** Not "the organ is the source" — that is S4 — and not
"the second brain reasons over it" — that is S6 and the executor.

The footnote is not decoration. Nights 2 and 3 measured two near-empty corpora
agreeing; night 4 measured a populated one. Dropping the clause would let a
reader take all three as equivalent evidence, which is exactly the overstatement
this document exists to prevent. Decided 2026-07-29 (operator): take the streak
as it stands with the denominator stated, rather than restart for three nights at
28 — the three-night rule tests stability over time, not a constant denominator,
and the evidence improves monotonically across the three.

Writing the claim down now is the point. It is much harder to overstate a release
whose exact wording was fixed before the tag existed.
