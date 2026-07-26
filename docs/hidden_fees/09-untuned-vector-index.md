# 09 — The vector index is 8× larger than it needs to be

## The fee

KEAP creates its ANN index with `libsql_vector_idx(vector)` and no parameters
(`server/db.ts:330`), so every DiskANN node stores its neighbours uncompressed.

Measured on the live store, 2026-07-26: `embeddings_vec_idx_shadow` is
**538 732 480 B (513.8 MB)** of a 565 MB database, for 3355 embeddings — about
153 KB per vector, where 768-d float32 is 3 KB. A synthetic reproduction at the
same corpus size matches the live figure exactly, which is what makes the
alternatives trustworthy:

| parameters | shadow | insert of 3356 |
|---|---|---|
| default (today) | 514.6 MB | 48.3 s |
| `float8` + `max_neighbors=20` | **65.6 MB** | **6.2 s** |

The cortex organ already ships tuned. So the estate now runs **two indexes with
different parameters**, which is only defensible while the organ holds no
vectors — true today (0 embeddings), false at C2.

## When the bill comes due

It is being paid now, at 449 MB and an 8× slower embed pass, and it scales with
the corpus. The sharp edge is C2: the organ inherits or diverges, and whichever
happens, doing it after the corpus has moved is a rebuild of a bigger index.

## How it was found

Measured during the 2026-07-24 durability review, deferred on 2026-07-25 with
"the store is moving, do not retune". C2 has no date. **A deferral whose
precondition is unscheduled is not a deferral — it is a decision to keep
paying**, and that is what makes this a fee rather than a plan.

## What closes it

The sequencing is already written and is not optional: run `npm run gate:recall`
to establish the baseline, change the DDL behind a migration that rebuilds the
index, re-run, accept only a variant that holds. Neighbour compression is exactly
the kind of change that degrades meaning quietly, and the size column must not
decide it. The blocker that justified waiting — "recall cost is unmeasured" —
stopped being true when the gate reached instrument grade in KEAP v1.28.0.

Detail: KEAP `docs/specs/durability-and-integrity.md` §4.
