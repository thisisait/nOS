/**
 * ANN recall harness — does a cheaper vector index still find the right neighbours?
 *
 * `keap.db` is 561 MB, of which 514.6 MB is `embeddings_vec_idx_shadow` for 3.4k
 * vectors: the index is built with default `libsql_vector_idx()` parameters, so
 * every DiskANN node stores its neighbours uncompressed. Compressed variants are
 * 8–12× smaller and 8× faster to build. The open question was never the size —
 * it was whether compression quietly degrades retrieval.
 *
 * `scripts/recall-gate.mjs` CANNOT answer that, and it is worth being precise
 * about why, because "run the recall gate before and after" is the obvious plan
 * and it is wrong twice over:
 *
 *   1. It carries four hand-written cases at k=5. That is a tripwire for a gross
 *      regression (nine `_stack.md` cards outranking real content), not an
 *      instrument that can resolve a few percent of ranking quality.
 *   2. It measures the whole hybrid stack — RRF over lexical + vector + graph.
 *      The lexical and graph legs can carry a case whose vector leg got worse,
 *      so a green gate after compression is consistent with a materially worse
 *      index.
 *
 * This measures the vector leg directly, and needs no labelled queries: for each
 * sampled query it computes the TRUE top-k by exhaustive `vector_distance_cos`
 * scan, then asks the index, and reports the overlap. Ground truth is defined by
 * the same distance function the app uses, so the number means exactly what it
 * says: "of the k nearest neighbours, how many does this index actually return".
 *
 * The semantic gate stays the end-to-end guard. Green there is NECESSARY, not
 * sufficient; this is the sufficient half.
 *
 *   node scripts/ann-recall.mjs --vectors <exported.json> [--k 10] [--queries 200]
 *
 * `--vectors` is `[[refId, "[f1,f2,…]"], …]` — export from a live DB with:
 *   select kind, ref_id, vector_extract(vector) v from embeddings
 */
import Database from 'libsql';
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const arg = (n, d) => {
  const i = process.argv.indexOf(`--${n}`);
  return i >= 0 && process.argv[i + 1] ? process.argv[i + 1] : d;
};
const VECTORS = arg('vectors', null);
const K = Number(arg('k', 10));
const NQ = Number(arg('queries', 200));
if (!VECTORS) {
  console.error('usage: node scripts/ann-recall.mjs --vectors <exported.json> [--k 10] [--queries 200]');
  process.exit(2);
}

/** The variants worth deciding between. `default` is what ships today. */
const VARIANTS = [
  ['default (today)', 'libsql_vector_idx(vector)'],
  ['float8', "libsql_vector_idx(vector, 'compress_neighbors=float8')"],
  ['max_neighbors=20', "libsql_vector_idx(vector, 'max_neighbors=20')"],
  ['float8 + mn=20', "libsql_vector_idx(vector, 'compress_neighbors=float8', 'max_neighbors=20')"],
  ['float1bit', "libsql_vector_idx(vector, 'compress_neighbors=float1bit')"],
  // DISCRIMINATION CONTROL, not a candidate. A 3-neighbour graph is crippled by
  // construction: if this scores as well as the others, the harness is measuring
  // nothing and every 100% above is meaningless.
  ['CONTROL mn=3', "libsql_vector_idx(vector, 'max_neighbors=3')"],
];

const raw = JSON.parse(readFileSync(VECTORS, 'utf8'));
const dim = JSON.parse(raw[0][1]).length;
console.log(`${raw.length} vectors, dim ${dim}, k=${K}, ${NQ} sampled queries\n`);

// Deterministic sample: a fixed LCG, so a re-run compares like with like and a
// variant cannot look better by drawing easier queries.
let seed = 20260725;
const next = () => (seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648;
const queryIdx = [];
const seen = new Set();
while (queryIdx.length < Math.min(NQ, raw.length)) {
  const i = Math.floor(next() * raw.length);
  if (!seen.has(i)) { seen.add(i); queryIdx.push(i); }
}

const TMP = mkdtempSync(path.join(os.tmpdir(), 'keap-ann-'));
const results = [];

try {
  // Ground truth once: an exhaustive scan is independent of any index.
  let truth = null;

  for (const [name, idxExpr] of VARIANTS) {
    const p = path.join(TMP, name.replace(/[^a-z0-9]+/gi, '_') + '.db');
    const db = new Database(p);
    db.exec('PRAGMA journal_mode=WAL');
    db.exec(`CREATE TABLE embeddings (kind TEXT NOT NULL, ref_id TEXT NOT NULL, model TEXT NOT NULL, dim INTEGER NOT NULL, content_hash TEXT NOT NULL, vector F32_BLOB(${dim}), updated_at INTEGER, PRIMARY KEY (kind, ref_id))`);
    let rejected = null;
    try { db.exec(`CREATE INDEX embeddings_vec_idx ON embeddings(${idxExpr})`); }
    catch (e) { rejected = e.message.slice(0, 80); }

    const ins = db.prepare(`INSERT INTO embeddings (kind, ref_id, model, dim, content_hash, vector, updated_at) VALUES ('v', ?, 'nomic', ${dim}, ?, vector32(?), 1)`);
    const t0 = Date.now();
    db.transaction(() => { for (const [ref, v] of raw) ins.run(ref, ref, v); })();
    const buildMs = Date.now() - t0;
    db.exec('PRAGMA wal_checkpoint(TRUNCATE)');

    const shadow = db.prepare("select coalesce(sum(pgsize),0) b from dbstat where name like '%vec_idx_shadow%'").get().b;

    // Ground truth from the FIRST database (the vectors are identical in all of
    // them, and an exhaustive scan ignores the index entirely).
    if (!truth) {
      const exact = db.prepare(`SELECT ref_id FROM embeddings ORDER BY vector_distance_cos(vector, vector32(?)) LIMIT ${K}`);
      truth = queryIdx.map((i) => exact.all(raw[i][1]).map((r) => r.ref_id));
    }

    let hits = 0, total = 0, qMs = 0;
    if (!rejected) {
      const ann = db.prepare(`SELECT e.ref_id FROM vector_top_k('embeddings_vec_idx', vector32(?), ${K}) AS v JOIN embeddings e ON e.rowid = v.id`);
      const t1 = Date.now();
      queryIdx.forEach((qi, n) => {
        const got = new Set(ann.all(raw[qi][1]).map((r) => r.ref_id));
        for (const want of truth[n]) if (got.has(want)) hits++;
        total += truth[n].length;
      });
      qMs = Date.now() - t1;
    }
    db.close();

    const recall = total ? hits / total : 0;
    results.push({ name, rejected, shadowMb: shadow / 1048576, buildMs, qUs: total ? (qMs * 1000) / queryIdx.length : 0, recall });
    console.log(
      name.padEnd(18),
      rejected ? `INDEX REJECTED: ${rejected}` :
      `shadow ${(shadow / 1048576).toFixed(1).padStart(6)} MB | build ${String(buildMs).padStart(6)}ms | ${(qMs * 1000 / queryIdx.length).toFixed(0).padStart(4)}µs/q | recall@${K} ${(recall * 100).toFixed(2)}%`,
    );
  }

  const base = results.find((r) => !r.rejected);
  console.log('\nrelative to the shipped default:');
  for (const r of results) {
    if (r.rejected) continue;
    console.log(
      `  ${r.name.padEnd(18)} size ×${(r.shadowMb / base.shadowMb).toFixed(3).padStart(6)}  build ×${(r.buildMs / base.buildMs).toFixed(2).padStart(5)}  recall@${K} ${(r.recall * 100).toFixed(2)}% (default ${(base.recall * 100).toFixed(2)}%)`,
    );
  }
  console.log('\nANN_RECALL_RESULT ' + JSON.stringify({ k: K, queries: queryIdx.length, vectors: raw.length, results }));
} finally {
  rmSync(TMP, { recursive: true, force: true });
}
