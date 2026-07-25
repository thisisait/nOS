/**
 * Vector corpus for `scripts/ann-recall.mjs` — LOCALLY AUTHORED (not a port).
 *
 * `ann-recall.mjs` takes `--vectors <exported.json>` and its docstring says to
 * export that from a live DB. The cortex organ has no live embeddings: the
 * embedder is deliberately outside the organ (host Ollama, driven by the Pulse
 * job `keap-embed-sync`, build-sequence step 10), so at step 6 the store's
 * `embeddings` table is empty. Something has to produce the vectors, or step 6
 * cannot be measured at all — only asserted.
 *
 * Two modes, and the difference matters:
 *
 *   --from-store   export whatever the organ's own store holds. The real thing.
 *                  Use it the moment embed-sync has run; it is the only mode
 *                  whose recall number describes THIS corpus.
 *   --synthetic    generate a CLUSTERED corpus at the same shape (N=3356,
 *                  dim=768 by default, matching docs/specs/durability-and-
 *                  integrity.md §4).
 *
 * ── Why clustered, and not random ───────────────────────────────────────────
 *
 * `durability-and-integrity.md` §4 is explicit that the earlier synthetic probe
 * proved only the SIZE figures, because it "used random near-orthogonal vectors,
 * so '10 results returned' says nothing about *which* 10". That criticism is
 * correct and it applies to any uniform-random generator: in 768 dimensions
 * random points are all nearly equidistant, so every candidate index scores the
 * same and the harness discriminates nothing.
 *
 * So this generates structure instead: `--clusters` centroids, each vector a
 * centroid plus gaussian noise at `--spread`, L2-normalised (the embeddings are
 * compared with `vector_distance_cos`). That produces genuine near-neighbours to
 * find or miss, which is the property recall@10 needs to mean anything. The
 * harness's own `CONTROL mn=3` variant is what proves the discrimination is
 * real: on this corpus it must score materially WORSE than the candidates. If it
 * ties them, the corpus is too easy and the 100%s above it are worthless.
 *
 * A synthetic recall number is still evidence about the INDEX PARAMETERS, not
 * about KEAP's semantics. It answers "does neighbour compression lose
 * neighbours at this N and dimensionality", which is exactly what step 6 asks.
 *
 *   node scripts/ann-corpus.mjs --out vectors.json [--n 3356] [--dim 768]
 *                               [--clusters 120] [--spread 0.35] [--seed 20260725]
 *   node scripts/ann-corpus.mjs --out vectors.json --from-store
 */
import Database from 'libsql';
import { writeFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const arg = (n, d) => {
  const i = process.argv.indexOf(`--${n}`);
  return i >= 0 && process.argv[i + 1] && !process.argv[i + 1].startsWith('--') ? process.argv[i + 1] : d;
};
const has = (n) => process.argv.includes(`--${n}`);

const OUT = arg('out', null);
if (!OUT) {
  console.error('usage: node scripts/ann-corpus.mjs --out <vectors.json> [--from-store | --synthetic]');
  console.error('       [--n 3356] [--dim 768] [--clusters 120] [--spread 0.35] [--seed 20260725]');
  process.exit(2);
}

let rows;

if (has('from-store')) {
  const storeDir = process.env.CORTEX_STORE_PATH ?? process.env.KEAP_DATA_DIR ?? path.join(os.homedir(), 'cortex', 'data');
  const dbPath = path.join(storeDir, 'keap.db');
  const db = new Database(dbPath, { readonly: true });
  rows = db
    .prepare('SELECT kind, ref_id, vector_extract(vector) v FROM embeddings WHERE vector IS NOT NULL')
    .all()
    .map((r) => [`${r.kind}:${r.ref_id}`, r.v]);
  db.close();
  if (rows.length === 0) {
    console.error(
      `${dbPath} holds no embeddings. The embedder is outside the organ (Pulse job keap-embed-sync,\n` +
        'build-sequence step 10); until it has run, measure with --synthetic instead.',
    );
    process.exit(4);
  }
  console.log(`exported ${rows.length} vectors from ${dbPath}`);
} else {
  const N = Number(arg('n', 3356));
  const DIM = Number(arg('dim', 768));
  const CLUSTERS = Number(arg('clusters', 120));
  const SPREAD = Number(arg('spread', 0.35));

  // Deterministic: the same LCG shape ann-recall.mjs uses for its query sample,
  // so a re-run compares like with like across variants AND across sessions.
  let seed = Number(arg('seed', 20260725));
  const unit = () => (seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648;
  // Box-Muller over the LCG — gaussian noise, not uniform, so a cluster is a
  // ball rather than a cube and the nearest-neighbour ordering is smooth.
  const gauss = () => {
    const u = Math.max(unit(), 1e-12);
    return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * unit());
  };
  const normalise = (v) => {
    let n = 0;
    for (const x of v) n += x * x;
    n = Math.sqrt(n) || 1;
    return v.map((x) => x / n);
  };

  const centroids = Array.from({ length: CLUSTERS }, () => normalise(Array.from({ length: DIM }, gauss)));
  rows = Array.from({ length: N }, (_, i) => {
    const c = centroids[i % CLUSTERS];
    const v = normalise(c.map((x) => x + SPREAD * gauss()));
    return [`v${i}`, `[${v.map((x) => x.toFixed(6)).join(',')}]`];
  });
  console.log(`generated ${N} vectors, dim ${DIM}, ${CLUSTERS} clusters, spread ${SPREAD}`);
}

writeFileSync(OUT, JSON.stringify(rows));
console.log(`wrote ${OUT}`);
console.log('ANN_CORPUS_RESULT ' + JSON.stringify({ vectors: rows.length, out: OUT, fromStore: has('from-store') }));
