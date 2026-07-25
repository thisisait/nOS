/**
 * Cortex organ runtime configuration — LOCALLY AUTHORED (not a port).
 *
 * Everything under `server/`, `knowledge/`, `shared/` and `src/game/` except this
 * file, `cortex-ann.ts`, `cortex-store.ts` and `cortex-store-cli.ts` is a
 * byte-identical lift of KEAP v1.27.0. This module is the seam between the
 * vendored code and the organ's own deployment shape, and it exists precisely so
 * that the seam is ONE file rather than a diff smeared across the port.
 *
 * ── The store filename is `keap.db`, and that is deliberate ──────────────────
 *
 * `docs/plans/nos-cortex-organ-design.md` §3 wrote the store as
 * `~/cortex/data/cortex.db`. It is `~/cortex/data/keap.db`, because TWO vendored
 * files independently derive the basename from a directory env var:
 *
 *   server/db.ts:29-30      DATA_DIR = process.env.KEAP_DATA_DIR ?? …
 *                           DB_PATH  = path.join(DATA_DIR, 'keap.db')
 *   knowledge/ingest.mjs:42 DATA_DIR = process.env.KEAP_DATA_DIR ?? '/app/data'
 *                        :60 DB_PATH  = path.join(DATA_DIR, 'keap.db')
 *
 * Renaming the file means editing both, which converts "re-sync from KEAP is a
 * plain `cp`" into "re-sync is a two-hunk patch that a careless merge drops" —
 * for a cosmetic gain. The DIRECTORY is what actually isolates the organ, the
 * directory is what config controls, and the directory is what the port already
 * parameterises. So `cortex_store_path` names the store DIRECTORY.
 *
 * This is NOT the "shared keap.db" that `docs/specs/cortex-full-scope-decision.md`
 * forbids. Same basename, different directory, different file, different
 * `db_identity`, and `cortex-store.ts` refuses to open a store file it did not
 * create — see `assertClaimable()` there. The organ never reads KEAP's store.
 *
 * ── Precedence, and the fallback that is NOT here ───────────────────────────
 *
 *   CORTEX_STORE_PATH   the organ's own var (Ansible `cortex_store_path`)
 *   ~/cortex/data       default, matching `bone_runtime_dir: ~/bone`
 *
 * `KEAP_DATA_DIR` is deliberately NOT consulted. It was, until it was noticed
 * that the stated reason ("so the VENDORED tests that point the port at a
 * throwaway tmpdir keep working untouched") was simply false: those tests —
 * `server/cortex-resolve.test.ts:20`, `onto1-agreement.test.ts:37`,
 * `onto1-digest.test.ts:70` — set `process.env.KEAP_DATA_DIR` and then
 * `await import('./db')`, and db.ts:29 reads that variable ITSELF. None of them
 * calls `resolveStoreConfig`, so the fallback never protected anything.
 *
 * What it did do was point the organ's store at KEAP's data directory in exactly
 * the environments where nobody had templated `cortex_store_path` — the case the
 * default exists for. `KEAP_DATA_DIR` is KEAP's vocabulary
 * (`knowledge/ingest.mjs:25`), so honouring it converts "the operator forgot to
 * configure the organ" from "the organ uses its own default" into "the organ
 * aims itself at another service's live libsql file". `assertClaimable()` would
 * refuse it, but a guard is not a reason to hand it the address.
 *
 * `openStore()` still SETS `KEAP_DATA_DIR` from the resolved directory — that is
 * how the vendored `db.ts` and `knowledge/ingest.mjs` are aimed. The flow is one
 * way: out of this module, never into it.
 */
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

/** Fixed by the vendored port (server/db.ts:30, knowledge/ingest.mjs:60). Not ours to choose. */
export const STORE_DB_FILENAME = 'keap.db';

/** Marker written into the store directory on first init. Its presence is the
 *  organ's claim on the directory: `cortex-store.ts` refuses — before opening
 *  anything — a directory that already holds a store file this marker does not
 *  cover, whatever that file's schema or row counts happen to be. */
export const STORE_MARKER_FILENAME = '.cortex-store.json';

/** Repo root of the vendored organ (…/files/anatomy/cortex), derived from this
 *  module's own location so a CLI invoked from any cwd finds `knowledge/`. */
export const ORGAN_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

/**
 * The `libsql_vector_idx` parameters. Defaults are the MEASURED optimum from
 * `docs/specs/durability-and-integrity.md` §4 — 65.6 MB shadow / 6.2 s build for
 * 3356 vectors, recall@10 = 100%.
 *
 * `float1bit` is smaller (41.0 MB) and is NOT the default on purpose: it is the
 * variant expected to degrade first as N grows, and this store is a knowledge
 * system where an index that answers slightly wrong questions is a bad trade.
 * It stays *reachable* (retuning at 20-50k nodes is a named follow-up) but a
 * deployment has to ask for it by name.
 */
export interface AnnConfig {
  /** `compress_neighbors` value, or null to omit the parameter entirely. */
  compressNeighbors: 'float8' | 'float1bit' | 'float16' | null;
  /** `max_neighbors` value, or null to omit the parameter entirely. */
  maxNeighbors: number | null;
}

export const ANN_DEFAULTS: AnnConfig = { compressNeighbors: 'float8', maxNeighbors: 20 };

const ANN_COMPRESSIONS = new Set(['float8', 'float1bit', 'float16']);

export interface CortexStoreConfig {
  /** Directory holding the store. Ansible `cortex_store_path`. */
  storeDir: string;
  /** Full path to the libsql file — `storeDir/keap.db`, see the header. */
  dbPath: string;
  /** Marker file asserting the organ owns `storeDir`. */
  markerPath: string;
  /** Canonical knowledge tree the ingest path materialises from. */
  canonicalDir: string;
  /** Spine SoT the generated `src/game/data/taxonomy.ts` is rendered from. */
  spineDir: string;
  /** `knowledge/ingest.mjs`, run as a child process (it opens its own handle). */
  ingestScript: string;
  /** `knowledge/spine-render.mjs --check`, the spine drift gate. */
  spineRenderScript: string;
  ann: AnnConfig;
}

function envStoreDir(env: NodeJS.ProcessEnv): string {
  const explicit = env.CORTEX_STORE_PATH?.trim();
  if (explicit) return path.resolve(explicit);
  // No KEAP_DATA_DIR fallback — see the header. An unconfigured organ gets its
  // OWN default, never another service's data directory.
  return path.join(os.homedir(), 'cortex', 'data');
}

/**
 * Read the ANN parameters from the environment.
 *
 * A typo is a HARD ERROR rather than a fallback. `applyAnnTuning` drops the
 * existing index before creating the tuned one, so a value libsql rejects would
 * leave the store with no vector index at all — the failure this validation
 * exists to make impossible. `none` (or an empty value) omits the parameter,
 * which is how you ask for the shipped default.
 */
function envAnn(env: NodeJS.ProcessEnv): AnnConfig {
  const rawCompress = env.CORTEX_ANN_COMPRESS_NEIGHBORS?.trim();
  let compressNeighbors = ANN_DEFAULTS.compressNeighbors;
  if (rawCompress !== undefined) {
    if (rawCompress === '' || rawCompress === 'none') compressNeighbors = null;
    else if (ANN_COMPRESSIONS.has(rawCompress)) compressNeighbors = rawCompress as AnnConfig['compressNeighbors'];
    else {
      throw new Error(
        `CORTEX_ANN_COMPRESS_NEIGHBORS=${JSON.stringify(rawCompress)} is not one of ` +
          `${[...ANN_COMPRESSIONS].join(', ')}, 'none'. Refusing to drop the vector index for a value libsql would reject.`,
      );
    }
  }

  const rawMax = env.CORTEX_ANN_MAX_NEIGHBORS?.trim();
  let maxNeighbors = ANN_DEFAULTS.maxNeighbors;
  if (rawMax !== undefined) {
    if (rawMax === '' || rawMax === 'none') maxNeighbors = null;
    else {
      const n = Number(rawMax);
      if (!Number.isInteger(n) || n < 1) {
        throw new Error(`CORTEX_ANN_MAX_NEIGHBORS=${JSON.stringify(rawMax)} is not a positive integer.`);
      }
      maxNeighbors = n;
    }
  }

  return { compressNeighbors, maxNeighbors };
}

export function resolveStoreConfig(env: NodeJS.ProcessEnv = process.env): CortexStoreConfig {
  const storeDir = envStoreDir(env);
  const knowledge = path.join(ORGAN_ROOT, 'knowledge');
  return {
    storeDir,
    dbPath: path.join(storeDir, STORE_DB_FILENAME),
    markerPath: path.join(storeDir, STORE_MARKER_FILENAME),
    canonicalDir: env.CORTEX_CANONICAL_DIR?.trim()
      ? path.resolve(env.CORTEX_CANONICAL_DIR.trim())
      : path.join(knowledge, 'canonical'),
    spineDir: path.join(knowledge, 'spine'),
    ingestScript: path.join(knowledge, 'ingest.mjs'),
    spineRenderScript: path.join(knowledge, 'spine-render.mjs'),
    ann: envAnn(env),
  };
}
