/**
 * ANN index tuning — LOCALLY AUTHORED (not a port). Build sequence step 6.
 *
 * `server/db.ts:330-331` creates the vector index with DEFAULT parameters:
 *
 *     CREATE INDEX IF NOT EXISTS embeddings_vec_idx
 *       ON embeddings(libsql_vector_idx(vector))
 *
 * which is the shape `docs/specs/durability-and-integrity.md` §4 measured at
 * **514.6 MB of shadow for 3356 vectors** — 153 KB per vector, where the 768-d
 * f32 payload is 3 KB. The measured optimum is `compress_neighbors=float8` +
 * `max_neighbors=20` → **65.6 MB / 6.2 s build**, at recall@10 = 100%.
 *
 * ── Why this is a separate module and not an edit to db.ts ───────────────────
 *
 * Changing the DDL in `db.ts` is a one-line edit that costs the port its
 * byte-identity with KEAP. It is also unnecessary, because of a property that
 * was verified empirically before this module was written:
 *
 *   1. `DROP INDEX embeddings_vec_idx` removes `embeddings_vec_idx_shadow` and
 *      `embeddings_vec_idx_shadow_idx` with it — no orphaned shadow.
 *   2. Re-creating with parameters REINDEXES the rows already in `embeddings`;
 *      `vector_top_k` answers over pre-existing data immediately after.
 *   3. `sqlite_master.sql` records the exact expression text, parameters
 *      included, so the live tuning is READABLE and therefore checkable.
 *   4. Re-running db.ts's own `CREATE INDEX IF NOT EXISTS …(libsql_vector_idx(
 *      vector))` against an already-tuned index is a NO-OP that PRESERVES the
 *      parameters.
 *
 * (4) is the load-bearing one: it means `initDb()` cannot clobber the tuning on
 * a later boot, so retuning after `initDb()` is durable rather than a race the
 * next restart undoes. The organ therefore keeps `db.ts` verbatim and adjusts
 * the index behind it.
 *
 * ── Degradation ─────────────────────────────────────────────────────────────
 *
 * `db.ts` wraps VECTOR_SCHEMA in a try/catch that sets `vectorsOk = false` on a
 * stock-SQLite build (no `libsql_vector_idx`), leaving FTS and the tree working.
 * This module preserves that contract exactly: it is a no-op when
 * `vectorSearchAvailable()` is false, and if the tuned DDL is itself rejected it
 * RESTORES db.ts's default index rather than leaving the store index-less. A
 * tuning failure must degrade to "correct but bigger", never to "no index".
 */
import type Database from 'libsql';
import type { AnnConfig } from './cortex-config';

/** The index name is db.ts's (`server/db.ts:330`). We change its parameters, never its name —
 *  `vector_top_k('embeddings_vec_idx', …)` is spelled out in db.ts's query paths. */
export const ANN_INDEX_NAME = 'embeddings_vec_idx';

/** db.ts's own DDL, verbatim in spirit — the fallback if a tuned create is rejected. */
const DEFAULT_INDEX_EXPR = 'libsql_vector_idx(vector)';

export type AnnOutcome =
  /** libsql vector layer missing — db.ts already set vectorsOk=false. */
  | 'unavailable'
  /** Index already carried the requested parameters. */
  | 'already-tuned'
  /** Dropped and rebuilt at the requested parameters. */
  | 'retuned'
  /** Tuned DDL was rejected; db.ts's default index was restored. */
  | 'rejected-restored-default'
  /** Tuned DDL was rejected AND the default could not be restored. */
  | 'rejected-no-index';

export interface AnnStatus {
  outcome: AnnOutcome;
  /** True when the store ends this call with a working vector index. */
  indexed: boolean;
  /** The `libsql_vector_idx(...)` expression the index now carries, as SQLite reports it. */
  indexExpr: string | null;
  requested: AnnConfig;
  /** Bytes attributed to the DiskANN shadow table, or null when `dbstat` is unavailable. */
  shadowBytes: number | null;
  /** Rows in `embeddings` at the time of the call — the N the shadow size is for. */
  vectors: number;
  /** Rejection message, when one applies. */
  error?: string;
}

/** Build the index expression for a tuning. Parameter order is fixed
 *  (`compress_neighbors` then `max_neighbors`) so the stored SQL is comparable
 *  across boots rather than depending on how the config was assembled. */
export function annIndexExpr(ann: AnnConfig): string {
  const params: string[] = [];
  if (ann.compressNeighbors) params.push(`'compress_neighbors=${ann.compressNeighbors}'`);
  if (ann.maxNeighbors != null) params.push(`'max_neighbors=${ann.maxNeighbors}'`);
  return `libsql_vector_idx(vector${params.map((p) => `, ${p}`).join('')})`;
}

function ddl(expr: string): string {
  return `CREATE INDEX ${ANN_INDEX_NAME} ON embeddings(${expr})`;
}

/** The `libsql_vector_idx(...)` expression the live index carries, or null when
 *  there is no such index. Whitespace-normalised so a formatting difference does
 *  not read as a tuning difference and trigger a pointless rebuild. */
export function currentAnnIndexExpr(d: Database.Database): string | null {
  const row = d
    .prepare(`SELECT sql FROM sqlite_master WHERE type = 'index' AND name = ?`)
    .get(ANN_INDEX_NAME) as { sql: string | null } | undefined;
  if (!row?.sql) return null;
  const m = /libsql_vector_idx\s*\(([\s\S]*)\)\s*\)\s*$/.exec(row.sql.trim());
  if (!m) return null;
  return `libsql_vector_idx(${m[1].replace(/\s+/g, ' ').trim()})`;
}

/** Bytes the DiskANN shadow occupies. `dbstat` is a compile-time option; when it
 *  is missing this returns null rather than pretending the index is free. */
export function annShadowBytes(d: Database.Database): number | null {
  try {
    const row = d
      .prepare(`SELECT coalesce(sum(pgsize), 0) b FROM dbstat WHERE name LIKE '%${ANN_INDEX_NAME}_shadow%'`)
      .get() as { b: number };
    return row.b;
  } catch {
    return null;
  }
}

function countVectors(d: Database.Database): number {
  try {
    return (d.prepare('SELECT COUNT(*) c FROM embeddings').get() as { c: number }).c;
  } catch {
    return 0;
  }
}

/**
 * Bring `embeddings_vec_idx` to the requested parameters.
 *
 * Idempotent: a store already at the requested tuning is left completely alone,
 * so this is safe to call on every boot (and is — `openStore()` does).
 */
export function applyAnnTuning(
  d: Database.Database,
  ann: AnnConfig,
  vectorsAvailable: boolean,
): AnnStatus {
  const requested = ann;
  if (!vectorsAvailable) {
    return {
      outcome: 'unavailable',
      indexed: false,
      indexExpr: null,
      requested,
      shadowBytes: null,
      vectors: 0,
    };
  }

  const want = annIndexExpr(ann);
  const have = currentAnnIndexExpr(d);
  const vectors = countVectors(d);

  if (have === want) {
    return {
      outcome: 'already-tuned',
      indexed: true,
      indexExpr: have,
      requested,
      shadowBytes: annShadowBytes(d),
      vectors,
    };
  }

  d.exec(`DROP INDEX IF EXISTS ${ANN_INDEX_NAME}`);
  try {
    d.exec(ddl(want));
    return {
      outcome: 'retuned',
      indexed: true,
      indexExpr: currentAnnIndexExpr(d),
      requested,
      shadowBytes: annShadowBytes(d),
      vectors,
    };
  } catch (err) {
    // The tuned DDL was rejected. Never leave the store without an index — put
    // db.ts's own default back, which is the shape that has always worked.
    const error = err instanceof Error ? err.message : String(err);
    try {
      d.exec(ddl(DEFAULT_INDEX_EXPR));
      return {
        outcome: 'rejected-restored-default',
        indexed: true,
        indexExpr: currentAnnIndexExpr(d),
        requested,
        shadowBytes: annShadowBytes(d),
        vectors,
        error,
      };
    } catch (restoreErr) {
      return {
        outcome: 'rejected-no-index',
        indexed: false,
        indexExpr: null,
        requested,
        shadowBytes: null,
        vectors,
        error: `${error} (default index could not be restored either: ${
          restoreErr instanceof Error ? restoreErr.message : String(restoreErr)
        })`,
      };
    }
  }
}
