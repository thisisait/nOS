# keap-linked-data — external-enrichment tooling for the KEAP star-map

Typing-first slice of the **KEAP node metadata + external dataset linkage** epic
(`docs/archive/roadmap-2026q3.md` § KEAP — the prose roadmap was retired
2026-08-07; live rows are `tools/roadmap-status.py --track cortex`). Resolves
each KEAP concept node to a **Wikidata QID** and a
**type** (P31 → KEAP render bucket + schema.org-ish class), so the star-map can
grow an entity-type lens + typed celestial forms and (later) a scope-signal and a
temporal axis.

> Status: **offline PoC / review tool**, not yet wired into the playbook. It emits
> a reviewable artifact; nothing lands in the canonical SoT or the KEAP DB until
> the operator signs off on quality. Sibling of `tools/keap-semantic-lens/`.

## resolve-typing.py

```bash
# node list + node embeddings via loopback (X-Authentik headers / RO agent token)
curl -s -H "X-Authentik-Username: <you>" -H "X-Authentik-Groups: nos-providers|nos-admins" \
     http://127.0.0.1:8091/api/graph -o graph.json
curl -s -H "authorization: Bearer $KEAP_AGENT_TOKEN_RO" \
     http://127.0.0.1:8091/agent/v1/features/vectors -o vectors.json
python3 resolve-typing.py --graph graph.json --vectors vectors.json \
     --out qid-typing.json --cache wd-cache.json
```

Read-only against the public Wikidata API; every response is cached to `--cache`
so a re-run (e.g. after tuning the type buckets) is instant and re-queries nothing.
`--vectors` enables semantic disambiguation (needs Ollama `nomic-embed-text`); the
per-node cosine map is cached to `<vectors>.sem.json` so bucket iteration stays fast.
Omit `--vectors` for a lexical-only pass.

### Why not naive top-hit

The 2026-07-15 feasibility spike showed `wbsearchentities` top-hit is ~40% and
**homonym-trapped**: a node named "Diodes" matches an insect genus, "Possible
worlds" a John Mighton play, "Chemistry" a European journal, "Maritime" a region
of Togo, "Heaps" a surname. Three guards fix it:

1. **Disambiguation at search time** — score the top-6 candidates by their
   Wikidata `description` gloss (deny `journal|article|play|film|genus|…`, allow
   `discipline|science|theory|process|…`) + exact-label match + lexical overlap
   with our node description. Pick the best, not the first.
2. **P31 post-filter** — after fetching `instance-of` for the chosen QID, reject
   any whose P31 is a *specific publication/artwork/media instance* (scholarly
   article, thesis, patent, painting, book edition, …) — those are homonyms that
   beat the label match because their gloss carried no deny keyword.
3. **Semantic veto/boost** (`--vectors`) — embed each candidate's Wikidata gloss
   via Ollama and cosine it against our node's own embedding (fetched from the
   container, same nomic space). A candidate scores `+SEM_W·cosine`; a best-pick
   under cosine `0.45` is vetoed even on an exact label. This is what rejects
   "Maritime→region of Togo" (cos 0.41) and flips "Heaps→surname" to the CS sense
   (cos 0.72) — the wrong-sense errors the lexical guards can't see.

### Output (`qid-typing.json`)

Per node: `{id, name, level, qid, label, desc, score, conf, reason, p31[],
keap_type, schema_type}`. Confidence tiers: **high** (exact label + concept-type),
**med** (exact OR type+overlap), **low** (weak — review), **none** (no clean
match — node carries no external identity, graceful fallback).

### Coverage reality (full 1750-node corpus, 2026-07-15)

| Level | nodes | usable (high+med) |
|-------|-------|-------------------|
| L0 | 12 | 41% |
| L1 | 95 | 69% |
| L2 | 255 | 66% |
| L3 | 476 | 47% |
| L4 | 897 | 15% |
| L5 | 15 | 6% |
| **all** | **1750** | **34%** (high 395 / med 212) |

Semantic disambiguation trades a few `med` for precision (wrong-sense rejects)
and promotes correct-sense matches to `high` (339→395) — the usable set is smaller
but cleaner. Lexical-only (no `--vectors`) yields ~618 usable but leaks wrong-sense
homonyms like Maritime→Togo.

The spine resolves the **structural upper tree well** (L0-L3 disciplines/fields/
named concepts ≈ 55-70%) and the **deep pedagogical leaves poorly** (L4-L5 ≈ 15%
— many aren't canonical Wikidata entities). This matches the render vision:
galaxies→planets (L0-L3) get rich typed bodies + external metadata; satellites
(L4+) stay plain. Metadata is optional per node by design.

### Type buckets (render facet)

`discipline · theory · process · quantity · substance · organism · person ·
event · technology · place · work · concept` (fallback). Drives the entity-type
lens and typed celestial forms. Tune `BUCKETS` / `REJECT_P31` at the top of the
script and re-run (cache-fast) to refine.

## Scope-signal (QRank) — `--qrank`

Join the resolved QIDs against the **QRank** dump (`qrank.toolforge.org/download/
qrank.csv.gz`, ~105 MB, `Entity,QRank` = QID → Wikimedia-pageview popularity) to
get a knowledge-scope signal per node — a real external "how important/broad is
this concept" measure that can drive render node-size (vs. today's subtree-size).

```bash
curl -sL https://qrank.toolforge.org/download/qrank.csv.gz -o qrank.csv.gz
python3 resolve-typing.py --graph graph.json --vectors vectors.json \
     --qrank qrank.csv.gz --post http://127.0.0.1:8091   # RW token via env
```

`scope_rank` = raw QRank; `scope_norm` = log-min-max 0-1 over the resolved set
(QRank is heavy-tailed). Landed in `node_metadata`, served as `node.meta.scopeRank
/scopeNorm`. Sanity: AI/Roman Empire/Renaissance top out ~1.0; Barley/Boiling/
Oats bottom ~0.25. ~48 of the 607 QIDs are absent from QRank (no scope, graceful).
The QRank public file is frozen at 2024-03 — fine for a slow-moving popularity
signal; OpenAlex `cited_by_count` is the live alternative for science branches.

## Next (post-review, not built)

- Promote reviewed QIDs into the git-SoT canonical `meta` block (permanence);
  optionally wire as a Pulse job (parity with `keap-features-sync`) — though the
  QID/scope resolution is stable, so occasional re-runs beat a nightly recompute.
- OpenAlex `cited_by_count` (science-branch scope, live) + dates (P571/575/585,
  dated subset only) → temporal axis. See `docs/archive/roadmap-2026q3.md`.
