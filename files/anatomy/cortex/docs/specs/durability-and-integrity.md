# Durability & data integrity — review and doctrine

Status: **review of 2026-07-24, acted on in part.** Written against v1.25.0 after
the live database was found to have been recreated two days earlier without
anyone noticing.

## 1. What happened on 2026-07-22

The live data directory (`/Volumes/SSD1TB/nOS/data/platform/services/keap/data`)
was replaced during the v1.24.0 converge. Evidence, all from the live DB:

- every row in `schema_migrations` carries the same `applied_at`,
  `2026-07-22 18:39 UTC` — six migrations do not apply in the same second on a
  database that already existed;
- the directory itself dates from 18:52 that day, and holds no prior file;
- every `knowledge_objects` row post-dates it;
- no backup of the previous database exists at that path or beside it.

**What came back by itself:** the taxonomy (1840 nodes), descriptions,
briefs, ToE relations (4434) — all re-ingested from `knowledge/canonical/`; and
165 cards re-synced from `nos-docs`. **What did not:** the 15 derived R3
relations from the 2026-07-20 fill. `relations` held only `source='toe'` rows.

The material loss was small — those 15 edges were machine-proposed, unmoderated,
and re-derivable. The *finding* is not small:

> A layer with no source outside the container is invisible when it disappears,
> because every layer that does have one rebuilds itself and the system looks
> healthy.

Two days passed. Nothing in the product could have told anyone.

Ruled out along the way: `syncToeRelations` (server/db.ts) deletes strictly
`WHERE source = 'toe'`, so the boot mirror was not the cause.

## 2. The gap, stated as a table

| layer | carrier | SoT | survives a blank |
| --- | --- | --- | --- |
| skeleton — taxonomy, descriptions, briefs | `taxonomy_nodes_ext`, `node_descriptions`, `taxonomy_metadata` | `knowledge/canonical/` | yes |
| ToE relations | `concept_relations` | `knowledge/canonical/` | yes |
| **assertions — R3 typed edges + verdicts** | `relations` | **none → `knowledge/ontology/`** | **no → yes** |
| **the controlled vocabulary** | `relation_types` | **code seed only → `knowledge/ontology/`** | **seed only → yes** |
| evidence — cards | `knowledge_objects` | fs-sync roots (`/user-files`) | yes |
| embeddings, layout, topic clusters | derived | — | regenerated |

The taxonomy layer was already right: git SoT, an idempotent importer, an
inverse dumper, a linter, and a CI gate proving `ingest ∘ dump = identity`. The
discipline was sound; it just did not reach far enough. **Moderation verdicts are
human work product** — the one thing in the system that cannot be recomputed —
and they were the one thing living only in a volume.

## 3. What was implemented

`knowledge/ontology/` — the R3 layer as versioned, reviewable, replayable data.
Format spec: `knowledge/_schema/ontology-format.md`.

- `relation-types.json` — the verb registry including moderated growth. A verb
  an admin confirmed into the palette exists *only* here; the code seed
  (`RELATION_TYPE_SEED`) is a floor, not a record.
- `relations/<L0>.json` — typed edges partitioned by the L0 of their taxonomy
  endpoint, each carrying its **moderation verdict** and full provenance
  (confidence, justification, model, `createdAt`).
- `dump.mjs` / `ingest.mjs` / `lint.mjs` / `roundtrip.mjs` extended; ownership of
  a row by a file is defined once in `_ontology.mjs` and imported by all four,
  because three scripts disagreeing by one row is a silent corruption.

Two design decisions worth restating, since both are departures from the
canonical layer and both are deliberate:

1. **Additive upsert, never wipe-then-insert.** `relations` has two writers —
   this importer and the live agent surface. A per-partition wipe would delete
   every edge proposed since the last dump. Nothing is lost by never deleting,
   because nothing in the system hard-deletes a derived edge: removal is
   `status='rejected'`, which the files carry — and a rejected row restored from
   git additionally stops the classifier re-proposing that pair after a rebuild,
   which a mere absence would not.
2. **`source='toe'` is excluded.** Those rows mirror `concept_relations`, which
   `canonical/` already versions. One edge under two sources of truth is a
   guarantee they will eventually disagree with no way to adjudicate.

Where git and a live verdict conflict, git wins **loudly**: every overwritten
verdict is named in `INGEST_RESULT.ontology.statusConflicts`. Unknown verbs and
malformed rows are dropped and named rather than imported, so a file cannot route
around the vocabulary gate the live moderation layer enforces.

### Detection

`/agent/v1/health` gained two fields:

- `database` — `{ id, initializedAt, freshThisBoot }`. The id is stored *inside*
  the database, so it cannot survive a recreation: **a changed id is proof the
  file was replaced.** A database that predates the field is adopted rather than
  reported fresh (the discriminator is content, so existing deployments do not
  cry wolf on their first upgraded boot). A blank boot also logs a loud warning
  naming the ontology layer as the thing with no other source.
- `ontology` — `{ verbs, toeRelations, curatedRelations, byStatus }`.
  `curatedRelations` is the count with no rebuild path other than
  `knowledge/ontology`; zero there on a system that had edges means the SoT was
  never ingested, not that the classifier found nothing.

This is the piece that turns a silent replacement into something a monitor can
alert on. `uptime-kuma` already runs in this stack.

### Gates

`knowledge.yml` runs lint + round-trip on every `knowledge/**` change, and now
also `vitest run knowledge`. That last step matters: `roundtrip.mjs` can only
gate shapes the repo's own files contain, and the ontology layer shipped with
**zero relations in it** — so on its own it proved nothing about the relation
format. `ontology-sot.test.ts` supplies what the repo lacks (every status, both
sources, optional fields present and absent, and the rejection paths). It lives
in the knowledge workflow because `app.yml` carries `paths-ignore: knowledge/**`
— a knowledge-only change would otherwise skip the suite written to gate it.

## 4. Measured, not yet acted on: the vector index

`keap.db` is **561 MB with a 116 MB WAL** for a corpus of 3356 embeddings.
`dbstat` attributes **514.6 MB of it to `embeddings_vec_idx_shadow`** — roughly
153 KB per vector, where 768-d float32 is 3 KB.

The index is created with defaults: `libsql_vector_idx(vector)`
(`server/db.ts:330`), so every DiskANN node stores its neighbours uncompressed.
A synthetic reproduction at the same corpus size reproduces the live figure
exactly (514.6 MB), which is what makes the alternatives below trustworthy:

| index parameters | shadow size | insert of 3356 vectors |
| --- | --- | --- |
| default (today) | 514.6 MB | 48.3 s |
| `compress_neighbors=float8` | 224.5 MB | 23.6 s |
| `max_neighbors=20` | 209.8 MB | 16.4 s |
| `compress_neighbors=float8` + `max_neighbors=20` | 65.6 MB | 6.2 s |
| `compress_neighbors=float1bit` | 41.0 MB | 8.3 s |

The size and write-throughput wins are large (an 8× faster embed pass also means
far less WAL churn). **The recall cost is unmeasured** — the probe above used
random near-orthogonal vectors, so "10 results returned" says nothing about
*which* 10, and neighbour compression is exactly the kind of change that
degrades meaning quietly.

That is what `npm run gate:recall` (v1.22) exists for: it measures ranking on the
real corpus through the real hybrid search path. **Sequencing: run the recall
gate against the current index to establish the baseline, change the DDL behind a
migration that rebuilds the index, re-run the gate, and accept only a variant
that holds.** A cheaper index that answers slightly wrong questions is a bad
trade for a knowledge system, and this is a decision that must be made on the
gate's number, not on the size column.

## 5. Standing doctrine

1. **Anything a human moderated has a source outside the container.** If it
   cannot be recomputed, it is versioned — otherwise its loss is undetectable by
   construction.
2. **Absence is not emptiness.** A dump writes its files even when empty; a
   missing file and an empty one must never look alike.
3. **Two writers means additive.** Any store the live system writes to as well as
   git is upserted, never wiped by partition.
4. **Conflicts are named, never resolved quietly.** Git winning is a policy;
   git winning silently is data loss with extra steps.
5. **The database publishes its own identity.** Rebuilt corpora hide
   replacements; an id that cannot survive one does not.

## 6. Open

- Vector index tuning, gated on recall (§4).
- No backup of `keap.db` exists. With the ontology layer versioned, the curated
  layers are all reconstructible from git + fs roots, which is the stronger
  guarantee — but the derived layers (embeddings, layout, topic-cluster identity)
  still cost a full re-embed to rebuild. Whether that warrants a snapshot is a
  cost question, not a correctness one.
- `knowledge/canonical` is bind-mounted into the container from a separate host
  checkout while `knowledge/ontology` ships in the image. The two can therefore
  be at different versions — worth aligning on the nOS side.
