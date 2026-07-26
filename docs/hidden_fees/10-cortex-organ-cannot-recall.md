# 10 — The cortex organ can typecheck, but it cannot remember

## The fee

C1 shipped the organ with a store that is **git-complete by design**: 1841 nodes,
1216 descriptions, 16 verbs, 4434 derived relations — and **0 `knowledge_objects`,
0 captures, 0 embeddings**. That property is what made C1 need no data migration,
no shared file and no two-writer decision, and it was the right way to land it.

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

C2 — the corpus and its ingestion: `knowledge_objects`, fs-sync, captures,
embeddings, hybrid search, `/graph`. It is the real migration (a store with no git
source) and it needs its own design pass, not a stretch of C1. Until it is
scheduled, the honest description of the organ is "validate surface", and the
docs should say that rather than "the fourth brain".
