/**
 * The Cortex organ's runtime store — LOCALLY AUTHORED (not a port).
 * Build sequence steps 4 and 6.
 *
 * This is the organ's boot path: it points the vendored `server/db.ts` at the
 * organ's OWN libsql file, materialises the taxonomy + vocabulary FROM GIT, and
 * brings the ANN index to its measured tuning. It is the only module that knows
 * both the deployment shape and the port, and it deliberately holds all of that
 * knowledge so no vendored file has to.
 *
 * ── Two things this store is NOT ────────────────────────────────────────────
 *
 * Both are written as live intent in `docs/plans/nos-cortex-organ-design.md` and
 * both were overturned by `docs/specs/cortex-full-scope-decision.md`
 * ("Two corrections"):
 *
 *   1. It does NOT inherit KEAP's `db_identity`. `initDb()` mints a fresh UUID on
 *      first boot. A cortex store wearing KEAP's UUID would make "is this the
 *      same database?" — the question that caught the 2026-07-22 wipe — a lie on
 *      day one. Bindings carry a 900 s TTL, so the blast radius of not
 *      inheriting is one TTL of drift rejections, and a drift rejection is the
 *      mechanism working.
 *   2. It does NOT share, open, read or copy KEAP's `keap.db`. `assertOwnStore()`
 *      below makes that mechanical rather than aspirational: a populated store
 *      the organ did not create is REFUSED, not adopted.
 *
 * ── Git materialisation ─────────────────────────────────────────────────────
 *
 * Everything in this store has a source in this repository. Nothing is migrated
 * from anywhere, which is exactly why C1 is first in the cutover sequence.
 *
 *   spine (790 nodes)   knowledge/spine/*.json
 *                         └─ rendered by knowledge/spine-render.mjs into the
 *                            checked-in src/game/data/taxonomy.ts, which
 *                            server/taxonomy.ts compiles in. `--check` gates the
 *                            two against each other; the store never holds the
 *                            spine as rows, it holds its FTS projection.
 *   delta (1565 nodes)  knowledge/canonical/**.json
 *                         └─ knowledge/ingest.mjs → taxonomy_nodes_ext,
 *                            node_descriptions, taxonomy_metadata,
 *                            concept_relations, knowledge_imports
 *   verbs (16)          knowledge/ontology/relation-types.json + the
 *                       RELATION_TYPE_SEED in db.ts (identical set)
 *                         └─ ingest.mjs + db.seedRelationTypes() → relation_types
 *   typed edges         knowledge/ontology/relations/*.json (currently empty in
 *                       git) → relations, plus the ToE mirror db.syncToeRelations()
 *                       rebuilds from concept_relations on every boot
 *
 * `knowledge_objects` is NOT materialised and is not read by any cortex module —
 * the corpus is C2 scope and has no git source.
 *
 * ── The digest and the delta ────────────────────────────────────────────────
 *
 * `cortexOntologyVersion()` hashes `allNodes()`, which INCLUDES the ext nodes
 * `registerExtNodes()` merges in. So:
 *
 *   materialise: false → 790 nodes  → onto1:76d1f3ad728b382b   (the pinned port-fidelity gate)
 *   materialise: true  → 2355 nodes → a different, larger digest (the operational value)
 *
 * These are not in conflict, but conflating them is the easy mistake. The pinned
 * literal is a statement about the PORT ("this TypeScript computes what the
 * reference computes for the same input"), and it is only reproducible on a
 * store with zero ext rows. The operational digest is a statement about the
 * CORPUS, and it is what has to agree with KEAP's live value at cutover for ASTs
 * to bind. `storeFacts()` reports whichever one this store actually carries.
 */
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { resolveStoreConfig, type CortexStoreConfig } from './cortex-config';
import { applyAnnTuning, type AnnStatus } from './cortex-ann';

type DbModule = typeof import('./db');
type TaxonomyModule = typeof import('./taxonomy');
type OntologyVersionModule = typeof import('./cortex-ontology-version');

export interface StoreMarker {
  organ: 'pazny.cortex';
  /** `db_identity.id` at the moment the organ claimed this directory. */
  dbIdentity: string;
  /** Basename of the libsql file, recorded so the `keap.db` name is never a surprise. */
  dbFile: string;
  createdAt: string;
}

export interface IngestResult {
  applied: string[];
  skipped: string[];
  changed: boolean;
  ontology: { types: number; relations: number; files: string[]; skipped: string[] };
  [k: string]: unknown;
}

export interface MaterialiseReport {
  /** Spine SoT ↔ generated taxonomy.ts agreement (knowledge/spine-render.mjs --check). */
  spineInSync: boolean;
  /** null when materialisation was not requested. */
  ingest: IngestResult | null;
  extNodesRegistered: number;
  descriptionOverrides: number;
  ftsRows: number;
}

export interface StoreFacts {
  dbPath: string;
  dbIdentity: { id: string; initializedAt: number; freshThisBoot: boolean } | null;
  vectorSearchAvailable: boolean;
  ann: AnnStatus;
  /** `allNodes().length` — spine + merged ext nodes. */
  taxonomyNodes: number;
  ftsRows: number;
  verbs: number;
  liveVerbs: number;
  toeRelations: number;
  curatedRelations: number;
  embeddings: number;
  /** `onto1:…` over the tree this store actually carries. */
  ontologyVersion: string;
}

export interface StoreHandle {
  config: CortexStoreConfig;
  db: DbModule;
  taxonomy: TaxonomyModule;
  ontologyVersion: OntologyVersionModule;
  materialise: MaterialiseReport;
  facts: StoreFacts;
}

export interface OpenStoreOptions {
  /**
   * Run the git ingest path before the boot materialisation.
   *
   * Default FALSE — a plain boot must not rewrite the corpus, and the fresh-store
   * digest gate depends on being able to open a store without a delta.
   * `materialiseFromGit()`/the CLI pass true.
   */
  materialise?: boolean;
  /** Re-apply every canonical file regardless of its `knowledge_imports` sha marker. */
  force?: boolean;
  /** Fail the boot if the spine SoT and the generated taxonomy.ts disagree. Default true. */
  requireSpineInSync?: boolean;
  env?: NodeJS.ProcessEnv;
  /** Sink for progress lines. Pass `() => {}` in tests. */
  log?: (line: string) => void;
}

/**
 * Refuse a populated store the organ did not create.
 *
 * "Do not share keap.db, not even read-only, not even transitionally" is a rule
 * that only holds if something enforces it, and the failure mode it guards is
 * quiet: pointing `CORTEX_STORE_PATH` at KEAP's data directory would produce an
 * organ that boots, answers, and is a second writer on someone else's file.
 *
 * The discriminator is the same `populated` predicate `establishDbIdentity()`
 * uses (db.ts:425) plus a marker this module owns:
 *
 *   marker absent, store empty      → the organ's own fresh store; claim it
 *   marker absent, store populated  → REFUSE. Rows we did not put there.
 *   marker present, identity agrees → our store, as expected
 *   marker present, identity differs→ REFUSE. The file underneath was replaced —
 *                                     the exact 2026-07-22 signal `db_identity`
 *                                     was added to catch.
 */
function assertOwnStore(db: DbModule, cfg: CortexStoreConfig, log: (l: string) => void): void {
  const d = db.getDb();
  const identity = db.getDbIdentity();
  const populated =
    (d.prepare('SELECT COUNT(*) c FROM taxonomy_nodes_ext').get() as { c: number }).c > 0 ||
    (d.prepare('SELECT COUNT(*) c FROM knowledge_objects').get() as { c: number }).c > 0;

  let marker: StoreMarker | null = null;
  if (fs.existsSync(cfg.markerPath)) {
    try {
      marker = JSON.parse(fs.readFileSync(cfg.markerPath, 'utf8')) as StoreMarker;
    } catch {
      marker = null; // unreadable — treated as absent, and rewritten below
    }
  }

  if (marker && identity && marker.dbIdentity !== identity.id) {
    throw new Error(
      `Cortex store identity mismatch at ${cfg.dbPath}.\n` +
        `  marker claims db_identity ${marker.dbIdentity}\n` +
        `  the file carries        ${identity.id}\n` +
        'The database under this directory was REPLACED. Everything with a git source\n' +
        'rebuilds; anything without one is gone. Investigate before deleting the marker.',
    );
  }

  if (!marker && populated) {
    throw new Error(
      `Refusing to open ${cfg.dbPath}: it holds curated rows but carries no cortex store marker.\n` +
        'This is what pointing the organ at a FOREIGN store looks like — most likely KEAP\'s own\n' +
        'data directory. The cortex organ mints its own identity and materialises everything from\n' +
        'git (docs/specs/cortex-full-scope-decision.md, "Two corrections"); it is never a second\n' +
        'writer on another service\'s libsql file.\n' +
        `Point CORTEX_STORE_PATH at a directory of the organ's own, or remove ${cfg.dbPath}.`,
    );
  }

  if (!marker && identity) {
    const claim: StoreMarker = {
      organ: 'pazny.cortex',
      dbIdentity: identity.id,
      dbFile: path.basename(cfg.dbPath),
      createdAt: new Date().toISOString(),
    };
    fs.writeFileSync(cfg.markerPath, JSON.stringify(claim, null, 2) + '\n');
    log(`[store] claimed ${cfg.storeDir} (db_identity ${identity.id})`);
  }
}

/** `knowledge/spine-render.mjs --check` — the checked-in `src/game/data/taxonomy.ts`
 *  must be exactly what `knowledge/spine/*.json` renders to. Without this gate
 *  "the spine comes from git" is a claim about a file nobody compared. */
export function checkSpineInSync(cfg: CortexStoreConfig): { ok: boolean; output: string } {
  // No cwd: spine-render.mjs resolves both its source and its target relative to
  // its own module URL, so it is correct from anywhere.
  const res = spawnSync(process.execPath, [cfg.spineRenderScript, '--check'], { encoding: 'utf8' });
  return {
    ok: res.status === 0,
    output: `${res.stdout ?? ''}${res.stderr ?? ''}`.trim(),
  };
}

/**
 * Run `knowledge/ingest.mjs` as a CHILD PROCESS.
 *
 * It is a script, not a module: it parses `process.argv` at load, opens its own
 * `new Database(path.join(KEAP_DATA_DIR, 'keap.db'))` handle and closes it at
 * the end. Importing it would mean faking argv and running a second connection
 * inside this process for the life of the boot. A child gets the argv contract
 * it was written for and releases its handle when it exits — the same way the
 * KEAP Ansible role invokes it.
 *
 * It is run AFTER `initDb()` because it does not create the tables it writes:
 * `taxonomy_nodes_ext`, `node_descriptions` and `taxonomy_metadata` are assumed
 * to exist (its `CREATE TABLE IF NOT EXISTS` guards cover only the marker and
 * relation tables). Against a never-booted file it would die on the first insert.
 */
export function runIngest(
  cfg: CortexStoreConfig,
  opts: { force?: boolean; dryRun?: boolean; log?: (l: string) => void } = {},
): IngestResult {
  const log = opts.log ?? ((l: string) => console.log(l));
  const args = [cfg.ingestScript, '--canonical', cfg.canonicalDir];
  if (opts.force) args.push('--force');
  if (opts.dryRun) args.push('--dry-run');

  const res = spawnSync(process.execPath, args, {
    encoding: 'utf8',
    env: { ...process.env, KEAP_DATA_DIR: cfg.storeDir },
    maxBuffer: 64 * 1024 * 1024,
  });

  const out = `${res.stdout ?? ''}${res.stderr ?? ''}`;
  if (res.status !== 0) {
    throw new Error(`knowledge/ingest.mjs exited ${res.status}:\n${out.slice(-4000)}`);
  }
  const line = out.split('\n').reverse().find((l) => l.startsWith('INGEST_RESULT '));
  if (!line) {
    throw new Error(`knowledge/ingest.mjs produced no INGEST_RESULT trailer:\n${out.slice(-4000)}`);
  }
  const parsed = JSON.parse(line.slice('INGEST_RESULT '.length)) as IngestResult;
  log(
    `[store] ingest: ${parsed.applied.length} applied, ${parsed.skipped.length} skipped, ` +
      `ontology ${parsed.ontology.types} verbs / ${parsed.ontology.relations} relations`,
  );
  return parsed;
}

/**
 * Open (and, on request, materialise) the organ's store.
 *
 * `KEAP_DATA_DIR` is set BEFORE `./db` is imported — db.ts resolves its data
 * directory at MODULE LOAD (db.ts:29), so a static top-level import would bind
 * whatever the environment happened to say when this file was first pulled in.
 * That is the same lesson the vendored `server/cortex-resolve.test.ts:21` records.
 */
export async function openStore(opts: OpenStoreOptions = {}): Promise<StoreHandle> {
  const env = opts.env ?? process.env;
  const log = opts.log ?? ((l: string) => console.log(l));
  const cfg = resolveStoreConfig(env);

  fs.mkdirSync(cfg.storeDir, { recursive: true });
  process.env.KEAP_DATA_DIR = cfg.storeDir;

  const spine = checkSpineInSync(cfg);
  if (!spine.ok && (opts.requireSpineInSync ?? true)) {
    throw new Error(
      `The generated src/game/data/taxonomy.ts disagrees with knowledge/spine/.\n${spine.output}\n` +
        'The spine is the half of the tree with a git source; a store built from a drifted\n' +
        'render is materialised from something no longer in the repository.',
    );
  }

  const db: DbModule = await import('./db');
  await db.initDb();
  assertOwnStore(db, cfg, log);

  // ── git materialisation, ingest half (child process, before we read the tree)
  const ingest = opts.materialise ? runIngest(cfg, { force: opts.force, log }) : null;

  // ── git materialisation, boot half ──────────────────────────────────────────
  // Mirrors KEAP's server/index.ts:41-56 exactly, minus the surfaces that did not
  // move: ensureLayout() (U1 star positions, a UI concern) and the corpus FTS
  // rebuild (knowledge_objects is C2 scope and this store has none).
  const taxonomy: TaxonomyModule = await import('./taxonomy');
  const extRows = db.listExtNodes();
  taxonomy.registerExtNodes(extRows); // fixpoint — order is created_at, not ancestry
  const descRows = db.listNodeDescriptions();
  for (const row of descRows) taxonomy.applyDescriptionOverride(row);
  db.rebuildTaxonomyFts(taxonomy.allNodes());
  db.seedRelationTypes();
  db.syncToeRelations();

  const ftsRows = db.countRows('taxonomy_fts');
  log(
    `[store] materialised: ${taxonomy.allNodes().length} nodes ` +
      `(${extRows.length} ext), ${descRows.length} description overrides, ${ftsRows} fts rows`,
  );

  // ── ANN (build sequence step 6) ─────────────────────────────────────────────
  const ann = applyAnnTuning(db.getDb(), cfg.ann, db.vectorSearchAvailable());
  log(
    ann.outcome === 'unavailable'
      ? '[store] vector layer unavailable — FTS-only, semantic recall disabled'
      : `[store] ann: ${ann.outcome} — ${ann.indexExpr} over ${ann.vectors} vectors` +
          (ann.shadowBytes != null ? ` (${(ann.shadowBytes / 1048576).toFixed(1)} MB shadow)` : ''),
  );

  const ontologyVersion: OntologyVersionModule = await import('./cortex-ontology-version');

  return {
    config: cfg,
    db,
    taxonomy,
    ontologyVersion,
    materialise: {
      spineInSync: spine.ok,
      ingest,
      extNodesRegistered: extRows.length,
      descriptionOverrides: descRows.length,
      ftsRows,
    },
    facts: storeFacts(cfg, db, taxonomy, ontologyVersion, ann),
  };
}

export function storeFacts(
  cfg: CortexStoreConfig,
  db: DbModule,
  taxonomy: TaxonomyModule,
  ontologyVersion: OntologyVersionModule,
  ann: AnnStatus,
): StoreFacts {
  const d = db.getDb();
  const stats = db.ontologyStats();
  const liveVerbs = (
    d
      .prepare("SELECT COUNT(*) c FROM relation_types WHERE status IN ('seed','confirmed')")
      .get() as { c: number }
  ).c;
  let embeddings = 0;
  try {
    embeddings = (d.prepare('SELECT COUNT(*) c FROM embeddings').get() as { c: number }).c;
  } catch {
    embeddings = 0; // no vector layer
  }
  return {
    dbPath: cfg.dbPath,
    dbIdentity: db.getDbIdentity(),
    vectorSearchAvailable: db.vectorSearchAvailable(),
    ann,
    taxonomyNodes: taxonomy.allNodes().length,
    ftsRows: db.countRows('taxonomy_fts'),
    verbs: stats.verbs,
    liveVerbs,
    toeRelations: stats.toeRelations,
    curatedRelations: stats.curatedRelations,
    embeddings,
    ontologyVersion: ontologyVersion.cortexOntologyVersion(),
  };
}
