# keap-linked-data — external-enrichment tooling for the KEAP star-map

Typing-first slice of the **KEAP node metadata + external dataset linkage** epic
(`docs/roadmap.md`). Resolves each KEAP concept node to a **Wikidata QID** and a
**type** (P31 → KEAP render bucket + schema.org-ish class), so the star-map can
grow an entity-type lens + typed celestial forms and (later) a scope-signal and a
temporal axis.

> Status: **offline PoC / review tool**, not yet wired into the playbook. It emits
> a reviewable artifact; nothing lands in the canonical SoT or the KEAP DB until
> the operator signs off on quality. Sibling of `tools/keap-semantic-lens/`.

## resolve-typing.py

```bash
# node list = GET http://127.0.0.1:8091/api/graph (loopback + X-Authentik-* headers)
curl -s -H "X-Authentik-Username: <you>" -H "X-Authentik-Groups: nos-providers|nos-admins" \
     http://127.0.0.1:8091/api/graph -o graph.json
python3 resolve-typing.py --graph graph.json --out qid-typing.json --cache wd-cache.json
```

Read-only against the public Wikidata API; every response is cached to `--cache`
so a re-run (e.g. after tuning the type buckets) is instant and re-queries nothing.

### Why not naive top-hit

The 2026-07-15 feasibility spike showed `wbsearchentities` top-hit is ~40% and
**homonym-trapped**: a node named "Diodes" matches an insect genus, "Possible
worlds" a John Mighton play, "Chemistry" a European journal. Two guards fix it:

1. **Disambiguation at search time** — score the top-6 candidates by their
   Wikidata `description` gloss (deny `journal|article|play|film|genus|…`, allow
   `discipline|science|theory|process|…`) + exact-label match + lexical overlap
   with our node description. Pick the best, not the first.
2. **P31 post-filter** — after fetching `instance-of` for the chosen QID, reject
   any whose P31 is a *specific publication/artwork/media instance* (scholarly
   article, thesis, patent, painting, book edition, …) — those are homonyms that
   beat the label match because their gloss carried no deny keyword.

### Output (`qid-typing.json`)

Per node: `{id, name, level, qid, label, desc, score, conf, reason, p31[],
keap_type, schema_type}`. Confidence tiers: **high** (exact label + concept-type),
**med** (exact OR type+overlap), **low** (weak — review), **none** (no clean
match — node carries no external identity, graceful fallback).

### Coverage reality (full 1750-node corpus, 2026-07-15)

| Level | nodes | usable (high+med) |
|-------|-------|-------------------|
| L0 | 12 | 41% |
| L1 | 95 | 70% |
| L2 | 255 | 69% |
| L3 | 476 | 48% |
| L4 | 897 | 15% |
| L5 | 15 | 6% |
| **all** | **1750** | **35%** |

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

## Next (post-review, not built)

- Storage: an optional `meta`/`links` block in the git-SoT canonical format +
  a `node_metadata` table beside `node_features`; land only high/med confidence.
- Wire as a Pulse job (parity with `keap-features-sync`) for periodic refresh.
- Scope-signal (OpenAlex `cited_by_count` / QRank) → node size; dates (P571/575/
  585, dated subset only) → temporal axis. See `docs/roadmap.md`.
