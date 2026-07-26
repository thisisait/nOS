/**
 * Hybrid corpus search — S4 (ROADMAP Track S), the retrieval recipe the
 * substrate research converged on:
 *
 *   lexical (FTS5/BM25 over the whole corpus)
 * ⊕ vector  (libSQL ANN, when the query can be embedded live)
 * ⊕ one-hop graph expansion (taxonomy parents/children of top hits,
 *   plus object⇄anchor hops via extracted links)
 *
 * fused by Reciprocal Rank Fusion: score(item) = Σ 1/(K + rank_in_leg).
 * RRF beats naive context concatenation (HybridRAG's precision collapse)
 * and needs no score calibration between legs.
 *
 * The lexical index is rebuilt lazily: write paths call markCorpusDirty()
 * and the next search re-derives corpus_fts from the SAME canonical texts
 * the embedding pipeline serves — the two legs always describe one corpus.
 * At personal-corpus scale (~1–10k rows) a full rebuild is a few ms.
 */
import * as db from './db';
import { allSources, embedText } from './embeddings';
import { getNode } from './taxonomy';
import { anchorNodeIds, type ObjectRef } from './objects';

const RRF_K = 60;
const LEG_FETCH = 40; // per-leg over-fetch before fusion

let corpusDirty = true;

/** Call after any write to objects / captures / curated metadata. */
export function markCorpusDirty(): void {
  corpusDirty = true;
}

function ensureCorpusFts(): void {
  if (!corpusDirty) return;
  db.rebuildCorpusFts(allSources());
  corpusDirty = false;
}

export interface SearchHit {
  kind: db.EmbeddingKind;
  refId: string;
  score: number;
  legs: string[]; // which legs contributed — explains WHY a hit ranks
}

type LegHit = { kind: db.EmbeddingKind; refId: string };

export interface SearchViewer {
  userId: string;
  seeAll: boolean;
  /** Authentik tier groups — threaded into the object-read ladder (S2⁶ §4). */
  groups: string[];
}

function visibleTo(h: LegHit, viewer?: SearchViewer): boolean {
  if (!viewer || h.kind === 'taxonomy' || h.kind === 'note') return true;
  if (h.kind === 'capture') return db.canReadCapture(h.refId, viewer.userId, viewer.seeAll);
  return db.canReadObject(h.refId, viewer.userId, viewer.seeAll, viewer.groups);
}

function key(h: LegHit): string {
  return `${h.kind}:${h.refId}`;
}

/** One-hop neighbours of a hit: tree edges for nodes, anchor links for objects. */
function hop(h: LegHit): LegHit[] {
  const out: LegHit[] = [];
  if (h.kind === 'taxonomy') {
    const n = getNode(h.refId);
    if (!n) return out;
    if (n.parentId) out.push({ kind: 'taxonomy', refId: n.parentId });
    for (const c of n.childIds.slice(0, 5)) out.push({ kind: 'taxonomy', refId: c });
  } else if (h.kind === 'object') {
    const o = db.getObject(h.refId);
    if (!o) return out;
    for (const a of anchorNodeIds((o.links ?? []) as ObjectRef[]).slice(0, 3)) {
      out.push({ kind: 'taxonomy', refId: a });
    }
  }
  return out;
}

export async function hybridSearch(
  query: string,
  kinds: db.EmbeddingKind[],
  limit: number,
  viewer?: SearchViewer,
): Promise<{ hits: SearchHit[]; legs: { lexical: boolean; vector: boolean; graph: boolean } }> {
  ensureCorpusFts();

  const legLists: Array<{ name: string; hits: LegHit[] }> = [];

  // Lexical leg — always available.
  const lexical = db.searchCorpusFts(query, kinds, LEG_FETCH).filter((hit) => visibleTo(hit, viewer));
  legLists.push({ name: 'lexical', hits: lexical });

  // Vector leg — only when the operator wired a live embedder.
  let vectorOk = false;
  const vec = await embedText(query);
  if (vec) {
    const hits = db
      .vectorNeighborsOf(JSON.stringify(vec), 'related', kinds, LEG_FETCH)
      .filter((hit) => visibleTo(hit, viewer));
    if (hits.length) {
      vectorOk = true;
      legLists.push({ name: 'vector', hits });
    }
  }

  // Graph leg — one hop out from the top hits of the other legs. Taxonomy
  // hops are always in-scope (they ARE the map); other kinds respect the
  // caller's kind filter.
  const hopSeeds = legLists.flatMap((l) => l.hits.slice(0, 5));
  const hopHits: LegHit[] = [];
  const seen = new Set(hopSeeds.map(key));
  for (const seed of hopSeeds) {
    for (const n of hop(seed)) {
      if (n.kind !== 'taxonomy' && !kinds.includes(n.kind)) continue;
      if (!visibleTo(n, viewer)) continue;
      if (seen.has(key(n))) continue;
      seen.add(key(n));
      hopHits.push(n);
    }
  }
  if (hopHits.length) legLists.push({ name: 'graph', hits: hopHits });

  // Reciprocal Rank Fusion.
  const fused = new Map<string, SearchHit>();
  for (const leg of legLists) {
    leg.hits.forEach((h, rank) => {
      const k = key(h);
      const entry = fused.get(k) ?? { kind: h.kind, refId: h.refId, score: 0, legs: [] };
      entry.score += 1 / (RRF_K + rank + 1);
      entry.legs.push(leg.name);
      fused.set(k, entry);
    });
  }

  const hits = [...fused.values()]
    .filter((h) => h.kind === 'taxonomy' ? kinds.includes('taxonomy') : true)
    .sort((a, b) => b.score - a.score)
    .slice(0, limit);

  return { hits, legs: { lexical: true, vector: vectorOk, graph: hopHits.length > 0 } };
}
