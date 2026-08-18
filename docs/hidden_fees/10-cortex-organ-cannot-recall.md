# 10 — The cortex organ can typecheck, but it cannot remember

## The fee

C1 shipped the organ with a store that is **git-complete by design**: 1841 nodes,
1216 descriptions, 16 verbs, 4434 derived relations — and **0 `knowledge_objects`,
0 captures, 0 embeddings**. That property is what made C1 need no data migration,
no shared file and no two-writer decision, and it was the right way to land it.

> **The three zeros expired (re-measured 2026-08-18).** The organ now holds
> **359 `knowledge_objects` and 6 482 embeddings** — S2's parallel corpus has
> been landing, and `keap:keap-embed-sync` feeds it nightly ("cortex +40" on
> 08-18). So the half this entry is named for is no longer missing outright;
> what is unestablished is whether recall WORKS, which is a different and
> harder claim than whether vectors exist. `/agent/v1/context` returning
> results is the measurement, and nothing in this repo runs it.
>
> Two consequences worth carrying forward rather than leaving implied:
> `docs/hidden_fees/09`'s "only defensible while the organ holds no vectors"
> is therefore void — both stores now hold real corpora, and 09 has the live
> A/B numbers. And the caveat below about `captures` is stale in a smaller
> way: the organ has no `captures` table at all, so the count cannot be
> compared to KEAP's the way this entry assumes.

But the organ is named for the half it does not have. `Cortex` is *"remembers and
reasons"*; without vectors it only reasons. `/agent/v1/context` — the recall
endpoint the design names as the organ's second surface — has nothing to search.
`tax:` resolves, `kg:` cannot, and the skills and ontology that make the answers
useful live in the corpus that stayed behind.

So today the organ is a typechecker on a host port, and every question that
needs meaning still goes to KEAP.

## When the bill comes due

The moment anything is built that assumes the organ is the place reasoning
happens — a Wing executor path, an AgentKit runner, a second consumer of
`/validate` that then wants context. Each one silently re-establishes KEAP as the
real cortex, and C2 gets more expensive per consumer added.

It also compounds with [09](09-untuned-vector-index.md): the index the organ
would inherit is the untuned one.

## How it was found

Stated plainly by the operator, 2026-07-26: *"orgán bez vektorů je nepoužitelný —
to samé přístupné skills, ontologie."* The staging was designed and gated
correctly and every gate was green; nothing measured whether the result was
**useful**, which is exactly the shape of a fee.

## What closes it

**S2** in `docs/archive/cortex-self-core.md`: `knowledge_objects`, fs-sync,
captures, embeddings, hybrid search, `/graph`.

Restaged 2026-07-26. This entry originally called it "the real migration, a store
with no git source". **That was false and measurement said so**: every corpus row
has an external source — 166 of 170 objects are fs-sync mirrors, 3 are
converge-seeded, 1 is a mirror too, and all 128 captures are filesystem-derived.
So S2 rebuilds the corpus in parallel from the same host sources and diffs the
two, instead of migrating anything.

Until it lands, the honest description of the organ is "validate surface", and
the docs should say that rather than "the fourth brain".
