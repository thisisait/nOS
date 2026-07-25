import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import Database from 'libsql';
import { spawnSync } from 'node:child_process';
import crypto from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { annIndexExpr, applyAnnTuning, currentAnnIndexExpr, ANN_INDEX_NAME } from './cortex-ann';
import { resolveStoreConfig, ANN_DEFAULTS, STORE_DB_FILENAME } from './cortex-config';

/**
 * Cortex organ store — build sequence steps 4 and 6.
 *
 * The store-level cases run the CLI as a CHILD PROCESS rather than calling
 * `openStore()` in-process, for a reason that is structural and not stylistic:
 * `server/db.ts` holds its connection in module scope and `initDb()` returns
 * early once it is set (db.ts:335), and the data directory is captured at module
 * LOAD (db.ts:29). One vitest module graph therefore gets exactly ONE store, so
 * "a fresh store and a materialised store behave differently" is not expressible
 * in-process. A child per scenario also means these tests exercise the entry
 * point Ansible will call, not a parallel arrangement of the same functions.
 *
 * The ANN cases go the other way — straight at a hand-built libsql file — because
 * what they assert is about the index and not about the organ's boot.
 */

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ORGAN = path.resolve(HERE, '..');
const CLI = path.join(HERE, 'cortex-store-cli.ts');

/** The pinned fresh-store digest (design step 5). 790 spine nodes, zero ext rows,
 *  16 seed verbs. Asserted here as well as in the agreement suite because THIS is
 *  the file that proves the organ's own store — not a hand-seeded tmpdir —
 *  reproduces it. */
const FRESH_DIGEST = 'onto1:76d1f3ad728b382b';
const SPINE_NODES = 790;

interface CliResult {
  command: string;
  config: { storeDir: string; ann: typeof ANN_DEFAULTS };
  materialise: {
    spineInSync: boolean;
    ingest: {
      applied: string[];
      skipped: string[];
      changed: boolean;
      ontology: { types: number; relations: number; files: string[]; skipped: string[] };
    } | null;
    extNodesRegistered: number;
    descriptionOverrides: number;
    ftsRows: number;
    slugRoots: string[];
  };
  facts: {
    dbPath: string;
    dbIdentity: { id: string; freshThisBoot: boolean } | null;
    vectorSearchAvailable: boolean;
    ann: { outcome: string; indexed: boolean; indexExpr: string | null; vectors: number };
    taxonomyNodes: number;
    ftsRows: number;
    verbs: number;
    liveVerbs: number;
    toeRelations: number;
    ontologyVersion: string;
  };
}

function cli(
  command: string,
  storeDir: string,
  extraArgs: string[] = [],
  env: Record<string, string> = {},
): { status: number; out: string; result: CliResult | null } {
  const res = spawnSync(process.execPath, ['--import', 'tsx', CLI, command, '--json', ...extraArgs], {
    cwd: ORGAN,
    encoding: 'utf8',
    env: { ...process.env, CORTEX_STORE_PATH: storeDir, ...env },
    maxBuffer: 64 * 1024 * 1024,
  });
  const out = `${res.stdout ?? ''}${res.stderr ?? ''}`;
  const line = out.split('\n').find((l) => l.startsWith('CORTEX_STORE_RESULT '));
  return {
    status: res.status ?? -1,
    out,
    result: line ? (JSON.parse(line.slice('CORTEX_STORE_RESULT '.length)) as CliResult) : null,
  };
}

const TMP = fs.mkdtempSync(path.join(os.tmpdir(), 'cortex-store-'));
const dirFor = (name: string) => path.join(TMP, name);

afterAll(() => fs.rmSync(TMP, { recursive: true, force: true }));

// ---------------------------------------------------------------------------
// Step 4 — the store, and what git puts in it
// ---------------------------------------------------------------------------

describe('fresh store (no ingest)', () => {
  let r: CliResult;
  beforeAll(() => {
    const out = cli('init', dirFor('fresh'));
    expect(out.status, out.out).toBe(0);
    r = out.result!;
  });

  it('creates its libsql file inside the configured store directory', () => {
    expect(r.facts.dbPath).toBe(path.join(dirFor('fresh'), STORE_DB_FILENAME));
    expect(fs.existsSync(r.facts.dbPath)).toBe(true);
  });

  it('mints its OWN db_identity rather than inheriting one', () => {
    // cortex-full-scope-decision.md "Two corrections" #1. A UUID exists and it was
    // created by this boot — nothing was carried over from KEAP.
    expect(r.facts.dbIdentity?.id).toMatch(/^[0-9a-f-]{36}$/);
    expect(r.facts.dbIdentity?.freshThisBoot).toBe(true);
  });

  it('writes the store marker that claims the directory', () => {
    const marker = JSON.parse(fs.readFileSync(path.join(dirFor('fresh'), '.cortex-store.json'), 'utf8'));
    expect(marker.organ).toBe('pazny.cortex');
    expect(marker.dbIdentity).toBe(r.facts.dbIdentity?.id);
  });

  it('materialises the 790-node spine from git into the FTS index', () => {
    expect(r.materialise.spineInSync).toBe(true);
    expect(r.facts.taxonomyNodes).toBe(SPINE_NODES);
    expect(r.facts.ftsRows).toBe(SPINE_NODES);
    expect(r.materialise.extNodesRegistered).toBe(0);
  });

  it('seeds the 16-verb live vocabulary', () => {
    expect(r.facts.verbs).toBe(16);
    expect(r.facts.liveVerbs).toBe(16);
  });

  it('reproduces the pinned fresh-store onto1 digest', () => {
    expect(r.facts.ontologyVersion).toBe(FRESH_DIGEST);
  });
});

describe('git materialisation (canonical ingest)', () => {
  const dir = dirFor('materialised');
  let first: CliResult;

  beforeAll(() => {
    const out = cli('materialise', dir);
    expect(out.status, out.out).toBe(0);
    first = out.result!;
  });

  it('applies every canonical domain file through the ported ingest path', () => {
    expect(first.materialise.ingest?.applied.length).toBe(107);
    expect(first.materialise.ingest?.skipped).toEqual([]);
    expect(first.materialise.ingest?.changed).toBe(true);
  });

  it('grows the tree by the ext-node delta and re-projects the FTS index', () => {
    // NOT a hardcoded count. The ext delta is git's curated domains PLUS the
    // generated self-model, and the self-model's size is a function of the
    // ESTATE — it changes whenever a service is added or removed. A literal here
    // would fail on the next plugin, which teaches people to bump the number
    // rather than read it. Assert the relationship and the coverage instead.
    expect(first.materialise.extNodesRegistered).toBeGreaterThan(900);
    expect(first.facts.taxonomyNodes).toBe(SPINE_NODES + first.materialise.extNodesRegistered);
    // The coverage the 91-node gap was missing: a slug root must exist, or every
    // `nos.*` operand answers unknown_operand and the refusal looks well-formed.
    expect(first.materialise.slugRoots).toContain('nos');
    expect(first.facts.ftsRows).toBe(first.facts.taxonomyNodes);
  });

  it('mirrors the ToE concept relations into the generalized store', () => {
    expect(first.facts.toeRelations).toBe(4434);
  });

  it('applies the ontology verb registry without growing the live vocabulary', () => {
    // knowledge/ontology/relation-types.json carries exactly the 16 seed verbs
    // db.seedRelationTypes() already inserts, so the digest's verb half is
    // unmoved by ingest. A 17th verb here would silently change every AST binding.
    expect(first.materialise.ingest?.ontology.types).toBe(16);
    expect(first.facts.verbs).toBe(16);
    expect(first.facts.liveVerbs).toBe(16);
  });

  it('leaves the digest DIFFERENT from the fresh-store literal, and says so honestly', () => {
    // Not a regression: cortexOntologyVersion() hashes allNodes(), which includes
    // the merged ext nodes. The pinned literal describes a store with zero ext
    // rows. Conflating the two is the mistake this assertion exists to prevent.
    expect(first.facts.ontologyVersion).not.toBe(FRESH_DIGEST);
    expect(first.facts.ontologyVersion).toMatch(/^onto1:[0-9a-f]{16}$/);
  });

  it('materialises NO corpus — knowledge_objects stays empty (C1 boundary)', () => {
    const db = new Database(first.facts.dbPath, { readonly: true });
    const n = (db.prepare('SELECT COUNT(*) c FROM knowledge_objects').get() as { c: number }).c;
    db.close();
    expect(n).toBe(0);
  });

  it('is idempotent — a second run skips every file and lands the same digest', () => {
    const again = cli('materialise', dir);
    expect(again.status, again.out).toBe(0);
    expect(again.result!.materialise.ingest?.applied).toEqual([]);
    // The canonical layer and the ontology layer keep separate skip ledgers:
    // 107 domain files in `skipped`, the verb registry in `ontology.skipped`.
    expect(again.result!.materialise.ingest?.skipped.length).toBe(107);
    expect(again.result!.materialise.ingest?.ontology.skipped).toEqual(['types']);
    expect(again.result!.materialise.ingest?.changed).toBe(false);
    expect(again.result!.facts.ontologyVersion).toBe(first.facts.ontologyVersion);
    expect(again.result!.facts.taxonomyNodes).toBe(first.facts.taxonomyNodes);
    // Same database, not a recreated one.
    expect(again.result!.facts.dbIdentity?.id).toBe(first.facts.dbIdentity?.id);
    expect(again.result!.facts.dbIdentity?.freshThisBoot).toBe(false);
  });
});

describe('degradation when the vector layer is unavailable', () => {
  it('boots FTS-only instead of crashing, and still materialises the tree', () => {
    // A stock-SQLite build has no `libsql_vector_idx`, so db.ts's VECTOR_SCHEMA
    // throws and `vectorsOk` goes false (db.ts:344-350). We cannot swap the
    // native driver here, so we reproduce the same REJECTION: give `embeddings`
    // a TEXT vector column. `CREATE TABLE IF NOT EXISTS` no-ops over it and the
    // index create is then refused with "unexpected vector column type: TEXT" —
    // the identical code path.
    //
    // The vector layer is removed from a store the organ ALREADY OWNS rather
    // than hand-built into an empty directory. A hand-built `keap.db` under no
    // marker is indistinguishable from somebody else's database, and
    // `assertClaimable()` now refuses it before opening it — correctly, and this
    // fixture is not the exception to that. Losing the vector layer under an
    // existing deployment (a rebuilt libsql, a host migration) is also the shape
    // this degradation actually takes in the field.
    const dir = dirFor('novectors');
    const init = cli('init', dir);
    expect(init.status, init.out).toBe(0);
    const d = new Database(path.join(dir, STORE_DB_FILENAME));
    d.exec(`DROP INDEX IF EXISTS ${ANN_INDEX_NAME}`);
    d.exec('DROP TABLE embeddings');
    d.exec(`CREATE TABLE embeddings (
       kind TEXT NOT NULL, ref_id TEXT NOT NULL, model TEXT, dim INTEGER,
       content_hash TEXT, vector TEXT, updated_at INTEGER, PRIMARY KEY (kind, ref_id))`);
    d.close();

    const out = cli('materialise', dir);
    expect(out.status, out.out).toBe(0); // boots — a missing vector layer is not fatal
    const r = out.result!;
    expect(r.facts.vectorSearchAvailable).toBe(false);
    expect(r.facts.ann.outcome).toBe('unavailable');
    expect(r.facts.ann.indexed).toBe(false);
    // Everything that does not need vectors still works: the tree materialised
    // from git, the FTS projection is complete, the vocabulary is live.
    expect(r.facts.taxonomyNodes).toBe(SPINE_NODES + r.materialise.extNodesRegistered);
    expect(r.materialise.extNodesRegistered).toBeGreaterThan(900);
    expect(r.facts.ftsRows).toBe(r.facts.taxonomyNodes);
    expect(r.facts.liveVerbs).toBe(16);
    expect(r.facts.ontologyVersion).toMatch(/^onto1:[0-9a-f]{16}$/);
  });
});

/** Everything the organ could have written into a store directory, as one
 *  comparable value: the bytes of every file plus the set of filenames. A
 *  refusal has to leave this IDENTICAL — that is what "never a second writer"
 *  means, and it is the half the old assertions never checked. */
function dirFingerprint(dir: string): { files: string[]; sha: Record<string, string> } {
  const files = fs.readdirSync(dir).sort();
  const sha: Record<string, string> = {};
  for (const f of files) {
    sha[f] = crypto.createHash('sha256').update(fs.readFileSync(path.join(dir, f))).digest('hex');
  }
  return { files, sha };
}

/** Open a store file, run some SQL, and leave NOTHING behind but `keap.db` —
 *  the WAL is checkpointed and truncated away so the fingerprint above is stable
 *  across the handle's lifetime rather than across libsql's flushing whims. */
function withDb(dbPath: string, fn: (d: Database.Database) => void): void {
  const d = new Database(dbPath);
  try {
    fn(d);
    d.pragma('wal_checkpoint(TRUNCATE)');
  } finally {
    d.close();
  }
  for (const suffix of ['-wal', '-shm']) {
    const p = dbPath + suffix;
    if (fs.existsSync(p)) fs.rmSync(p);
  }
}

describe('the organ never adopts a foreign store', () => {
  it('refuses a populated store that carries no cortex marker', () => {
    const dir = dirFor('foreign');
    const out = cli('materialise', dir);
    expect(out.status).toBe(0);
    // Simulate "CORTEX_STORE_PATH points at somebody else's data directory":
    // the rows are there, the organ's claim is not.
    fs.rmSync(path.join(dir, '.cortex-store.json'));
    const refused = cli('status', dir);
    expect(refused.status).toBe(1);
    expect(refused.out).toContain('FOREIGN store');
  });

  it('refuses a database it has never seen WITHOUT OPENING IT — not one byte written', () => {
    // The guard's whole claim is "it is never a second writer on another
    // service's libsql file". A guard that runs after `initDb()` cannot make
    // that claim: `initDb()` sets journal_mode=WAL, execs the schema, applies
    // every migration the target lacks and INSERTs a db_identity — so the
    // refusal, however well worded, arrives after the write it names.
    //
    // The file here is deliberately NOT KEAP-shaped: its content lives in a
    // table the organ has never heard of, which is what a row-count predicate
    // over two hand-picked tables reads as "empty".
    const dir = dirFor('foreign-untouched');
    fs.mkdirSync(dir, { recursive: true });
    const dbPath = path.join(dir, STORE_DB_FILENAME);
    withDb(dbPath, (d) => {
      d.exec('CREATE TABLE somebody_elses_ledger (id INTEGER PRIMARY KEY, note TEXT)');
      d.prepare("INSERT INTO somebody_elses_ledger (id, note) VALUES (1, 'not the organ''s')").run();
    });
    const before = dirFingerprint(dir);

    const refused = cli('status', dir);
    expect(refused.status).toBe(1);
    expect(refused.out).toContain('FOREIGN store');
    expect(refused.out).toContain('nothing has been opened and nothing has been\nwritten');

    // Byte-for-byte, filename-for-filename. No WAL, no -shm, no marker: the
    // refusal is a decision made on the filesystem, before any handle exists.
    expect(dirFingerprint(dir)).toEqual(before);
    expect(before.files).toEqual([STORE_DB_FILENAME]);

    // And the schema is still the foreign one — no SCHEMA exec, no migrations.
    const d = new Database(dbPath, { readonly: false });
    const tables = (
      d.prepare("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").all() as Array<{
        name: string;
      }>
    ).map((r) => r.name);
    d.close();
    expect(tables).toEqual(['somebody_elses_ledger']);
  });

  it('refuses a KEAP-shaped store whose rows live outside ext-nodes and objects', () => {
    // The reachable production case: a KEAP instance provisioned and serving
    // before its canonical-ingest step has run (taxonomy_nodes_ext empty) and
    // without KEAP_USER_FILES_DIR (knowledge_objects empty). It still holds
    // course progress, curated metadata, captures and moderated relations —
    // none of which a two-table `populated` predicate can see, so the organ
    // claimed the directory and then rebuilt the FTS index, reseeded the verb
    // vocabulary and DELETEd the source='toe' relations inside somebody else's
    // live database, exit 0.
    const dir = dirFor('foreign-keapshaped');
    const init = cli('init', dir);
    expect(init.status, init.out).toBe(0);
    const dbPath = path.join(dir, STORE_DB_FILENAME);

    withDb(dbPath, (d) => {
      d.prepare(
        `INSERT INTO course_progress (user_id, course_id, progress, completed_chapters)
         VALUES ('alice', 7, 42, 3)`,
      ).run();
      // The two tables the old predicate DID look at stay empty, which is the
      // entire point: this store is unmistakably somebody's, and invisible.
      expect((d.prepare('SELECT COUNT(*) c FROM taxonomy_nodes_ext').get() as { c: number }).c).toBe(0);
      expect((d.prepare('SELECT COUNT(*) c FROM knowledge_objects').get() as { c: number }).c).toBe(0);
    });
    fs.rmSync(path.join(dir, '.cortex-store.json'));
    const before = dirFingerprint(dir);

    const refused = cli('status', dir);
    expect(refused.status).toBe(1);
    expect(refused.out).toContain('FOREIGN store');
    expect(refused.out).not.toContain('[store] claimed');
    expect(dirFingerprint(dir)).toEqual(before);
    expect(fs.existsSync(path.join(dir, '.cortex-store.json'))).toBe(false);
  });

  it('never writes a foreign db_identity into its own marker', () => {
    // cortex-full-scope-decision.md "Two corrections" #1. If the organ adopts a
    // directory whose db_identity it did not mint, `/health`'s
    // `binding.databaseId` and every `ast.binding` it stamps carry someone
    // else's id — and Wing's "databaseId moved ⇒ REJECT" drift check reports
    // AGREEMENT across two different databases. The mechanism that exists to
    // catch a replaced store would be the thing hiding one.
    const dir = dirFor('foreign-identity');
    const init = cli('init', dir);
    expect(init.status, init.out).toBe(0);
    const FOREIGN_ID = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee';

    withDb(path.join(dir, STORE_DB_FILENAME), (d) => {
      d.prepare(
        `UPDATE app_settings SET value = ? WHERE user_id = 'system' AND key = 'db_identity'`,
      ).run(JSON.stringify({ id: FOREIGN_ID, initializedAt: 1700000000 }));
    });
    fs.rmSync(path.join(dir, '.cortex-store.json'));

    const refused = cli('status', dir);
    expect(refused.status).toBe(1);
    expect(fs.existsSync(path.join(dir, '.cortex-store.json'))).toBe(false);
    expect(refused.out).not.toContain(FOREIGN_ID);
  });

  it('refuses when the file under the marker was replaced', () => {
    const dir = dirFor('replaced');
    const out = cli('init', dir);
    expect(out.status).toBe(0);
    // The 2026-07-22 signal: same directory, same marker, different database.
    fs.rmSync(path.join(dir, STORE_DB_FILENAME));
    for (const suffix of ['-wal', '-shm']) {
      const p = path.join(dir, STORE_DB_FILENAME + suffix);
      if (fs.existsSync(p)) fs.rmSync(p);
    }
    const refused = cli('init', dir);
    expect(refused.status).toBe(1);
    expect(refused.out).toContain('identity mismatch');
    expect(refused.out).toContain('was REPLACED');
  });
});

describe('store configuration', () => {
  it('resolves CORTEX_STORE_PATH, then ~/cortex/data — and NEVER KEAP_DATA_DIR', () => {
    expect(resolveStoreConfig({ CORTEX_STORE_PATH: '/a', KEAP_DATA_DIR: '/b' }).storeDir).toBe('/a');
    // KEAP_DATA_DIR is KEAP's vocabulary for KEAP's data directory. Honouring it
    // as a fallback aimed an UNCONFIGURED organ at another service's live
    // libsql file — precisely the environments the default exists for. The
    // fallback's stated justification ("so the vendored tests keep working")
    // was false: cortex-resolve.test.ts:20, onto1-agreement.test.ts:37 and
    // onto1-digest.test.ts:70 set KEAP_DATA_DIR and import server/db.ts, which
    // reads the variable ITSELF. None of them calls resolveStoreConfig.
    expect(resolveStoreConfig({ KEAP_DATA_DIR: '/b' }).storeDir).toBe(path.join(os.homedir(), 'cortex', 'data'));
    expect(resolveStoreConfig({}).storeDir).toBe(path.join(os.homedir(), 'cortex', 'data'));
  });

  it('an unconfigured organ lands in its OWN default, not in an inherited KEAP_DATA_DIR', () => {
    // The unit assertion above proves the resolver; this proves the BOOT, which
    // is where it matters — `openStore()` mkdirs the resolved directory and
    // opens a database in it. A unit that runs with a shared EnvironmentFile, a
    // compose env_file, or an operator shell that sourced KEAP's environment
    // gets KEAP_DATA_DIR for free; `cortex_store_path` is the thing that might
    // not be templated yet. HOME is redirected so "the default" is observable
    // without writing into the developer's real ~/cortex/data.
    const home = dirFor('nofallback-home');
    const keapDir = dirFor('nofallback-keapdata');
    fs.mkdirSync(home, { recursive: true });
    fs.mkdirSync(keapDir, { recursive: true });

    const env: NodeJS.ProcessEnv = { ...process.env, HOME: home, USERPROFILE: home, KEAP_DATA_DIR: keapDir };
    delete env.CORTEX_STORE_PATH;
    const res = spawnSync(process.execPath, ['--import', 'tsx', CLI, 'init', '--json'], {
      cwd: ORGAN,
      encoding: 'utf8',
      env,
      maxBuffer: 64 * 1024 * 1024,
    });
    const out = `${res.stdout ?? ''}${res.stderr ?? ''}`;
    expect(res.status, out).toBe(0);
    const line = out.split('\n').find((l) => l.startsWith('CORTEX_STORE_RESULT '))!;
    const parsed = JSON.parse(line.slice('CORTEX_STORE_RESULT '.length)) as CliResult;

    expect(parsed.facts.dbPath).toBe(path.join(home, 'cortex', 'data', STORE_DB_FILENAME));
    // The inherited directory was never resolved to, never mkdir'd into, never
    // opened. It is as empty as it was handed over.
    expect(fs.readdirSync(keapDir)).toEqual([]);
  });

  it('defaults the ANN parameters to the measured optimum', () => {
    expect(resolveStoreConfig({}).ann).toEqual({ compressNeighbors: 'float8', maxNeighbors: 20 });
  });

  it('rejects an unparseable ANN parameter instead of dropping the index for it', () => {
    // applyAnnTuning DROPs before it CREATEs, so a value libsql would reject must
    // never reach it — the store would be left with no vector index at all.
    expect(() => resolveStoreConfig({ CORTEX_ANN_COMPRESS_NEIGHBORS: 'float4' })).toThrow(/not one of/);
    expect(() => resolveStoreConfig({ CORTEX_ANN_MAX_NEIGHBORS: 'twenty' })).toThrow(/positive integer/);
    expect(resolveStoreConfig({ CORTEX_ANN_COMPRESS_NEIGHBORS: 'none' }).ann.compressNeighbors).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Step 6 — the ANN index
// ---------------------------------------------------------------------------

describe('ANN index tuning', () => {
  /** A store shaped exactly like db.ts's VECTOR_SCHEMA, with db.ts's DEFAULT index. */
  function vectorStore(name: string, rows = 40): Database.Database {
    const d = new Database(path.join(TMP, `${name}.db`));
    d.pragma('journal_mode = WAL');
    d.exec(`CREATE TABLE IF NOT EXISTS embeddings (
       kind TEXT NOT NULL, ref_id TEXT NOT NULL, model TEXT NOT NULL, dim INTEGER NOT NULL,
       content_hash TEXT NOT NULL, vector F32_BLOB(768),
       updated_at INTEGER DEFAULT (strftime('%s','now')), PRIMARY KEY (kind, ref_id))`);
    d.exec(`CREATE INDEX IF NOT EXISTS ${ANN_INDEX_NAME} ON embeddings(libsql_vector_idx(vector))`);
    let s = 7;
    const vec = () => {
      const a: string[] = [];
      for (let i = 0; i < 768; i++) {
        s = (s * 1103515245 + 12345) % 2147483648;
        a.push((s / 2147483648 - 0.5).toFixed(5));
      }
      return `[${a.join(',')}]`;
    };
    const ins = d.prepare(
      `INSERT INTO embeddings (kind, ref_id, model, dim, content_hash, vector)
       VALUES ('taxonomy', ?, 'nomic-embed-text', 768, ?, vector32(?))`,
    );
    d.transaction(() => {
      for (let i = 0; i < rows; i++) ins.run(`n${i}`, `h${i}`, vec());
    })();
    return d;
  }

  it('builds the expression at the measured optimum', () => {
    expect(annIndexExpr(ANN_DEFAULTS)).toBe(
      "libsql_vector_idx(vector, 'compress_neighbors=float8', 'max_neighbors=20')",
    );
    expect(annIndexExpr({ compressNeighbors: null, maxNeighbors: null })).toBe('libsql_vector_idx(vector)');
  });

  it('retunes db.ts’s default index in place and keeps the rows searchable', () => {
    const d = vectorStore('ann-retune');
    expect(currentAnnIndexExpr(d)).toBe('libsql_vector_idx(vector)');

    const status = applyAnnTuning(d, ANN_DEFAULTS, true);
    expect(status.outcome).toBe('retuned');
    expect(status.indexed).toBe(true);
    expect(status.indexExpr).toBe(annIndexExpr(ANN_DEFAULTS));
    expect(status.vectors).toBe(40);

    // The rebuild REINDEXED what was already there — the retune is not a wipe.
    const hit = d
      .prepare(
        `SELECT e.ref_id FROM vector_top_k('${ANN_INDEX_NAME}', (SELECT vector FROM embeddings WHERE ref_id = 'n3'), 5) v
         JOIN embeddings e ON e.rowid = v.id`,
      )
      .all() as Array<{ ref_id: string }>;
    expect(hit.map((r) => r.ref_id)).toContain('n3');
    d.close();
  });

  it('is idempotent — a second call reports already-tuned and rebuilds nothing', () => {
    const d = vectorStore('ann-idempotent');
    expect(applyAnnTuning(d, ANN_DEFAULTS, true).outcome).toBe('retuned');
    expect(applyAnnTuning(d, ANN_DEFAULTS, true).outcome).toBe('already-tuned');
    d.close();
  });

  it('survives db.ts re-running its own default DDL on a later boot', () => {
    // This is what makes tuning-outside-db.ts viable at all: initDb() executes
    // VECTOR_SCHEMA on every boot, and IF NOT EXISTS against an already-tuned
    // index is a no-op that PRESERVES the parameters. If this ever regressed,
    // every restart would silently revert the store to the 514 MB shape.
    const d = vectorStore('ann-survives-initdb');
    applyAnnTuning(d, ANN_DEFAULTS, true);
    d.exec(`CREATE INDEX IF NOT EXISTS ${ANN_INDEX_NAME} ON embeddings(libsql_vector_idx(vector))`);
    expect(currentAnnIndexExpr(d)).toBe(annIndexExpr(ANN_DEFAULTS));
    d.close();
  });

  it('degrades to a no-op when the vector layer is unavailable', () => {
    // db.ts's vectorsOk try/catch (db.ts:344-350) is the contract: a stock-SQLite
    // build keeps FTS and the tree, and loses only semantic recall. Tuning must
    // not be the thing that turns that graceful degradation into a crash.
    const d = new Database(path.join(TMP, 'ann-novectors.db'));
    d.exec('CREATE TABLE IF NOT EXISTS embeddings (kind TEXT, ref_id TEXT, vector BLOB)');
    const status = applyAnnTuning(d, ANN_DEFAULTS, false);
    expect(status.outcome).toBe('unavailable');
    expect(status.indexed).toBe(false);
    expect(status.indexExpr).toBeNull();
    d.close();
  });

  it('restores db.ts’s default index when the tuned DDL is rejected', () => {
    const d = vectorStore('ann-rejected', 5);
    const status = applyAnnTuning(d, { compressNeighbors: 'float8', maxNeighbors: -1 }, true);
    expect(status.outcome).toBe('rejected-restored-default');
    expect(status.indexed).toBe(true);
    expect(currentAnnIndexExpr(d)).toBe('libsql_vector_idx(vector)');
    d.close();
  });

  it('accounts for the DiskANN shadow so the size win is observable', () => {
    const d = vectorStore('ann-shadow');
    const status = applyAnnTuning(d, ANN_DEFAULTS, true);
    expect(status.shadowBytes).not.toBeNull();
    expect(status.shadowBytes!).toBeGreaterThan(0);
    d.close();
  });
});
