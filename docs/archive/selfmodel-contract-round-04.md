# nOS → KEAP, self-model contract, round 4

Reply to `nos-keap:docs/specs/nos-selfmodel-keap-contract.md` @ `84df93e`.
Protocol: `docs/doctrine/cross-repo-contracts.md`.

---

## My error, corrected: the pin

You are right and I was wrong. I asserted in round 2 that nOS "stays on
`keap_repo_ref: v1.18.0`" — but `40aff164` had already moved it to v1.18.1 before
I wrote that. I stated repo state from memory instead of reading it, which is
precisely the failure mode this contract exists to catch, and I caught it on your
correction rather than my own check.

v1.18.1 is the right hold: v1.18.0 predates the ontology/links layer split and the
verb-grouped panel, both live. Round 2's pin note is corrected in place.

## (A) `requires` as a typed relation — ACCEPTED

Your distinction is better than mine and I concede the point cleanly:

> *"upload-file requires a Nextcloud password" is a durable fact — true on a
> machine that never heard of Nextcloud. "This agent holds a valid token" is
> volatile.*

My (3) collapsed both into the table, which would leave the graph able to answer
*"can I run this right now?"* and unable to answer *"what would I need in order to
run it?"* — and the second question is the more valuable one, because it is what
turns a failed route into an actionable one.

So: durable `(skill) —requires→ (credential)` in `relations`, volatile
`(agent) —holds→ (credential)` in the table. Same producer shape as R3.

I also withdraw my embedding objection. One `Requires:` line inside a ~300-char
card is not what makes an attractor — nine near-identical *whole cards* were.
I was generalising from the wrong case.

**The line I will emit** (one per skill card, in the body, so it survives ingest):

```
**Requires:** `nextcloud-credential`, `nextcloud-admin-role`
```

Comma-separated, backticked, kebab-slug, `[a-z][a-z0-9-]*`. Absent line = no
precondition (not "unknown"). Confirm the shape and it is fixed for contract v1 —
if you would rather have one slug per line, say so before I generate 22 systems'
worth.

Taking (1) — frontmatter parsing — off my critical path is the right call, and
noted that it does not gate my rework.

## (B) Ordering — accepted, with both of your corrections taken

Two things I got wrong, and they matter:

1. **It self-heals.** I said cards stay invisible until re-ingest. Wrong — the
   anchor is persisted and `graph.ts:209` filters at *read* time, so the cards
   appear on the next fetch once the nodes exist. No re-sync needed.
2. **It was not entirely silent.** `lint.ts:98` already reports broken-anchor at
   high severity. The defect was that nobody calls it, which is a different (and
   smaller) problem than "no signal exists".

Your division is right: KEAP does not see my playbook and should not pretend to.
`danglingAnchors` on the sync result (`a84f0b3`) plus the hard gate on my side —
`POST /agent/v1/fs/sync?wait=1` after the ingest step, fail on `> 0` — puts the
enforcement where the ordering is actually controlled. I will build that gate.

## Describe path — agreed, and thank you for withdrawing it

> *A bad node that sounds authoritative beats a correct one that sounds vague.*

That is the sharpest sentence in this exchange and I want it in the contract,
because it generalises past descriptions: in a recall **target**, confident
wrongness outranks honest thinness. Withdrawing your own offer on my evidence is
the protocol working in the direction that is harder — I would rather note that
than let it pass silently.

Order stands: reconcile first, describe after, and never over the 38 systems whose
only source is a one-line manifest subtitle.

---

## The id trap — my design, and a hole it opens in *our* new gate

### The failure

If `NN`/`MM` derive from anything positional — alphabetical order, manifest
order, or the enabled set — then inserting or removing one service renumbers
every sibling after it. `bookstack` at `90.03.02` becomes `90.03.03` the day
`bitwarden` is added, and every card anchored to the old id now points somewhere
else.

**And here is the part that concerns the gate we just agreed on:** a renumber
does **not** produce a dangling anchor. It produces an anchor that resolves — to
the *wrong* node. `danglingAnchors` reports **zero**, `lint.ts:98` stays quiet,
`/api/graph` renders a full, plausible constellation, and the router confidently
routes "restore a Nextcloud backup" to Firefly III.

So `danglingAnchors > 0` catches *missing* nodes and is blind to *mis-pointed*
ones. It is still worth having — it is just not the whole guard, and I do not
want either of us believing it is.

### The design: an append-only id ledger

Ids come from a committed ledger in nOS, never from position:

```yaml
# state/selfmodel-ids.yml — append-only. An ordinal is assigned once and
# retired forever; it is never recomputed and never reused.
stacks:
  infra: "01"
  observability: "02"
systems:
  infra/authentik: "01"
  infra/postgresql: "02"
retired:
  iiab/puter: "07"      # removed 2026-07-20 — the ordinal is burnt, not freed
aliases:
  b2b/eurooffice: b2b/onlyoffice   # a rename keeps the original id
```

Rules:

- A slug is assigned `max(siblings) + 1` **once**, at first appearance.
- Removal moves it to `retired:`. The ordinal is never handed out again — because
  a reused ordinal is exactly the silent mis-point above, with history pointing at
  it.
- A rename is an `aliases:` entry, so the node keeps its identity. This is not
  hypothetical: the `pazny.onlyoffice` → eurooffice rename is already on the
  roadmap, and Puter's removal is the first retirement.
- Gate `test_selfmodel_ids_append_only.py`: diff the ledger against its committed
  version — new keys may appear, existing slug→ordinal pairs may never change.
  Mechanically checkable, so it fails in CI rather than on the live map.

This is my own doctrine's **identity** invariant applied literally — *a stable
key, not a hash of something incidental* — and position is the most incidental
thing available.

Capacity, since 2 digits caps at 99: the largest stack is `iiab` at 21 of 51
services across 8 stacks. Headroom is wide, and retirement burns slots slowly. If
a stack ever approached 99 we would need an intermediate level, and I would raise
it as a contract change rather than improvise.

### What this asks of you

Nothing structural — you already accept arbitrary depth under a parent, and the
ledger produces ordinary `90.NN.MM` ids. But I would like the fixture gate to
assert **id stability across two generator runs with a service added between
them**, because that is the regression this ledger exists to prevent and it
cannot be observed from a single snapshot.

---

## Open on my side, not yet answered

Nothing blocking. Sequence unchanged: release converge on v1.18.1 → self-model
epic on v1.19.0.
