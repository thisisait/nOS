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
 *   2. It does NOT share, open, read or copy KEAP's `keap.db`. `assertClaimable()`
 *      below makes that mechanical rather than aspirational: a store file the
 *      organ did not create is REFUSED — BEFORE anything opens it read-write —
 *      not adopted. See the two functions' own headers for why the check is
 *      split across `initDb()` rather than sitting on one side of it.
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
import { resolveStoreConfig, NOS_ROOT, type CortexStoreConfig } from './cortex-config';
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

/**
 * The docs-as-knowledge coverage claim, reported as DATA (design §6).
 *
 * This is the field the C1 self-model gap did not have. That gap — 91 `nos.*`
 * nodes missing — survived a fully green P-4 because coverage was LOGGED and
 * never ASSERTED: a router answering `unknown_operand` for a third of the estate
 * looks identical to a router answering correctly. `servicesMissed` names the
 * services that have NO doc tree, so "silence" and "no such capability" are no
 * longer the same value (`hidden_fees/04`). null when docs were not generated.
 */
export interface DocsReport {
  docNodes: number;
  nodesByKind: { skill: number; hint: number; note: number; snippet: number };
  servicesTotal: number;
  servicesCovered: string[];
  /** Manifest services with no `docs/systems/<svc>/` tree — the coverage GAP, by name. */
  servicesMissed: string[];
  domainsMerged: string[];
}

export interface MaterialiseReport {
  /** Spine SoT ↔ generated taxonomy.ts agreement (knowledge/spine-render.mjs --check). */
  spineInSync: boolean;
  /** null when materialisation was not requested. */
  ingest: IngestResult | null;
  extNodesRegistered: number;
  descriptionOverrides: number;
  ftsRows: number;
  /** Slug roots present after materialisation — the COVERAGE claim, reported as
   *  data rather than only logged. The 91-node self-model gap survived a fully
   *  green P-4 because every gate measured composition and none measured
   *  coverage; a fact nobody can read is a fact nobody checks. */
  slugRoots: string[];
  /** Docs-as-knowledge coverage AS REPORTED BY THE GENERATOR — what the child
   *  process BUILT from the files on disk. null when the self-model (and thus
   *  docs) was not run. Never the coverage ASSERTION: see `docNodesInStore`. */
  docs: DocsReport | null;
  /** Doc nodes the STORE actually holds, MEASURED off DB rows (not the generator
   *  stdout). This is what the coverage gate asserts on — a `docs.docNodes` that
   *  only agreed with the file-reading generator would repeat the C1 gap one
   *  level down: a store whose doc rows a non-forced re-ingest skipped would boot
   *  green while every doc query returned nothing. 0 when docs were not run. */
  docNodesInStore: number;
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
 * The organ's claim on a directory. `unreadable` is kept DISTINCT from `absent`:
 * both mean "we cannot show a claim", but only one of them can be explained by
 * "nobody has been here yet", and the refusal message says which.
 */
type MarkerState =
  | { kind: 'absent' }
  | { kind: 'unreadable' }
  | { kind: 'present'; marker: StoreMarker };

function readMarker(cfg: CortexStoreConfig): MarkerState {
  if (!fs.existsSync(cfg.markerPath)) return { kind: 'absent' };
  try {
    return { kind: 'present', marker: JSON.parse(fs.readFileSync(cfg.markerPath, 'utf8')) as StoreMarker };
  } catch {
    return { kind: 'unreadable' };
  }
}

/** Bytes on disk for the store file and its WAL sidecar. `0` means "there is
 *  nothing here", which is the ONLY state the organ may claim. */
function storeBytes(cfg: CortexStoreConfig): number {
  let bytes = 0;
  for (const p of [cfg.dbPath, `${cfg.dbPath}-wal`]) {
    try {
      bytes += fs.statSync(p).size;
    } catch {
      /* not there — contributes nothing */
    }
  }
  return bytes;
}

/**
 * Refuse a store file the organ did not create — BEFORE anything opens it.
 *
 * "Do not share keap.db, not even read-only, not even transitionally" is a rule
 * that only holds if something enforces it, and the failure mode it guards is
 * quiet: pointing `CORTEX_STORE_PATH` at KEAP's data directory would produce an
 * organ that boots, answers, and is a second writer on someone else's file.
 *
 * ── Why this runs before `initDb()`, and why it does no SQL ─────────────────
 *
 * `initDb()` (db.ts:334-377) is not a probe. It opens the file READ-WRITE, sets
 * `journal_mode = WAL`, execs the whole SCHEMA, runs `runMigrations()` (which
 * applies every migration id the target lacks and INSERTs a `schema_migrations`
 * row for each), execs VECTOR_SCHEMA, runs three ALTER TABLE sweeps, and calls
 * `initializeAppMetadata()` + `establishDbIdentity()`. A guard placed after all
 * of that cannot prevent the write it exists to prevent: it can only complain
 * once the foreign file has already been mutated, WAL-mode has been turned on
 * underneath its owner, and — against a KEAP database behind this vendored
 * migration set — unshipped migrations have been applied to a live corpus.
 *
 * So the decision is made here, from the FILESYSTEM alone:
 *
 *   marker present            → our claim; the identity check after `initDb()`
 *                               verifies the file underneath it did not change
 *   marker absent, 0 bytes    → nothing is here; the organ's own fresh store
 *   marker absent, any bytes  → REFUSE. Untouched, unopened, unmigrated.
 *
 * No SQL, deliberately. Counting tables or rows would mean opening a connection
 * on a file we have just decided might not be ours — and a read-only libsql
 * handle on a WAL database still creates the `-shm` sidecar, so even the
 * "harmless" probe writes. Size is the one discriminator that needs no handle,
 * knows nothing about anyone's schema, and therefore cannot be fooled by a
 * database whose content lives in tables this organ has never heard of.
 */
function assertClaimable(cfg: CortexStoreConfig, state: MarkerState): void {
  if (state.kind === 'present') return;
  const bytes = storeBytes(cfg);
  if (bytes === 0) return;

  throw new Error(
    `Refusing to open ${cfg.dbPath}: ${bytes} bytes of database are already there and the organ ` +
      'carries no claim on them.\n' +
      (state.kind === 'unreadable'
        ? `The marker ${cfg.markerPath} exists but could not be parsed, so it proves nothing.\n`
        : `There is no ${path.basename(cfg.markerPath)} in this directory.\n`) +
      'This is what pointing the organ at a FOREIGN store looks like — most likely KEAP\'s own\n' +
      'data directory. The cortex organ mints its own identity and materialises everything from\n' +
      'git (docs/specs/cortex-full-scope-decision.md, "Two corrections"); it is never a second\n' +
      'writer on another service\'s libsql file, so nothing has been opened and nothing has been\n' +
      'written — the file is exactly as it was.\n' +
      `Point CORTEX_STORE_PATH at a directory of the organ's own, or remove ${cfg.dbPath}.`,
  );
}

/**
 * Verify, after `initDb()`, that the database under our marker is still the one
 * we claimed — and record the claim on a store this boot created.
 *
 * This runs AFTER `initDb()` because it needs `db_identity`, which only exists
 * once the schema does. It is NOT the foreign-store guard; `assertClaimable()`
 * above is, and it has already run. What is left here is the half that a
 * filesystem probe cannot answer:
 *
 *   marker present, identity agrees → our store, as expected
 *   marker present, identity differs→ REFUSE. The file underneath was replaced —
 *                                     the exact 2026-07-22 signal `db_identity`
 *                                     was added to catch.
 *   marker absent                   → this boot created the file; claim it
 *
 * The `freshThisBoot` assertion is belt to `assertClaimable()`'s braces, and it
 * is deliberately not load-bearing: `establishDbIdentity()` derives that flag
 * from db.ts's own two-table `populated` predicate (db.ts:424-426), which sees
 * `taxonomy_nodes_ext` and `knowledge_objects` and none of the other ~40 tables.
 * A foreign database whose content sits anywhere else reads as fresh to it. That
 * narrowness is exactly why the real discriminator is bytes-on-disk and not a
 * row count, and why this check can only ever confirm — never establish —
 * ownership.
 */
function assertOwnStore(
  db: DbModule,
  cfg: CortexStoreConfig,
  state: MarkerState,
  log: (l: string) => void,
): void {
  const identity = db.getDbIdentity();

  if (state.kind === 'present' && identity && state.marker.dbIdentity !== identity.id) {
    throw new Error(
      `Cortex store identity mismatch at ${cfg.dbPath}.\n` +
        `  marker claims db_identity ${state.marker.dbIdentity}\n` +
        `  the file carries        ${identity.id}\n` +
        'The database under this directory was REPLACED. Everything with a git source\n' +
        'rebuilds; anything without one is gone. Investigate before deleting the marker.',
    );
  }

  if (state.kind === 'present' || !identity) return;

  if (!identity.freshThisBoot) {
    throw new Error(
      `Refusing to claim ${cfg.dbPath}: it carries db_identity ${identity.id}, which this boot did\n` +
        'not mint, and no cortex store marker. A pre-existing identity written into the organ\'s\n' +
        'own marker is db_identity CARRY-OVER — every `ast.binding` this organ stamps would then\n' +
        'agree with a database it does not own, and the drift check that exists to catch a\n' +
        'replaced store would report agreement (docs/specs/cortex-full-scope-decision.md,\n' +
        '"Two corrections" #1).',
    );
  }

  const claim: StoreMarker = {
    organ: 'pazny.cortex',
    dbIdentity: identity.id,
    dbFile: path.basename(cfg.dbPath),
    createdAt: new Date().toISOString(),
  };
  fs.writeFileSync(cfg.markerPath, JSON.stringify(claim, null, 2) + '\n');
  log(`[store] claimed ${cfg.storeDir} (db_identity ${identity.id})`);
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
/**
 * Generate the estate's self-model and ingest it as a second canonical tree.
 *
 * The generator is `files/anatomy/scripts/keap_selfmodel_gen.py` — the same
 * script `roles/pazny.keap` runs at converge time, invoked with the same
 * `--schema slug` contract. Running it here rather than reading the KEAP
 * container's mounted output keeps ONE source and leaves the organ independent
 * of whether KEAP is deployed at all.
 */
export function runSelfmodel(
  cfg: CortexStoreConfig,
  opts: { force?: boolean; log?: (l: string) => void } = {},
): { generated: boolean; canonicalDir: string; ingest: IngestResult | null; docs: DocsReport } {
  const log = opts.log ?? ((l: string) => console.log(l));
  if (!fs.existsSync(cfg.selfmodelGen)) {
    throw new Error(
      `self-model generator not found at ${cfg.selfmodelGen}. Set CORTEX_SELFMODEL_GEN, ` +
        'or CORTEX_SELFMODEL=0 to build a deliberately spine-only store.',
    );
  }
  fs.rmSync(cfg.selfmodelStageDir, { recursive: true, force: true });
  fs.mkdirSync(cfg.selfmodelStageDir, { recursive: true });

  const gen = spawnSync('python3', [
    cfg.selfmodelGen,
    '--schema', 'slug',
    '--manifest', cfg.selfmodelManifest,
    '--plugins-dir', cfg.selfmodelPluginsDir,
    '--docs-root', cfg.selfmodelDocsRoot,
    '--out', cfg.selfmodelStageDir,
  ], { encoding: 'utf8', maxBuffer: 32 * 1024 * 1024 });
  if (gen.status !== 0) {
    throw new Error(`self-model generator exited ${gen.status}:\n${(gen.stderr || gen.stdout || '').slice(-4000)}`);
  }

  const canonicalDir = path.join(cfg.selfmodelStageDir, 'canonical');
  if (!fs.existsSync(canonicalDir)) {
    throw new Error(
      `self-model generator wrote no canonical/ under ${cfg.selfmodelStageDir}. ` +
        'With --schema slug that directory IS the output; its absence means the run produced nothing.',
    );
  }

  // The DOCS pass merges the estate's prose into the self-model tree that was
  // just written, BEFORE ingest — so it is one canonical tree, one ingest, one
  // `nos` root. It must run after the self-model (its nodes have no parent system
  // otherwise) and before ingest (ingest is where the merged tree becomes rows).
  const docs = runDocs(cfg, canonicalDir, { log });

  const ingest = runIngest({ ...cfg, canonicalDir }, { force: opts.force, log });
  log(`[store] self-model: ${ingest.applied.length} domain(s) applied from the generated tree`);
  return { generated: true, canonicalDir, ingest, docs };
}

/**
 * Merge `docs/systems/` prose into the self-model's canonical tree as typed
 * nodes, and return the coverage claim.
 *
 * The generator (`keap_docs_gen.py`) EXITS NON-ZERO when it produces zero doc
 * nodes — the "corpus exhausted" lie the store must refuse, not log past. So a
 * failed run throws here rather than composing a self-model that silently lost
 * every README. Absence is not emptiness: if the walk found nothing, the boot
 * stops and says so.
 */
export function runDocs(
  cfg: CortexStoreConfig,
  canonicalDir: string,
  opts: { log?: (l: string) => void } = {},
): DocsReport {
  const log = opts.log ?? ((l: string) => console.log(l));
  if (!fs.existsSync(cfg.selfmodelDocsGen)) {
    throw new Error(
      `docs-as-knowledge generator not found at ${cfg.selfmodelDocsGen}. Set CORTEX_DOCS_GEN, ` +
        'or CORTEX_SELFMODEL=0 to build a deliberately spine-only store.',
    );
  }
  const gen = spawnSync('python3', [
    cfg.selfmodelDocsGen,
    '--manifest', cfg.selfmodelManifest,
    '--docs-root', cfg.selfmodelDocsRoot,
    '--canonical', canonicalDir,
    '--repo-root', NOS_ROOT,
  ], { encoding: 'utf8', maxBuffer: 32 * 1024 * 1024 });
  if (gen.status !== 0) {
    throw new Error(
      `docs-as-knowledge generator exited ${gen.status} — a self-model with no doc prose is the ` +
        `coverage lie the store refuses to boot on:\n${(gen.stderr || gen.stdout || '').slice(-4000)}`,
    );
  }
  const line = (gen.stdout || '').split('\n').reverse().find((l) => l.trim().startsWith('{'));
  if (!line) {
    throw new Error(`docs-as-knowledge generator produced no JSON coverage trailer:\n${(gen.stdout || '').slice(-2000)}`);
  }
  const raw = JSON.parse(line) as {
    doc_nodes: number;
    nodes_by_kind: { skill: number; hint: number; note: number; snippet: number };
    services_total: number;
    services_covered: string[];
    services_missed: string[];
    domains_merged: string[];
  };
  const docs: DocsReport = {
    docNodes: raw.doc_nodes,
    nodesByKind: raw.nodes_by_kind,
    servicesTotal: raw.services_total,
    servicesCovered: raw.services_covered,
    servicesMissed: raw.services_missed,
    domainsMerged: raw.domains_merged,
  };
  log(
    `[store] docs: ${docs.docNodes} node(s) ` +
      `(${docs.nodesByKind.skill} skill / ${docs.nodesByKind.hint} hint / ` +
      `${docs.nodesByKind.note} note / ${docs.nodesByKind.snippet} snippet), ` +
      `coverage ${docs.servicesCovered.length}/${docs.servicesTotal} services ` +
      `(${docs.servicesMissed.length} missed)`,
  );
  return docs;
}

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

const DOC_KINDS = new Set(['skill', 'hint', 'note', 'snippet']);

/**
 * Count the doc nodes ACTUALLY IN THE STORE — read off DB rows, never off the
 * generator's stdout.
 *
 * `keap_docs_gen` writes each doc node's typed brief (`{kind, source,
 * provenance}`) to `taxonomy_metadata` as a JSON OBJECT. The self-model's own
 * system/stack/credential nodes carry NO brief, and the git corpus carries a
 * STRING brief under numeric domains — so an object brief with a `provenance`
 * sidecar and a doc `kind`, under a `nos.*` id, is a doc node and nothing else
 * is. That is the measurement the coverage gate must assert against.
 *
 * Why not trust `docs.docNodes`: that number is what the child process BUILT
 * from the files on disk. It diverges from what the store HOLDS the instant a
 * `knowledge_imports` sha still matches while the rows behind it are gone — a
 * `taxonomy_metadata`/`node_descriptions` schema migration, a restored partial
 * backup, an interrupted vacuum. `ingest.mjs` then sees the domain as unchanged
 * and SKIPS it ("unchanged → continue"), never re-inserting; the file-reading
 * generator still reports 394. Asserting on stdout would call that store
 * documented — the exact "silence == no-such-capability" lie this feature kills,
 * reproduced for the prose layer.
 */
function measureDocNodes(db: DbModule): number {
  const rows = db
    .getDb()
    .prepare("SELECT data FROM taxonomy_metadata WHERE id LIKE 'nos.%'")
    .all() as Array<{ data: string }>;
  let n = 0;
  for (const row of rows) {
    let brief: unknown;
    try {
      brief = (JSON.parse(row.data) as { brief?: unknown }).brief;
    } catch {
      continue;
    }
    if (
      brief &&
      typeof brief === 'object' &&
      (brief as { provenance?: unknown }).provenance &&
      DOC_KINDS.has((brief as { kind?: unknown }).kind as string)
    ) {
      n += 1;
    }
  }
  return n;
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

  // FIRST, before the spine gate, before `./db` is even imported: decide whether
  // this directory is ours to write to. Everything below this line opens a
  // read-write handle sooner or later, and a guard that runs after one of them
  // is a guard that reports a write instead of preventing it.
  const marker = readMarker(cfg);
  assertClaimable(cfg, marker);

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
  assertOwnStore(db, cfg, marker, log);

  // ── git materialisation, ingest half (child process, before we read the tree)
  const ingest = opts.materialise ? runIngest(cfg, { force: opts.force, log }) : null;

  // ── the SELF-MODEL half: generated, not git ────────────────────────────────
  // See cortex-config.ts `selfmodelGen` for why this exists. Two ingests compose
  // safely: ingest.mjs's stale-domain sweep prunes a slug root only when THAT
  // root is in the run's own file set, and numeric seed domains are exempt from
  // it entirely — so the self-model pass cannot prune the git pass's domains,
  // and vice versa.
  const selfmodel = opts.materialise && cfg.selfmodelEnabled
    ? runSelfmodel(cfg, { force: opts.force, log })
    : null;

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

  // ── coverage assertion ─────────────────────────────────────────────────────
  // A tree that silently lacks the domain everything references is the "corpus
  // exhausted" class of lie: every query still answers, and every answer is
  // `unknown_operand`. That is how the 91 missing self-model nodes went
  // unnoticed through a full green P-4 — the gates measured composition, not
  // coverage. So the store states what it covers, and refuses to come up
  // pretending otherwise.
  let slugRootIds: string[] = [];
  let docNodesInStore = 0;
  if (opts.materialise && cfg.selfmodelEnabled) {
    const slugRoots = taxonomy
      .allNodes()
      .filter((n) => n.parentId === null && /^[a-z][a-z0-9-]*$/.test(n.id));
    slugRootIds = slugRoots.map((n) => n.id);
    if (!slugRoots.length) {
      throw new Error(
        'materialisation produced NO slug root — the self-model tree is absent. Every `nos.*` operand ' +
          'would resolve to unknown_operand, which reads as a well-formed refusal rather than a missing ' +
          'corpus. Set CORTEX_SELFMODEL=0 only if a spine-only store is what you meant.',
      );
    }
    log(`[store] coverage: slug root(s) ${slugRoots.map((n) => n.id).join(', ')}`);

    // The DOCS coverage assertion — the half the C1 gap lacked. The self-model
    // slug-root check above proves the SHAPE landed; this proves the PROSE did.
    // Zero doc nodes is the same "corpus exhausted" lie one level down: every
    // system node present, every one of them mute.
    //
    // Crucially, this is MEASURED against the store, not read off `docs.docNodes`
    // (the generator's file-derived stdout). Asserting on the stdout would be
    // structurally WEAKER than the sibling slug-root check right above, which
    // queries `taxonomy.allNodes()` — and it would miss the exact failure this
    // feature exists to kill: the generator re-derives 394 from the files while a
    // non-forced re-ingest, seeing an unchanged `knowledge_imports` sha, declined
    // to re-insert doc rows a migration/partial-restore had dropped. The store
    // would boot green logging "documented" with zero doc rows behind it.
    const docs = selfmodel?.docs ?? null;
    docNodesInStore = measureDocNodes(db);
    if (!docs || docNodesInStore === 0) {
      throw new Error(
        'materialisation ENABLED docs but the STORE holds zero doc rows — the self-model system ' +
          'nodes would all resolve mute (no README, no skill, no note), which reads as "no such ' +
          'capability" rather than "docs not generated". This is measured against the store, not the ' +
          `generator's stdout (which built ${docs?.docNodes ?? 'null'}): a null docs report, or a doc ` +
          'corpus a non-forced re-ingest skipped while its rows were absent, both land here. Set ' +
          'CORTEX_SELFMODEL=0 for a deliberately prose-free store, or re-run with --force.',
      );
    }
    if (docs.docNodes !== docNodesInStore) {
      throw new Error(
        `docs coverage desync: keap_docs_gen BUILT ${docs.docNodes} doc node(s) from the files on ` +
          `disk, but the store HOLDS ${docNodesInStore}. A non-forced re-ingest skipped a domain whose ` +
          'knowledge_imports sha still matched while its doc rows were gone (a schema migration, a ' +
          'partial restore, an interrupted vacuum). The coverage claim is asserted against the store, ' +
          'not the generator — re-run with --force to re-materialise the missing rows.',
      );
    }
    log(
      `[store] docs coverage: ${docs.servicesCovered.length}/${docs.servicesTotal} services documented, ` +
        `${docNodesInStore} doc node(s) in store, ${docs.servicesMissed.length} missed` +
        (docs.servicesMissed.length ? ` (${docs.servicesMissed.slice(0, 8).join(', ')}` +
          (docs.servicesMissed.length > 8 ? ', …)' : ')') : ''),
    );
  }

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
      slugRoots: slugRootIds,
      docs: selfmodel?.docs ?? null,
      docNodesInStore,
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
