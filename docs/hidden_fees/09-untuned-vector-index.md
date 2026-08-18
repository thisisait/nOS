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
vectors — true on 2026-07-26, **false since**.

> **RE-MEASURED 2026-08-18 — the deferral's own precondition has expired, and
> the estate is now its own A/B test.** Both indexes hold real corpora on this
> host:
>
> | store | vectors | shadow index | per vector |
> |---|---|---|---|
> | KEAP (untuned, `libsql_vector_idx(vector)`) | 4 283 | **656.7 MB** | 157.0 KB |
> | cortex organ (`float8` + `max_neighbors=20`) | 6 482 | **126.7 MB** | 20.0 KB |
>
> **The organ holds 51% more vectors in 19% of the space** — 7.8× per vector,
> which lands between the synthetic table's prediction and the live 2026-07
> figure. KEAP's shadow grew 514 MB → 657 MB in three weeks on ~900 new
> vectors. Matching the organ's parameters would reclaim **≈573 MB** of a
> 726 MB database, where the entire rest of the knowledge — corpus FTS,
> taxonomy, relations, descriptions, history — is about 15 MB.
>
> The "two indexes with different parameters" condition this entry called
> defensible-for-now is therefore live, and the C2 sharp edge it warned about
> ("doing it after the corpus has moved is a rebuild of a bigger index") is
> being paid at 143 MB per three weeks.
>
> **Measuring trap, recorded because it cost a wrong conclusion here first:**
> `SELECT COUNT(*) FROM embeddings` returns **0** under stock `sqlite3` 3.51 on
> a libsql table carrying a vector index, while `SELECT rowid, kind … LIMIT 3`
> returns real rows. Count through a subquery — `SELECT COUNT(*) FROM (SELECT
> rowid FROM embeddings)` — or ask KEAP. Read naively, the store looks like it
> holds nothing and the whole index looks like dead pages.

## When the bill comes due

It is being paid now — **657 MB as of 2026-08-18, up from the 514 MB this entry
was written against** — and an 8× slower embed pass, and it scales with the
corpus. The sharp edge is C2: the organ inherits or diverges, and whichever
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
