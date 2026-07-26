# The recall gate — what it measures, what it cannot, and how to read it

> Vendored from thisisait/nos-keap @ v1.28.0 (94acbfe) docs/specs/recall-gate.md — organ-side copy, P-4b Docs stage 2026-07-25. The KEAP original remains authoritative until the post-C4 docs cleanup.

Status: **shipped**, at **gate semantics v2**. `scripts/recall-gate.mjs` (I/O) +
`scripts/recall-lib.mjs` (the decision layer, unit-tested in
`scripts/recall-lib.test.mjs`), written against v1.27.0. Measured numbers in §6
are from real runs on 2026-07-25, **after** the five fixes in §7.

> Read §7 before trusting any recall number recorded before 2026-07-25. Between
> shipping and that date the gate measured **presence only**: an exemption meant
> for navigation silently consumed 100% of the `forbid` refs in the nOS set, so
> the half of the assertion this gate exists for never ran, and 261/261 was
> recorded in that state.

Every other check in the chain gates **form**: charsets, anchor integrity, id
stability, description length. The failure that started this track — nine
`_stack.md` cards outranking real content for *Nuclear Engineering* — passed all
of them. Sixty templated node descriptions would pass lint (`en ≥ 20 chars`) and
wreck recall identically. We measure length because it is easy; what fails is
meaning.

This gate measures meaning, and it is built so that it cannot flatter itself.

---

## 1. What it measures

A query set of `{q, expect[], forbid[]}` cases is run through the **real** hybrid
search (RRF over lexical + vector + graph legs), against a **real** embedded
corpus, and each case asserts two things:

- **presence** — at least one `expect` ref is in the top *k* (default 5), and
- **relative order** — no `forbid` ref outranks it.

`forbid` is the point. The `_stack.md` failure was *relative*: generic
self-model items capturing queries that specific ones should own. A gate that
only asked "is the right thing somewhere in the top 5" would have shipped it.

Two modes, same semantics and same exit codes:

| mode | corpus | what it proves |
| --- | --- | --- |
| **fixture** (default) | throwaway KEAP booted from `--fixture DIR`, cards from `--skills DIR`, embedded through the real pending → Ollama → POST loop | a tree is good **before** it ships |
| **live** (`--base URL`) | an already-running KEAP, read-only through `/agent/v1` with `KEAP_AGENT_TOKEN_RO` | the corpus that **actually** shipped, embedded by the live pulse job |

Ranking happens **within scope** (`spec.scope`, default `nos`). Absolute
corpus-wide rank against the 790-node seed spine is a stricter, different
property: it is printed as diagnostics and never gated, because otherwise every
generic phrasing would fail against the spine and the gate would be ignored.

Two exemptions are applied and both are **reported, never silent**:

- **graph-only hits are not relevance.** A hit whose only leg is `graph` was
  surfaced by topology — the graph leg hops one step out from the real hits, so
  a stack is every system's neighbour no matter what its text says. The router
  routes on meaning; the gate ranks only hits that earned a lexical or vector leg.
- **proper ancestors of the target are navigation, not competition.** A parent
  stack ranking beside its own child is the search working as designed. A
  *sibling* above the target is the `_stack.md` class and is never exempt.
  **Neither is anything the case explicitly forbids** — `forbid` is a written
  assertion by the query set's author about relative order, and a generic
  heuristic does not get to overrule it. Ignoring that precedence is how the
  exemption came to void the forbid half of all 261 cases (§7.1).

The forbid half reports its own health on every run, healthy or not:

```
   FORBID HALF    528/528 ref(s) compared (528 resolved) across 261/261 measured case(s)
```

`compared` counts forbid refs that survived the exemption and could actually be
ranked against the target. It read **0/528** for a year of green runs.

## 2. What it cannot measure — and says so

**A case whose expectations name nothing in the corpus under test is not a
failure. It is not a pass either. It is a case that never ran.** Conflating the
two turns a coverage gap into a wall of false reds that buries the real signal;
hiding it turns a 5% sample into a green light. So the gate reports it as its
own quantity, broken down by cause:

| cause | meaning | whose problem |
| --- | --- | --- |
| `gap:both-absent` | neither the expected node nor the expected card exists here | corpus owner |
| `gap:node-absent` | the only expectation was a node id, absent here | corpus owner |
| `gap:card-absent` | the only expectation was a card title, absent here | corpus owner |
| `ambiguous-title` | the title exists on several cards and nothing scopes it | query set / KEAP |

And a case can be measured on **less** than it named. If a case says
`[node:nos.iiab.nextcloud, title:get-user-info]` and the card is missing, the
node still resolves and the case is graded — on the *system*, not on the *skill*
it is actually about. That is real coverage of a smaller claim, so it is counted
as `DEGRADED` rather than left to pass silently.

| degraded cause | meaning |
| --- | --- |
| `degraded:card-absent` | measured on the NODE only — the named card is not in this corpus |
| `degraded:node-absent` | measured on the CARD only — the named node is not in this corpus |
| `degraded:presence-only` | the case named `forbid` refs and **not one** could be compared — the relative-order half did not run |
| `degraded:forbid-partial` | some `forbid` refs name nothing here and were not compared |

The last two are the forbid side of the same rule, and they are the reason a
`node:` forbid that no longer exists (nOS renames a service) cannot quietly
downgrade a case to "is it somewhere in the top 5" while the summary still
counts it under PASSING.

The corpus must also be **fully embedded** before any of this means anything. A
half-embedded corpus has no vector leg for whatever was not reached, so the
competitors that would have outranked the target never compete and cases pass on
the lexical leg alone. The gate drains `pending` and asserts it — in fixture
mode by looping until the page comes back empty, in live mode by reading
`/agent/v1/embeddings/pending`. Not draining is exit 4, never a pass.

Three more things the gate deliberately does **not** claim:

- **`expect` is a UNION.** A pass means the node **or** the card made top-*k*.
  The summary prints `PASS SHAPE — node+card / card only / SYSTEM NODE ONLY`;
  the last bucket is a pass where the named skill never appeared.
- **rank *k* is one slot from a miss.** The rank histogram is printed, and cases
  sitting at exactly *k* are called out.
- **it is not a benchmark.** These are curated query→winner pairs, not a
  sampled distribution of real traffic. It catches regressions; it does not
  estimate recall in the wild.

## 3. `title:` is not a unique handle (a defect this gate shipped with)

Card ids are content-addressed (`fs:nos-docs:ca724ab6…`), so query sets name
cards by title. Titles are **not unique across an estate**: the live corpus has
six duplicated skill names (`create-document`, `list-users`, `list-dashboards`,
`create-post`, `list-databases`, `list-libraries`). The gate used to resolve them
through a last-write-wins map, and the consequences were measured, not theorised:
30 cases named a duplicated title, **13 resolved to a card owned by a different
system than the case meant**, producing 3 false reds (ERPNext's
`create-document` ranked #1 while the gate graded Outline's) and 2 false greens.

Fix, KEAP-side: a `title:` ref resolves **within the subtree of the node the same
case names**. Preference order is (a) a card anchored at or under the expected
node, (b) a card anchored at an ancestor of it, (c) unresolved. An unscopeable
duplicate is `ambiguous-title` — unmeasurable, never guessed, because guessing
is how the false reds happened.

nOS's generator is not at fault here: it is reasonable to assume skill names are
unique *per system*. They are not unique *per estate*.

## 4. The baseline — regression and corpus gap are different problems

`--update-baseline` records the current passing set to
`e2e/baselines/<slugified-query-path>.<mode>.json`. A later run then reports:

| line | meaning |
| --- | --- |
| `REGRESSIONS` | passed then, **fails now** — KEAP's ranking moved. Ours to fix. |
| `NEWLY COVERED & FAILING` | the baseline recorded it as **unmeasurable**; it is measured now, and fails on its first measurement |
| `NEW & FAILING` | the case is not in the baseline at all — a new expectation, not a regression |
| `COVERAGE LOST` | was measurable, **is not now** — the corpus shrank or drifted. Not a recall failure. |
| `NEW COVERAGE` | was unmeasurable, is measured now (split into passing / failing, so nothing is counted twice) |
| `FIXED` | failed then, passes now |

Every failing case lands in **exactly one** of the first three rows, because the
baseline's three sets are disjoint. A newly covered failure used to be reported
as "not in the baseline at all" *and* counted under `NEW COVERAGE` at the same
time — one case in two mutually exclusive buckets, and the operator told nothing
about the state that actually held.

Baselines are keyed by **query set × mode × semantics**, and the file records all
three. A baseline recorded for a different set, a different mode, or an older
gate generation is *refused*, not silently compared — fixture mode and live mode
measure different corpora, and a v1 record's passes were measured with the forbid
half disabled (§7.1), so comparing against them would report the newly-live
relative-order failures as KEAP ranking regressions, which they are not. (The two
self-model sets even share a basename, so the whole path is slugified into the
filename.)

### Writing one is guarded

`--update-baseline` is refused when the run **cannot speak for the set**: nothing
measured, below `--min-measured`, coverage the baseline holds now unmeasurable,
the corpus not fully embedded, or simply fewer measured cases than the file
already on disk. The last one is deliberately independent of the comparison: a
baseline refused for a mode or semantics mismatch reports no lost coverage at
all, and that is precisely when a thin run must not be allowed to replace a full
one. `--force-baseline` overrides, says so, and lists what it overrode.

The verdict is computed **before** the write, which is the whole fix — see §7.3.

## 5. How to read the output

```
── RECALL GATE — ../nOS/tests/fixtures/selfmodel-recall.json (live mode, k=5, scope=nos) ──
   cases in set   261
   MEASURED       100.0% (261/261) of the set
   PASSING        99.6% (260/261) of MEASURED  ← never of 261
   FAILING        1/261 measured
   UNMEASURABLE   0/261 — not failures, and not passes either
   FORBID HALF    528/528 ref(s) compared (528 resolved) across 261/261 measured case(s)
   PASS SHAPE     node+card 112 · card only 148 · SYSTEM NODE ONLY 0
   RANKS          rank1 234 · rank2 23 · rank3 2 · rank4 1
   ANCESTOR EXEMPTION fired on 0/261 measured case(s)
```

**Rule of this gate: no percentage is ever printed without the fraction that
produced it.** `PASSING` is always *of MEASURED*, and `MEASURED` is always
*of the set*, on the line above it. If you ever see a bare percentage from this
script, that is a bug — the repo shipped "corpus exhausted" once and the whole
point of this format is that reading it honestly is the path of least resistance.

The machine-readable line is `RECALL_RESULT {…}` on **stdout** (everything else
is stderr): `{queries, mode, cases, measured, passing, failed[], unmeasurable,
unmeasurableByCause{}, degradedByCause{}, passShape{}, ranks{},
forbid{named,resolved,compared,cases}, drain{drained,remaining,rounds,reason},
baseline{…}, semantics, embedded, exit{code,reason,detail}, report[]}`.

`forbid.compared` and `drain.drained` are there for the same reason the lines
above are: the two failure modes that produced a green light over an unmeasured
set were both quantities nothing recorded. A consumer that trusts `passing`
without reading them is trusting the number that lied.

### Exit codes — four states, deliberately distinct

| code | meaning |
| --- | --- |
| `0` | no **regression**, and coverage did not shrink. Either a clean pass, or `pass-with-known-failures` — failures the baseline already records, printed as `PASSED WITH DEBT` with every carried case named |
| `1` | a **regression**: a case that passed in the baseline fails now. With **no** baseline, any failure exits 1 — you cannot call a failure known on a corpus you have never recorded |
| `4` | **loud skip, never a pass**: no embedder, query set missing, **the corpus never finished embedding**, zero measurable cases, coverage below `--min-measured`, or coverage lost against the baseline |

**Why a known failure does not fail the run.** The baseline computes regressions
and the gate used to throw that answer away, exiting 1 on any failure at all. The
in-repo fixture holds 7 nodes across one stack-pair, and two of its four cases
forbid an ancestor from outranking a skill — which a corpus that small cannot
satisfy however good recall is. So the default gate was permanently red, and a
gate that can never go green is one people learn to ignore. What stops this
becoming a baseline of shame: the known-failing set can only GROW through an
explicit `--update-baseline`, because any pass→fail transition is a regression
and fails. A newly measured failure (coverage widened) likewise does not fail —
punishing that would penalise the act of finding out where recall is weak.

The guard order lives in `exitVerdict()` in `scripts/recall-lib.mjs`, where it
can be read and tested, rather than being a property of which statement happens
to come first in the script. The drain is checked **before everything else**: if
the corpus was not fully embedded, no number from the run means anything,
including its failures.

`--min-measured` **defaults to 50%** rather than to nothing. The failure being
fixed here is precisely a green exit over a 5% sample; a gate must refuse to call
itself passing when most of its set never ran, whether or not CI remembered to
ask. Pass `--min-measured 100%` when the corpus is supposed to cover everything,
or `--min-measured 0` to opt out deliberately.

## 6. Running it

```bash
npm run gate:recall                 # in-repo 4-case set against the in-repo fixture
npm run gate:recall:nos             # the 261-case nOS set against the in-repo fixture
KEAP_AGENT_TOKEN_RO=$(docker exec iiab-keap-1 printenv KEAP_AGENT_TOKEN_RO) \
  npm run gate:recall:nos:live      # the 261-case nOS set against the live estate
```

The nOS set is **read where nOS keeps it** (`../nOS/tests/fixtures/selfmodel-recall.json`,
override with `KEAP_NOS_QUERIES`). It is never copied into this repo: a fork
would silently diverge from the contract it is supposed to check.

Real results, 2026-07-25, v1.27.0, **gate semantics v2** (all three re-measured
after the §7 fixes; the v1 column is what the same corpus reported before them):

| run | measured | passing (v2) | reported (v1) | exit |
| --- | --- | --- | --- | --- |
| `gate:recall` (in-repo set, in-repo fixture) | 4/4 | **2/4** | 4/4 | **0** (2 known failing, no regression) |
| `gate:recall:nos:live` (nOS set, live estate) | 261/261 | **260/261** — rank1 234, rank2 23, rank3 2, rank4 1 | 261/261 | **1** |
| `gate:recall:nos` (nOS set, in-repo fixture) | **14/261** | **9/14** | 14/14 | **1** |

Three things to read off that table.

**The forbid half now runs.** 528/528 forbid refs compared on the live set, 9/9
in-repo, 28/28 in the fixture-mode nOS run — all of them previously 0. Every
difference between the v2 and v1 columns is a case that was already failing its
relative-order assertion and being reported as a pass.

**The live failure is the `_stack.md` class, exactly.** On *"is everything up"*
the stack node `nos.iiab` takes rank 1 (`vector+graph`) over the uptime-kuma card
at rank 2 — a generic self-model item capturing a query a specific one should
own. That is the failure this whole track started from, on the shipped corpus,
and it was invisible for as long as the exemption was.

**The 247-case gap is not KEAP's to paper over.** Against the live corpus the
same 261 cases are 100% measurable — every expected node id and every expected
card title exists there. The gap is a property of the in-repo fixture, which was
built to prove one stack-pair and is being asked a question about an estate.
Closing it means shipping a larger canonical fixture (nOS's tree, nOS's cards) —
a corpus decision, made by the corpus owner, not a resolution rule bent until the
number looks better. Note that the fixture-mode nOS run now exits **1** rather
than 4: 5 of its 14 measurable cases fail their relative-order assertion, and a
real failure outranks a coverage skip.

One judgement call is open in that last row, and it is recorded here rather than
resolved quietly. All 5 of those failures are cases the same run already flags
`degraded:card-absent`: the fixture has no card, so the case was graded on the
system node alone, and what actually failed is *"`nos.iiab.nextcloud` must
outrank `nos.iiab`"* — a weaker claim than the one the case makes about its
skill card. That is the `_stack.md` shape (a stack capturing a query its child
should own), so it is gated; but a DEGRADED case failing the half it was
degraded *into* is worth a decision by the corpus owner, not a default. It does
not arise on the live corpus, where every card exists.

## 7. What the 2026-07-25 audit found

Five defects, all shipped, all in the same shape: **the quantity that was broken
was the one quantity the summary did not print.** Fixed in `recall-lib.mjs` with
one test per defect written from the concrete scenario that made it visible
(`scripts/recall-lib.test.mjs`).

### 7.1 The ancestor exemption voided the forbid half of every case *(major)*

`properAncestors()` seeded its set with `scopeRoot` and added every proper
ancestor of each expected ref; those taxonomy keys were then stripped from
`ranked` **before** `bestForbidden` was computed as `ranked.indexOf(f)`. nOS's
261-case set forbids exactly `[node:nos, node:nos.<stack>]` and expects
`node:nos.<stack>.<svc>` — so all 528 forbid refs were proper ancestors of their
own target, all 528 were exempted, `bestForbidden` was always `Infinity`,
`cleanRank` was unconditionally `true`, and **§1's "relative order" was never
measured for a single case**. Feed the motivating scenario — stack at #1, root at
#2, skill card at #3 — to the shipped code and it prints `✓ "upload file" → rank 1`.

Nothing disclosed it: not the summary, not `RECALL_RESULT`, not the baseline.
`ANCESTOR EXEMPTION` fired only when an ancestor happened to land in top-*k* and
was framed as benign navigation. The committed 261/261 live baseline was recorded
in that state.

Fix: an explicitly forbidden ref is never exempt — a written assertion beats a
heuristic — and the summary carries a `FORBID HALF` line on every run so the
count can never sit at zero unnoticed again.

### 7.2 The embed loop had no drain assertion *(major)*

`for (let round = 0; round < 12; round++)` over a page size the server caps at
500: 6000 items, no post-condition. §6 names the remedy for the coverage gap as
"a larger canonical fixture (nOS's tree, nOS's cards)" — which, on top of the
790-node seed spine the gate deliberately embeds too, plausibly exceeds that
ceiling. The vector leg would then be populated for an arbitrary prefix of the
corpus (pending lists taxonomy first, so the tail is exactly the fixture cards),
cases would pass on the lexical leg alone against competitors that had no
vectors, and the gate would print `corpus embedded: 6000 item(s)` and exit 0.

Fix: the drain is measured and asserted in both modes, a no-progress break names
a write-back that is not landing as itself, and `drain{}` is in `RECALL_RESULT`.

### 7.3 `--update-baseline` wrote before the guards *(major)*

The write sat at the top of the exit section, ahead of `!measured`, `failures`,
`--min-measured` and `coverageLost`. Record the live baseline while the pulse job
is still embedding and only 140 of 261 cases resolve: the file is overwritten
with `measured: 140`, the run *then* prints SKIPPED-LOUD and exits 4 — and the
261/261 record is already gone. Every later run compares against 140, finds no
lost coverage and no regressions, clears the 50% floor, and prints **RECALL GATE
PASSED** while 121 cases that used to be measured are invisible. The entire
anti-"corpus exhausted" premise rests on that file, and it had no guard, no
confirmation and no warning.

Fix: verdict first, write second, refused unless the run can speak for the set —
including a refusal to shrink the file's own denominator when the comparison was
skipped for a mode or semantics mismatch. `--force-baseline` is the deliberate
override.

### 7.4 Unresolvable forbid refs were silently dropped *(minor)*

Forbid resolution kept `.resolved` and discarded the `nodeRefs/nodeHits/
titleRefs/titleHits/ambiguous` counters that the same function computes for the
expect side. A `node:` forbid absent from the corpus, or a `title:` forbid
`scopeTitle` marks ambiguous, simply vanished: `forbidden` went empty,
`cleanRank` was trivially true, and the case was reported as a full PASS with no
`DEGRADED` entry. Today all 28 forbid refs across the 14 fixture-measurable nOS
cases happen to resolve — but the query set is owned by the other repo and read
in place, so the first `forbid: ["node:nos.iiab.outline"]` would silently disable
that case's relative-order assertion while the summary still counted it under
PASSING. Fix: `degraded:presence-only` / `degraded:forbid-partial`.

### 7.5 "NEW & FAILING" mislabelled newly covered cases *(minor)*

`newlyFailing` never consulted the baseline's `unmeasurable` map, so a case the
baseline recorded as a coverage gap — 247 of them in `gate:recall:nos` today —
would, on becoming measurable and failing, be reported as "a new expectation,
not a regression" *and* counted under `NEW COVERAGE`: one case in two mutually
exclusive buckets, and neither of them the truth. Fix: `NEWLY COVERED & FAILING`
is its own row and `NEW COVERAGE` is split into passing and failing.
