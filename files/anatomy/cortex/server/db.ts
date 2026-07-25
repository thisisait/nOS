/**
 * SQLite persistence — full port of the old src/services/database.server.ts.
 *
 * Structural changes vs the IIAB-era schema:
 *   1. Every user-scoped table gains `user_id` (default 'local') so per-user
 *      state works behind Authentik header-OIDC. The old schema was implicitly
 *      single-tenant.
 *   2. User-scoped content tables also gain `visibility` ('private' default).
 *      Nothing reads it yet — it exists so the future sharing/social phase
 *      (COMPLETION_PROPOSAL.md, Phase S) needs no schema rework. No code may
 *      assume single-user semantics.
 *   3. `taxonomy_metadata` (the Admin-curated knowledge layer) stays GLOBAL —
 *      it is the shared knowledge base that humans and nOS agents consume;
 *      writes are admin-gated in routes.ts and attributed via `updated_by`.
 *   4. DB path is `KEAP_DATA_DIR` (mounted volume), not process.cwd()/data.
 *   5. The fake sample courses from the old insertSampleData() are gone —
 *      empty state is real state.
 */
import Database from 'libsql';
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { runMigrations } from './migrations';
import { readableVisibilitiesFor } from './rbac';

let db: Database.Database | null = null;
let vectorsOk = false;

const DATA_DIR = process.env.KEAP_DATA_DIR ?? path.resolve(process.cwd(), 'data');
const DB_PATH = path.join(DATA_DIR, 'keap.db');

const SCHEMA = [
  `CREATE TABLE IF NOT EXISTS course_progress (
     user_id TEXT NOT NULL DEFAULT 'local',
     course_id INTEGER NOT NULL,
     progress INTEGER DEFAULT 0,
     completed_chapters INTEGER DEFAULT 0,
     visibility TEXT NOT NULL DEFAULT 'private',
     updated_at INTEGER DEFAULT (strftime('%s','now')),
     PRIMARY KEY (user_id, course_id)
   )`,
  `CREATE TABLE IF NOT EXISTS completed_items (
     user_id TEXT NOT NULL DEFAULT 'local',
     id TEXT NOT NULL,
     visibility TEXT NOT NULL DEFAULT 'private',
     completed_at INTEGER DEFAULT (strftime('%s','now')),
     PRIMARY KEY (user_id, id)
   )`,
  `CREATE TABLE IF NOT EXISTS taxonomy_metadata (
     id TEXT PRIMARY KEY,
     data TEXT NOT NULL,
     updated_by TEXT,
     updated_at INTEGER DEFAULT (strftime('%s','now'))
   )`,
  `CREATE TABLE IF NOT EXISTS api_taxonomy_metadata (
     id TEXT PRIMARY KEY,
     user_id TEXT NOT NULL DEFAULT 'local',
     title TEXT NOT NULL,
     description TEXT,
     url TEXT,
     domain TEXT,
     metadata TEXT,
     source TEXT,
     modality TEXT,
     visibility TEXT NOT NULL DEFAULT 'private',
     created_at INTEGER DEFAULT (strftime('%s','now')),
     updated_at INTEGER DEFAULT (strftime('%s','now'))
   )`,
  `CREATE TABLE IF NOT EXISTS homepage_tiles (
     user_id TEXT NOT NULL DEFAULT 'local',
     id TEXT NOT NULL,
     title TEXT NOT NULL,
     type TEXT NOT NULL,
     position INTEGER NOT NULL,
     visible INTEGER DEFAULT 1,
     config TEXT,
     updated_at INTEGER DEFAULT (strftime('%s','now')),
     PRIMARY KEY (user_id, id)
   )`,
  `CREATE TABLE IF NOT EXISTS recent_activity (
     id INTEGER PRIMARY KEY AUTOINCREMENT,
     user_id TEXT NOT NULL DEFAULT 'local',
     item_id TEXT NOT NULL,
     item_type TEXT NOT NULL,
     timestamp INTEGER DEFAULT (strftime('%s','now'))
   )`,
  `CREATE TABLE IF NOT EXISTS app_metadata (
     id TEXT PRIMARY KEY,
     version TEXT NOT NULL,
     last_updated INTEGER DEFAULT (strftime('%s','now')),
     total_items INTEGER DEFAULT 0,
     completed_items INTEGER DEFAULT 0
   )`,
  `CREATE TABLE IF NOT EXISTS app_settings (
     user_id TEXT NOT NULL DEFAULT 'local',
     key TEXT NOT NULL,
     value TEXT NOT NULL,
     updated_at INTEGER DEFAULT (strftime('%s','now')),
     PRIMARY KEY (user_id, key)
   )`,
  `CREATE TABLE IF NOT EXISTS todos (
     id TEXT PRIMARY KEY,
     user_id TEXT NOT NULL DEFAULT 'local',
     title TEXT NOT NULL,
     completed INTEGER DEFAULT 0,
     visibility TEXT NOT NULL DEFAULT 'private',
     created_at INTEGER DEFAULT (strftime('%s','now')),
     updated_at INTEGER DEFAULT (strftime('%s','now'))
   )`,
  // Baked star positions — pure function of the root index (ROADMAP U1,
  // spatial-memory contract; see server/layout.ts). Rebaked ONLY when
  // layout_version changes.
  `CREATE TABLE IF NOT EXISTS taxonomy_layout (
     node_id TEXT PRIMARY KEY,
     x REAL NOT NULL,
     y REAL NOT NULL,
     z REAL NOT NULL,
     layout_version TEXT NOT NULL
   )`,
  // OKF-aligned index cards (ROADMAP Track S — see server/objects.ts).
  // JSON columns (tags/frontmatter/links) stay opaque here; shape lives in
  // objects.ts. links is derived from body+resource on every write.
  `CREATE TABLE IF NOT EXISTS knowledge_objects (
     id TEXT PRIMARY KEY,
     user_id TEXT NOT NULL DEFAULT 'local',
     type TEXT NOT NULL,
     title TEXT NOT NULL,
     description TEXT,
     resource TEXT,
     tags TEXT,
     frontmatter TEXT,
     body TEXT,
     links TEXT,
     visibility TEXT NOT NULL DEFAULT 'private',
     created_at INTEGER DEFAULT (strftime('%s','now')),
     updated_at INTEGER DEFAULT (strftime('%s','now'))
   )`,
  // Dynamic taxonomy nodes (Track T free/votable zones) — approved
  // extension proposals materialize here and merge into the static tree at
  // startup (server/taxonomy.ts registerExtNode). ordinal pins the U1
  // append placement forever (spatial-memory contract: new stars appear,
  // existing stars never move).
  `CREATE TABLE IF NOT EXISTS taxonomy_nodes_ext (
     id TEXT PRIMARY KEY,
     parent_id TEXT NOT NULL,
     name TEXT NOT NULL,
     description TEXT NOT NULL,
     zone TEXT NOT NULL,
     ordinal INTEGER NOT NULL,
     proposed_by TEXT NOT NULL,
     approved_by TEXT NOT NULL,
     created_at INTEGER DEFAULT (strftime('%s','now'))
   )`,

  // Curated node descriptions (Track K, K1 taxonomy-describe) — the moderated
  // OVERRIDE layer on top of the seed taxonomy's (mostly missing) descriptions.
  // Descriptions are load-bearing (DescGraph): they ARE the node's search/
  // embedding text. LLM skills propose them (promotions kind='desc'); approval
  // upserts here and the in-memory tree, FTS and the embeddings pending diff
  // pick the change up in the same step. en is canonical (embed/FTS text);
  // cs is the UI localization.
  `CREATE TABLE IF NOT EXISTS node_descriptions (
     node_id TEXT PRIMARY KEY,
     description_en TEXT NOT NULL,
     description_cs TEXT,
     proposed_by TEXT NOT NULL,
     approved_by TEXT NOT NULL,
     updated_at INTEGER DEFAULT (strftime('%s','now'))
   )`,

  // Promotion proposals (server/promotions.ts) — the moderated bridge from
  // the review queue into the curated corpus. An agent (librarian) or a user
  // PROPOSES turning a capture into a knowledge object; the MODERATOR has
  // the final word. votes is the MMO seed: local policy = one admin decision,
  // democratic policy = quorum over votes (deferred to the sharing phase,
  // same doctrine as the spatial-memory consensus note).
  `CREATE TABLE IF NOT EXISTS promotions (
     id TEXT PRIMARY KEY,
     kind TEXT NOT NULL DEFAULT 'object',
     capture_id TEXT NOT NULL,
     proposed_by TEXT NOT NULL,
     rationale TEXT,
     object_json TEXT NOT NULL,
     status TEXT NOT NULL DEFAULT 'proposed',
     votes TEXT NOT NULL DEFAULT '[]',
     decided_by TEXT,
     decided_at INTEGER,
     object_id TEXT,
     created_at INTEGER DEFAULT (strftime('%s','now'))
   )`,

  // Knowledge-lint findings (server/lint.ts). One row per (check, refs)
  // finding with a lifecycle: first_seen on discovery, last_seen refreshed
  // every run that still observes it, resolved_at stamped by the run that
  // no longer does. The lint job notifies only on NEW rows, so a standing
  // finding never spams the A9 channel twice.
  `CREATE TABLE IF NOT EXISTS lint_findings (
     id TEXT PRIMARY KEY,
     check_id TEXT NOT NULL,
     severity TEXT NOT NULL,
     ref_kind TEXT,
     ref_id TEXT,
     message TEXT NOT NULL,
     data TEXT,
     first_seen INTEGER DEFAULT (strftime('%s','now')),
     last_seen INTEGER DEFAULT (strftime('%s','now')),
     resolved_at INTEGER
   )`,

  // Concept relations — typed cross-node edges BEYOND the parent-child tree
  // (imported research graphs, e.g. Theory-of-Everything: shared-structure,
  // shared-math, conjecture, limit, conflict, duality, related-concept). The
  // taxonomy tree stays the skeleton (graph.ts links); these are a SEPARATE
  // overlay (data.relations) the explorer renders as vazby behind a toggle.
  // `explored` carries the research rating (well|partially|barely) — the
  // frontier (barely) is what the explorer highlights.
  `CREATE TABLE IF NOT EXISTS concept_relations (
     from_id TEXT NOT NULL,
     to_id TEXT NOT NULL,
     type TEXT NOT NULL,
     explored TEXT,
     source TEXT DEFAULT 'toe',
     PRIMARY KEY (from_id, to_id, type)
   )`,

  // Curator work-log — the recursive-reconciler agent's cursor + progress
  // (docs/plans/keap-curator-agent.md §9). curator_runs is one row per overnight
  // sweep; curator_visits is one row per (node, run) so a kill/OOM resumes from
  // the max cursor and the frontier orders staleness-first (never-visited, then
  // oldest visited_at). content_hash lets a re-run skip an unchanged node inside
  // the cooldown window. Propose-only: the curator never writes taxonomy rows
  // directly — every edit rides the promotions bus.
  `CREATE TABLE IF NOT EXISTS curator_runs (
     run_id TEXT PRIMARY KEY,
     started_at INTEGER DEFAULT (strftime('%s','now')),
     ended_at INTEGER,
     params_json TEXT,
     budget_tokens INTEGER,
     tokens_spent INTEGER,
     nodes_visited INTEGER NOT NULL DEFAULT 0,
     proposals_made INTEGER NOT NULL DEFAULT 0,
     proposals_approved INTEGER NOT NULL DEFAULT 0,
     status TEXT NOT NULL DEFAULT 'running'
   )`,
  `CREATE TABLE IF NOT EXISTS curator_visits (
     node_id TEXT NOT NULL,
     run_id TEXT NOT NULL,
     pass INTEGER NOT NULL DEFAULT 0,
     visited_at INTEGER DEFAULT (strftime('%s','now')),
     content_hash TEXT,
     findings_count INTEGER NOT NULL DEFAULT 0,
     proposals_count INTEGER NOT NULL DEFAULT 0,
     action TEXT,
     PRIMARY KEY (node_id, run_id)
   )`,

  // Knowledge-ingest marker — one row per canonical domain file (knowledge/ =
  // git SoT; knowledge/ingest.mjs). source_sha (sha256 of the file bytes) gates
  // re-apply: an unchanged file is skipped, so the pazny.keap role's ingest is
  // idempotent every run and only restarts the container when something changed.
  // A blank DB has no markers → everything applies. See
  // docs/plans/keap-knowledge-ingest-pipeline.md (in the nOS repo).
  `CREATE TABLE IF NOT EXISTS knowledge_imports (
     import_key TEXT PRIMARY KEY,
     source_sha TEXT NOT NULL,
     n_nodes INTEGER NOT NULL DEFAULT 0,
     n_relations INTEGER NOT NULL DEFAULT 0,
     applied_at TEXT NOT NULL
   )`,

  // Semantic-lens derived features — a handful of scalars per node, projected
  // from its 768-dim embedding onto interpretable difference-vector axes, plus
  // centrality (hub-ness) and a k-means cluster (texture facet). Computed by the
  // host-side keap-features-sync Pulse job (which has Ollama + numpy) and POSTed
  // to /agent/v1/features; GraphCanvas maps these to colour/size/texture behind
  // the "semantic lens" toggle. Positions stay tree-baked — features never move a
  // star. axis_json holds all axis projections {name: score}; the fixed columns
  // are convenience mirrors of the canonical four. See docs/plans/keap-semantic-lens.md.
  `CREATE TABLE IF NOT EXISTS node_features (
     node_id TEXT PRIMARY KEY,
     abstractness REAL,
     scale REAL,
     formalness REAL,
     dynamism REAL,
     centrality REAL,
     cluster INTEGER,
     axis_json TEXT,
     model TEXT,
     updated_at INTEGER DEFAULT (strftime('%s','now'))
   )`,

  // Linked-data enrichment: each concept node's external identity + typing,
  // resolved host-side (tools/keap-linked-data/resolve-typing.py) against
  // Wikidata with disambiguation. Derived + optional per node (many deep leaves
  // have no canonical entity) — a DERIVED layer like node_features, not curated
  // git-SoT. qid = Wikidata QID, keap_type = render facet bucket, schema_type =
  // schema.org-ish class, confidence = high|med. See docs/roadmap.md.
  `CREATE TABLE IF NOT EXISTS node_metadata (
     node_id TEXT PRIMARY KEY,
     qid TEXT,
     keap_type TEXT,
     schema_type TEXT,
     wd_label TEXT,
     confidence TEXT,
     scope_rank INTEGER,
     scope_norm REAL,
     model TEXT,
     updated_at INTEGER DEFAULT (strftime('%s','now'))
   )`,
];

// ── Vector layer (libSQL native) ──────────────────────────────────────────────
// One table for every embeddable object kind; the vector sits NEXT to the row
// reference, so joins + filters + distance run in a single SQL statement (the
// reason libSQL replaced better-sqlite3 here). Dimension is fixed to 768
// (nomic-embed-text); switching to a model with a different dimension requires
// DROP TABLE embeddings + a full re-sync from the host-side embed job.
// content_hash invalidates stale vectors when the source text changes.
const VECTOR_SCHEMA = [
  `CREATE TABLE IF NOT EXISTS embeddings (
     kind TEXT NOT NULL,
     ref_id TEXT NOT NULL,
     model TEXT NOT NULL,
     dim INTEGER NOT NULL,
     content_hash TEXT NOT NULL,
     vector F32_BLOB(768),
     updated_at INTEGER DEFAULT (strftime('%s','now')),
     PRIMARY KEY (kind, ref_id)
   )`,
  `CREATE INDEX IF NOT EXISTS embeddings_vec_idx
     ON embeddings(libsql_vector_idx(vector))`,
];

export async function initDb(): Promise<void> {
  if (db) return;
  fs.mkdirSync(DATA_DIR, { recursive: true });
  db = new Database(DB_PATH);
  db.pragma('journal_mode = WAL');
  for (const stmt of SCHEMA) db.exec(stmt);
  runMigrations(db);
  // Vector tables degrade gracefully: if the runtime lacks the libSQL vector
  // functions (e.g. a stock-SQLite build), semantic features stay off and the
  // FTS/tree surfaces keep working — same pattern as the agent-token 503s.
  try {
    for (const stmt of VECTOR_SCHEMA) db.exec(stmt);
    vectorsOk = true;
  } catch (err) {
    vectorsOk = false;
    console.warn('[db] vector layer unavailable, semantic features disabled:', err);
  }
  // Additive column sweep for pre-intake DBs (Wing /events ALTER precedent):
  // source/modality landed with the unified intake — ALTER is idempotent via
  // the duplicate-column catch.
  for (const col of ['source TEXT', 'modality TEXT']) {
    try {
      db.exec(`ALTER TABLE api_taxonomy_metadata ADD COLUMN ${col}`);
    } catch {
      /* duplicate column — already migrated */
    }
  }
  try {
    db.exec("ALTER TABLE promotions ADD COLUMN kind TEXT NOT NULL DEFAULT 'object'");
  } catch {
    /* duplicate column — already migrated */
  }
  // node_metadata scope-signal columns (QRank popularity) landed after the QID
  // typing layer — idempotent add for DBs created at the type-only stage.
  for (const col of ['scope_rank INTEGER', 'scope_norm REAL']) {
    try {
      db.exec(`ALTER TABLE node_metadata ADD COLUMN ${col}`);
    } catch {
      /* duplicate column — already migrated */
    }
  }
  initializeAppMetadata();
  establishDbIdentity();
}

/** Identity of the database FILE itself — a value that changes if and only if
 *  the database was recreated. */
export type DbIdentity = {
  /** Random per-database id. A changed id means a different database, full stop. */
  id: string;
  /** When this database first came into existence (unix seconds). */
  initializedAt: number;
  /** This process created it — i.e. it booted onto an empty data directory. */
  freshThisBoot: boolean;
};

let dbIdentity: DbIdentity | null = null;

/**
 * Record (or read back) this database's identity.
 *
 * On 2026-07-22 the live data directory was replaced and the DB recreated. The
 * corpus rebuilt itself from its sources — canonical ingest, fs-sync — so from
 * the outside everything looked healthy, and the loss (the entire moderated
 * relation set, which had no source to rebuild from) went unnoticed for two
 * days. Nothing was wrong with the recovery; what was missing was any way to
 * ask "is this the same database it was yesterday?"
 *
 * An id stored INSIDE the database answers that: it cannot survive a recreation,
 * so a changed `id` (or a jumped `initializedAt`) is proof the file was
 * replaced, and a monitor can alert on it.
 *
 * A database that predates this field must not masquerade as fresh — otherwise
 * every existing deployment would cry wolf on its first upgraded boot. The
 * discriminator is content: a DB carrying curated rows is demonstrably not new,
 * so it is adopted with its identity backdated to its own oldest evidence.
 */
function establishDbIdentity(): void {
  const d = getDb();
  const row = d
    .prepare("SELECT value FROM app_settings WHERE user_id = 'system' AND key = 'db_identity'")
    .get() as { value: string } | undefined;
  if (row) {
    try {
      const parsed = JSON.parse(row.value) as { id: string; initializedAt: number };
      dbIdentity = { ...parsed, freshThisBoot: false };
      return;
    } catch {
      /* unreadable — fall through and re-establish */
    }
  }
  const populated =
    (d.prepare('SELECT COUNT(*) c FROM taxonomy_nodes_ext').get() as { c: number }).c > 0 ||
    (d.prepare('SELECT COUNT(*) c FROM knowledge_objects').get() as { c: number }).c > 0;
  const now = Math.floor(Date.now() / 1000);
  // An adopted database is backdated to when it actually came into existence —
  // its own oldest migration. That is the same evidence the 2026-07-22 forensics
  // ran on (six migrations sharing one timestamp is a DB born in that second),
  // and it means `initializedAt` reads as the creation date for every database,
  // not just the ones born after this field existed.
  const born = populated
    ? ((d.prepare('SELECT MIN(applied_at) t FROM schema_migrations').get() as { t: number | null }).t ?? now)
    : now;
  const identity = { id: crypto.randomUUID(), initializedAt: born };
  d.prepare(
    `INSERT INTO app_settings (user_id, key, value, updated_at) VALUES ('system', 'db_identity', ?, ?)
     ON CONFLICT(user_id, key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at`,
  ).run(JSON.stringify(identity), now);
  dbIdentity = { ...identity, freshThisBoot: !populated };
  if (!populated) {
    console.warn(
      `[db] EMPTY DATA DIRECTORY — this process created a new database (id ${identity.id}).\n` +
        '      Expected on a first install. On a system that was already live it means the\n' +
        '      data directory was replaced: everything with a source (canonical ingest,\n' +
        '      fs-sync) will rebuild, everything without one is GONE. Check that the\n' +
        '      ontology layer (knowledge/ontology) has been ingested — the moderated\n' +
        '      relation set has no other source.',
    );
  }
}

/** Identity of the running database — null before initDb(). */
export function getDbIdentity(): DbIdentity | null {
  return dbIdentity;
}

/** Ontology-layer census: the R3 store, split the way its durability matters —
 *  `toe` rows are mirrored from canonical/ at every boot, everything else lives
 *  or dies with knowledge/ontology. */
export function ontologyStats(): {
  verbs: number;
  toeRelations: number;
  curatedRelations: number;
  byStatus: Record<string, number>;
} {
  const d = getDb();
  const verbs = (d.prepare('SELECT COUNT(*) c FROM relation_types').get() as { c: number }).c;
  const rows = d
    .prepare("SELECT source, status, COUNT(*) c FROM relations GROUP BY source, status")
    .all() as Array<{ source: string; status: string; c: number }>;
  const byStatus: Record<string, number> = {};
  let toeRelations = 0;
  let curatedRelations = 0;
  for (const r of rows) {
    if (r.source === 'toe') toeRelations += r.c;
    else {
      curatedRelations += r.c;
      byStatus[r.status] = (byStatus[r.status] ?? 0) + r.c;
    }
  }
  return { verbs, toeRelations, curatedRelations, byStatus };
}

export function getDb(): Database.Database {
  if (!db) throw new Error('DB not initialised — call initDb() first');
  return db;
}

/** True when the libSQL vector layer initialised (embeddings table + ANN index). */
export function vectorSearchAvailable(): boolean {
  return vectorsOk;
}

// ── Courses ───────────────────────────────────────────────────────────────────

export interface UserProgress {
  courseId: number;
  progress: number;
  completedChapters: number;
}

export function getAllCourses(userId: string): UserProgress[] {
  return getDb()
    .prepare(
      'SELECT course_id as courseId, progress, completed_chapters as completedChapters FROM course_progress WHERE user_id = ?',
    )
    .all(userId) as UserProgress[];
}

export function updateCourseProgress(
  userId: string,
  courseId: number,
  progress: number,
  completedChapters: number,
): void {
  getDb()
    .prepare(
      `INSERT INTO course_progress (user_id, course_id, progress, completed_chapters, updated_at)
       VALUES (?, ?, ?, ?, strftime('%s','now'))
       ON CONFLICT(user_id, course_id) DO UPDATE SET
         progress = excluded.progress,
         completed_chapters = excluded.completed_chapters,
         updated_at = excluded.updated_at`,
    )
    .run(userId, courseId, progress, completedChapters);
}

// ── Completed items ───────────────────────────────────────────────────────────

export function getCompletedItems(userId: string): string[] {
  return (
    getDb().prepare('SELECT id FROM completed_items WHERE user_id = ?').all(userId) as Array<{ id: string }>
  ).map((r) => r.id);
}

export function toggleCompletedItem(userId: string, itemId: string): void {
  const d = getDb();
  const row = d.prepare('SELECT 1 FROM completed_items WHERE user_id = ? AND id = ?').get(userId, itemId);
  if (row) {
    d.prepare('DELETE FROM completed_items WHERE user_id = ? AND id = ?').run(userId, itemId);
  } else {
    d.prepare('INSERT INTO completed_items (user_id, id) VALUES (?, ?)').run(userId, itemId);
  }
}

// ── Curated taxonomy metadata (GLOBAL knowledge layer, admin-written) ─────────

/** Curated note payload — arbitrary admin-authored JSON. `requiredData`
 *  (a content ref) is the one key the server itself reads. */
export interface CuratedNoteData {
  requiredData?: string;
  [key: string]: unknown;
}

export interface TaxonomyMetadata {
  id: string;
  data: CuratedNoteData;
  updatedAt: number;
}

/** Raw taxonomy_metadata row — snake_case DB columns before mapping. */
interface CuratedNoteDbRow {
  id: string;
  data: string;
  updated_at: number;
}

export function getTaxonomyMetadata(id?: string): TaxonomyMetadata[] | TaxonomyMetadata | null {
  const d = getDb();
  if (id) {
    const row = d.prepare('SELECT * FROM taxonomy_metadata WHERE id = ?').get(id) as
      | CuratedNoteDbRow
      | undefined;
    if (!row) return null;
    return { id: row.id, data: JSON.parse(row.data), updatedAt: row.updated_at };
  }
  const rows = d.prepare('SELECT * FROM taxonomy_metadata').all() as CuratedNoteDbRow[];
  return rows.map((row) => ({ id: row.id, data: JSON.parse(row.data), updatedAt: row.updated_at }));
}

export function saveTaxonomyMetadata(metadata: { id: string; data: CuratedNoteData }, updatedBy: string): void {
  getDb()
    .prepare(
      `INSERT INTO taxonomy_metadata (id, data, updated_by, updated_at)
       VALUES (?, ?, ?, strftime('%s','now'))
       ON CONFLICT(id) DO UPDATE SET
         data = excluded.data,
         updated_by = excluded.updated_by,
         updated_at = excluded.updated_at`,
    )
    .run(metadata.id, JSON.stringify(metadata.data), updatedBy);
}

export function deleteTaxonomyMetadata(id: string): void {
  getDb().prepare('DELETE FROM taxonomy_metadata WHERE id = ?').run(id);
}

// ── Captured page metadata (owner-scoped; admins see all) ────────────────────

export interface ApiTaxonomyMetadata {
  id: string;
  userId?: string;
  title: string;
  description?: string;
  url?: string;
  domain?: string;
  metadata?: Record<string, unknown> | null;
  /** Intake attribution: which ENTRY POINT class produced this capture. */
  source?: string;
  /** Intake modality: url | text | geo | media | audio-transcript. */
  modality?: string;
  createdAt: number;
  updatedAt: number;
}

/** Raw api_taxonomy_metadata row — nullable text columns are typed as their
 *  mapped shapes (the mapper passes them straight through). */
interface CaptureDbRow {
  id: string;
  user_id: string;
  title: string;
  description?: string;
  url?: string;
  domain?: string;
  metadata: string | null;
  source: string | null;
  modality: string | null;
  created_at: number;
  updated_at: number;
}

function mapCaptureRow(row: CaptureDbRow): ApiTaxonomyMetadata {
  return {
    id: row.id,
    userId: row.user_id,
    title: row.title,
    description: row.description,
    url: row.url,
    domain: row.domain,
    metadata: row.metadata ? JSON.parse(row.metadata) : null,
    source: row.source ?? undefined,
    modality: row.modality ?? undefined,
    createdAt: row.created_at,
    updatedAt: row.updated_at,
  };
}

export function getAllMetadataApi(userId: string, seeAll: boolean): ApiTaxonomyMetadata[] {
  const d = getDb();
  const rows = seeAll
    ? d.prepare('SELECT * FROM api_taxonomy_metadata ORDER BY updated_at DESC').all()
    : d.prepare('SELECT * FROM api_taxonomy_metadata WHERE user_id = ? ORDER BY updated_at DESC').all(userId);
  return (rows as CaptureDbRow[]).map(mapCaptureRow);
}

export function getMetadataApi(id: string): ApiTaxonomyMetadata | null {
  const row = getDb().prepare('SELECT * FROM api_taxonomy_metadata WHERE id = ?').get(id) as
    | CaptureDbRow
    | undefined;
  return row ? mapCaptureRow(row) : null;
}

export function canReadCapture(id: string, userId: string, seeAll: boolean): boolean {
  if (seeAll) return Boolean(getDb().prepare('SELECT 1 FROM api_taxonomy_metadata WHERE id = ?').get(id));
  return Boolean(
    getDb().prepare('SELECT 1 FROM api_taxonomy_metadata WHERE id = ? AND user_id = ?').get(id, userId),
  );
}

export function getMetadataByDomainApi(userId: string, seeAll: boolean, domain: string): ApiTaxonomyMetadata[] {
  const d = getDb();
  const rows = seeAll
    ? d.prepare('SELECT * FROM api_taxonomy_metadata WHERE domain = ? ORDER BY updated_at DESC').all(domain)
    : d
        .prepare('SELECT * FROM api_taxonomy_metadata WHERE user_id = ? AND domain = ? ORDER BY updated_at DESC')
        .all(userId, domain);
  return (rows as CaptureDbRow[]).map(mapCaptureRow);
}

export function saveMetadataApi(
  userId: string,
  metadata: Omit<ApiTaxonomyMetadata, 'createdAt' | 'updatedAt' | 'source' | 'modality'>,
  intake?: { source: string; modality: string },
): void {
  getDb()
    .prepare(
      `INSERT INTO api_taxonomy_metadata (id, user_id, title, description, url, domain, metadata, source, modality, created_at, updated_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, strftime('%s','now'), strftime('%s','now'))
       ON CONFLICT(id) DO UPDATE SET
         title = excluded.title,
         description = excluded.description,
         url = excluded.url,
         domain = excluded.domain,
         metadata = excluded.metadata,
         source = COALESCE(excluded.source, api_taxonomy_metadata.source),
         modality = COALESCE(excluded.modality, api_taxonomy_metadata.modality),
         updated_at = excluded.updated_at`,
    )
    .run(
      metadata.id,
      userId,
      metadata.title,
      metadata.description ?? null,
      metadata.url ?? null,
      metadata.domain ?? null,
      metadata.metadata ? JSON.stringify(metadata.metadata) : null,
      intake?.source ?? null,
      intake?.modality ?? null,
    );
}

// ── Homepage tiles (per-user UI config) ──────────────────────────────────────

export interface HomepageTile {
  id: string;
  title: string;
  type: string;
  position: number;
  visible: boolean;
  config?: unknown;
}

export function getHomepageTiles(userId: string): HomepageTile[] {
  const rows = getDb()
    .prepare('SELECT * FROM homepage_tiles WHERE user_id = ? ORDER BY position')
    .all(userId) as Array<{
    id: string;
    title: string;
    type: string;
    position: number;
    visible: number;
    config: string | null;
  }>;
  return rows.map((row) => ({
    id: row.id,
    title: row.title,
    type: row.type,
    position: row.position,
    visible: Boolean(row.visible),
    config: row.config ? JSON.parse(row.config) : null,
  }));
}

export function saveHomepageTiles(userId: string, tiles: HomepageTile[]): void {
  const d = getDb();
  const replaceAll = d.transaction((rows: HomepageTile[]) => {
    d.prepare('DELETE FROM homepage_tiles WHERE user_id = ?').run(userId);
    const insert = d.prepare(
      'INSERT INTO homepage_tiles (user_id, id, title, type, position, visible, config) VALUES (?, ?, ?, ?, ?, ?, ?)',
    );
    for (const tile of rows) {
      insert.run(
        userId,
        tile.id,
        tile.title,
        tile.type,
        tile.position,
        tile.visible ? 1 : 0,
        tile.config ? JSON.stringify(tile.config) : null,
      );
    }
  });
  replaceAll(tiles);
}

// ── Activity (per-user) ───────────────────────────────────────────────────────

export function trackActivity(userId: string, itemId: string, itemType: string): void {
  getDb()
    .prepare('INSERT INTO recent_activity (user_id, item_id, item_type) VALUES (?, ?, ?)')
    .run(userId, itemId, itemType);
}

export interface RecentActivityRow {
  id: number;
  user_id: string;
  item_id: string;
  item_type: string;
  timestamp: number;
}

export function getRecentActivity(userId: string, type?: string, limit = 10): RecentActivityRow[] {
  const d = getDb();
  if (type) {
    return d
      .prepare('SELECT * FROM recent_activity WHERE user_id = ? AND item_type = ? ORDER BY timestamp DESC LIMIT ?')
      .all(userId, type, limit) as RecentActivityRow[];
  }
  return d
    .prepare('SELECT * FROM recent_activity WHERE user_id = ? ORDER BY timestamp DESC LIMIT ?')
    .all(userId, limit) as RecentActivityRow[];
}

// ── App metadata (global) ─────────────────────────────────────────────────────

export interface AppMetadata {
  id: string;
  version: string;
  lastUpdated: number;
  totalItems: number;
  completedItems: number;
}

function initializeAppMetadata(): void {
  const d = getDb();
  const existing = d.prepare('SELECT COUNT(*) as count FROM app_metadata').get() as { count: number };
  if (existing.count === 0) {
    d.prepare("INSERT INTO app_metadata (id, version, total_items, completed_items) VALUES ('main', '1.0.0', 0, 0)").run();
  }
}

export function getAppMetadata(): AppMetadata | null {
  const row = getDb().prepare("SELECT * FROM app_metadata WHERE id = 'main'").get() as
    | { id: string; version: string; last_updated: number; total_items: number; completed_items: number }
    | undefined;
  if (!row) return null;
  return {
    id: row.id,
    version: row.version,
    lastUpdated: row.last_updated,
    totalItems: row.total_items,
    completedItems: row.completed_items,
  };
}

// ── Settings (per-user) ───────────────────────────────────────────────────────

export function saveSetting(userId: string, key: string, value: string): void {
  getDb()
    .prepare(
      `INSERT INTO app_settings (user_id, key, value, updated_at)
       VALUES (?, ?, ?, strftime('%s','now'))
       ON CONFLICT(user_id, key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at`,
    )
    .run(userId, key, value);
}

export function getSetting(userId: string, key: string): string | null {
  const row = getDb().prepare('SELECT value FROM app_settings WHERE user_id = ? AND key = ?').get(userId, key) as
    | { value: string }
    | undefined;
  return row ? row.value : null;
}

// ── Todos (per-user) ──────────────────────────────────────────────────────────

export interface TodoItem {
  id: string;
  title: string;
  completed: boolean;
  createdAt: number;
  updatedAt: number;
}

export function getTodos(userId: string): TodoItem[] {
  const rows = getDb()
    .prepare('SELECT * FROM todos WHERE user_id = ? ORDER BY created_at DESC')
    .all(userId) as Array<{
    id: string;
    title: string;
    completed: number;
    created_at: number;
    updated_at: number;
  }>;
  return rows.map((row) => ({
    id: row.id,
    title: row.title,
    completed: Boolean(row.completed),
    createdAt: row.created_at,
    updatedAt: row.updated_at,
  }));
}

export function saveTodo(
  userId: string,
  todo: { id: string; title: string; completed?: boolean; createdAt?: number },
): void {
  getDb()
    .prepare(
      `INSERT INTO todos (id, user_id, title, completed, created_at, updated_at)
       VALUES (?, ?, ?, ?, ?, strftime('%s','now'))
       ON CONFLICT(id) DO UPDATE SET
         title = excluded.title,
         completed = excluded.completed,
         updated_at = excluded.updated_at
       WHERE todos.user_id = excluded.user_id`,
    )
    .run(todo.id, userId, todo.title, todo.completed ? 1 : 0, todo.createdAt ?? Math.floor(Date.now() / 1000));
}

export function deleteTodo(userId: string, id: string): void {
  getDb().prepare('DELETE FROM todos WHERE user_id = ? AND id = ?').run(userId, id);
}

// ── Knowledge objects (per-user OKF index cards; admins see all) ─────────────

export interface KnowledgeObject {
  id: string;
  userId?: string;
  type: string;
  title: string;
  description?: string;
  resource?: string;
  tags?: string[];
  frontmatter?: Record<string, unknown>;
  body?: string;
  links?: unknown[];
  visibility?: string;
  createdAt: number;
  updatedAt: number;
}

/** Raw knowledge_objects row — snake_case DB columns before mapping. */
interface ObjectDbRow {
  id: string;
  user_id: string;
  type: string;
  title: string;
  description: string | null;
  resource: string | null;
  tags: string | null;
  frontmatter: string | null;
  body: string | null;
  links: string | null;
  visibility: string;
  created_at: number;
  updated_at: number;
}

function mapObjectRow(row: ObjectDbRow): KnowledgeObject {
  return {
    id: row.id,
    userId: row.user_id,
    type: row.type,
    title: row.title,
    description: row.description ?? undefined,
    resource: row.resource ?? undefined,
    tags: row.tags ? JSON.parse(row.tags) : undefined,
    frontmatter: row.frontmatter ? JSON.parse(row.frontmatter) : undefined,
    body: row.body ?? undefined,
    links: row.links ? JSON.parse(row.links) : undefined,
    visibility: row.visibility,
    createdAt: row.created_at,
    updatedAt: row.updated_at,
  };
}

export function getObjects(userId: string, seeAll: boolean, type?: string): KnowledgeObject[] {
  const d = getDb();
  const where = [seeAll ? null : 'user_id = ?', type ? 'type = ?' : null].filter(Boolean);
  const params = [...(seeAll ? [] : [userId]), ...(type ? [type] : [])];
  const sql = `SELECT * FROM knowledge_objects ${where.length ? `WHERE ${where.join(' AND ')}` : ''} ORDER BY updated_at DESC`;
  return (d.prepare(sql).all(...params) as ObjectDbRow[]).map(mapObjectRow);
}

/** A knowledge_objects row trimmed to exactly what the topic pipeline reads:
 *  the label fields, owner + visibility (for per-viewer label scoping), links
 *  (for θ anchoring) and the body capped at 1 KB. */
export interface TopicObjectRow {
  id: string;
  userId: string;
  visibility: string;
  title: string;
  description?: string;
  tags?: string[];
  links?: unknown[];
  body?: string;
}

/** Every object trimmed for a clustering run (server/topics.ts). Selects only
 *  the columns the pipeline uses and truncates body to 1 KB in SQL — c-TF-IDF
 *  reads only the first 1 000 chars — so a 10k-object run never materializes
 *  every full body in memory (decision #2 memory budget). */
export function getObjectsForTopics(): TopicObjectRow[] {
  return (
    getDb()
      .prepare(
        `SELECT id, user_id, visibility, title, description, tags, links,
                substr(body, 1, 1000) AS body
         FROM knowledge_objects`,
      )
      .all() as Array<{
      id: string;
      user_id: string;
      visibility: string;
      title: string;
      description: string | null;
      tags: string | null;
      links: string | null;
      body: string | null;
    }>
  ).map((r) => ({
    id: r.id,
    userId: r.user_id,
    visibility: r.visibility,
    title: r.title,
    description: r.description ?? undefined,
    tags: r.tags ? (JSON.parse(r.tags) as string[]) : undefined,
    links: r.links ? (JSON.parse(r.links) as unknown[]) : undefined,
    body: r.body ?? undefined,
  }));
}

export function getObject(id: string): KnowledgeObject | null {
  const row = getDb().prepare('SELECT * FROM knowledge_objects WHERE id = ?').get(id) as
    | ObjectDbRow
    | undefined;
  return row ? mapObjectRow(row) : null;
}

// Row-level read gate for a single object. `groups` is REQUIRED (no default) so
// a caller can NEVER silently fall back to a wrong visibility set — the tier
// ladder (server/rbac.ts) is the single source of truth, identical to
// getVisibleObjects below. seeAll (admin) short-circuits to any row.
export function canReadObject(
  id: string,
  userId: string,
  seeAll: boolean,
  groups: string[],
): boolean {
  if (seeAll) return Boolean(getDb().prepare('SELECT 1 FROM knowledge_objects WHERE id = ?').get(id));
  const vis = readableVisibilitiesFor(groups); // always includes 'shared'
  const placeholders = vis.map(() => '?').join(', ');
  return Boolean(
    getDb()
      .prepare(
        `SELECT 1 FROM knowledge_objects WHERE id = ? AND (user_id = ? OR visibility IN (${placeholders}))`,
      )
      .get(id, userId, ...vis),
  );
}

export function saveObject(
  userId: string,
  o: Omit<KnowledgeObject, 'userId' | 'createdAt' | 'updatedAt'>,
): void {
  getDb()
    .prepare(
      `INSERT INTO knowledge_objects (id, user_id, type, title, description, resource, tags, frontmatter, body, links, visibility, created_at, updated_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, strftime('%s','now'), strftime('%s','now'))
       ON CONFLICT(id) DO UPDATE SET
         type = excluded.type,
         title = excluded.title,
         description = excluded.description,
         resource = excluded.resource,
         tags = excluded.tags,
         frontmatter = excluded.frontmatter,
         body = excluded.body,
         links = excluded.links,
         visibility = excluded.visibility,
         updated_at = excluded.updated_at`,
    )
    .run(
      o.id,
      userId,
      o.type,
      o.title,
      o.description ?? null,
      o.resource ?? null,
      o.tags ? JSON.stringify(o.tags) : null,
      o.frontmatter ? JSON.stringify(o.frontmatter) : null,
      o.body ?? null,
      o.links ? JSON.stringify(o.links) : null,
      o.visibility ?? 'private',
    );
}

export function deleteObject(id: string): void {
  getDb().prepare('DELETE FROM knowledge_objects WHERE id = ?').run(id);
}

/** Distinct types in use — the "recent types" suggestions in the object form. */
export function objectTypes(): string[] {
  return (
    getDb().prepare('SELECT DISTINCT type FROM knowledge_objects ORDER BY type').all() as Array<{ type: string }>
  ).map((r) => r.type);
}

// ── Mapped folders (fs_mappings) + owner-scoped object helpers ───────────────
// Admin-managed read-only mirrors of KEAP_FS_ROOTS directories (migration
// 004-fs-mappings). Mirrored objects reuse knowledge_objects unchanged, keyed
// by the synthetic owner 'fsmap:<id>' (precedent: 'agent:<name>') with object
// ids 'fsm:…' — disjoint from the users-pass 'fs:' mirrors by construction.
// The walk/upsert engine lives in server/fs-sync.ts, the admin routes in
// server/fs-mappings.ts.

export interface FsMappingSyncSnapshot {
  scanned?: number;
  upserted?: number;
  removed?: number;
  unchanged?: number;
  capped?: boolean;
  pruneRefused?: boolean;
  rootAvailable?: boolean;
  tookMs?: number;
  error?: string | null;
}

export interface FsMappingRow {
  id: string;
  rootKey: string;
  relPath: string;
  label: string;
  description?: string;
  nestUnderFiles: boolean;
  /** Object-materialization template: type override + static frontmatter. */
  schema: { type?: string; frontmatter?: Record<string, unknown> };
  tags: string[];
  taxonomyRoot?: string;
  taxonomyLinks: string[];
  visibility: string;
  enabled: boolean;
  createdBy: string;
  lastSyncAt?: number;
  /** Parsed last FsMappingSyncResult (fs-sync.ts) — survives restarts. */
  lastSync?: FsMappingSyncSnapshot;
  createdAt: number;
  updatedAt: number;
}

/** Raw fs_mappings row — snake_case DB columns before mapping. */
interface FsMappingDbRow {
  id: string;
  root_key: string;
  rel_path: string;
  label: string;
  description: string | null;
  nest_under_files: number;
  schema_json: string | null;
  tags: string | null;
  taxonomy_root: string | null;
  taxonomy_links: string | null;
  visibility: string;
  enabled: number;
  created_by: string;
  last_sync_at: number | null;
  last_sync_json: string | null;
  created_at: number;
  updated_at: number;
}

function mapFsMappingRow(row: FsMappingDbRow): FsMappingRow {
  return {
    id: row.id,
    rootKey: row.root_key,
    relPath: row.rel_path,
    label: row.label,
    description: row.description ?? undefined,
    nestUnderFiles: Boolean(row.nest_under_files),
    schema: JSON.parse(row.schema_json || '{}'),
    tags: JSON.parse(row.tags || '[]'),
    taxonomyRoot: row.taxonomy_root ?? undefined,
    taxonomyLinks: JSON.parse(row.taxonomy_links || '[]'),
    visibility: row.visibility,
    enabled: Boolean(row.enabled),
    createdBy: row.created_by,
    lastSyncAt: row.last_sync_at ?? undefined,
    lastSync: row.last_sync_json ? JSON.parse(row.last_sync_json) : undefined,
    createdAt: row.created_at,
    updatedAt: row.updated_at,
  };
}

export function listFsMappings(): FsMappingRow[] {
  return (
    getDb().prepare('SELECT * FROM fs_mappings ORDER BY created_at, id').all() as FsMappingDbRow[]
  ).map(mapFsMappingRow);
}

export function getFsMapping(id: string): FsMappingRow | null {
  const row = getDb().prepare('SELECT * FROM fs_mappings WHERE id = ?').get(id) as
    | FsMappingDbRow
    | undefined;
  return row ? mapFsMappingRow(row) : null;
}

/** Insert a new mapping. The caller mints the id ('m-'+8 hex — routes layer). */
export function insertFsMapping(
  m: Omit<FsMappingRow, 'lastSyncAt' | 'lastSync' | 'createdAt' | 'updatedAt'>,
): FsMappingRow {
  getDb()
    .prepare(
      `INSERT INTO fs_mappings (id, root_key, rel_path, label, description, nest_under_files, schema_json, tags, taxonomy_root, taxonomy_links, visibility, enabled, created_by)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
    )
    .run(
      m.id,
      m.rootKey,
      m.relPath,
      m.label,
      m.description ?? null,
      m.nestUnderFiles ? 1 : 0,
      JSON.stringify(m.schema ?? {}),
      JSON.stringify(m.tags ?? []),
      m.taxonomyRoot ?? null,
      JSON.stringify(m.taxonomyLinks ?? []),
      m.visibility,
      m.enabled ? 1 : 0,
      m.createdBy,
    );
  return getFsMapping(m.id)!;
}

/** Everything PATCHable — id/created_by/sync status stay immutable here. */
export type FsMappingPatch = Partial<{
  rootKey: string;
  relPath: string;
  label: string;
  description: string | null;
  nestUnderFiles: boolean;
  schema: FsMappingRow['schema'];
  tags: string[];
  taxonomyRoot: string | null;
  taxonomyLinks: string[];
  visibility: string;
  enabled: boolean;
}>;

export function updateFsMapping(id: string, patch: FsMappingPatch): FsMappingRow | null {
  const sets: string[] = [];
  const params: Array<string | number | null> = [];
  const put = (col: string, val: string | number | null) => {
    sets.push(`${col} = ?`);
    params.push(val);
  };
  if (patch.rootKey !== undefined) put('root_key', patch.rootKey);
  if (patch.relPath !== undefined) put('rel_path', patch.relPath);
  if (patch.label !== undefined) put('label', patch.label);
  if (patch.description !== undefined) put('description', patch.description ?? null);
  if (patch.nestUnderFiles !== undefined) put('nest_under_files', patch.nestUnderFiles ? 1 : 0);
  if (patch.schema !== undefined) put('schema_json', JSON.stringify(patch.schema ?? {}));
  if (patch.tags !== undefined) put('tags', JSON.stringify(patch.tags ?? []));
  if (patch.taxonomyRoot !== undefined) put('taxonomy_root', patch.taxonomyRoot ?? null);
  if (patch.taxonomyLinks !== undefined) put('taxonomy_links', JSON.stringify(patch.taxonomyLinks ?? []));
  if (patch.visibility !== undefined) put('visibility', patch.visibility);
  if (patch.enabled !== undefined) put('enabled', patch.enabled ? 1 : 0);
  if (sets.length) {
    getDb()
      .prepare(`UPDATE fs_mappings SET ${sets.join(', ')}, updated_at = strftime('%s','now') WHERE id = ?`)
      .run(...params, id);
  }
  return getFsMapping(id);
}

export function deleteFsMapping(id: string): boolean {
  return getDb().prepare('DELETE FROM fs_mappings WHERE id = ?').run(id).changes > 0;
}

/** Persist one sync pass's outcome. Deliberately does NOT bump updated_at —
 *  that column tracks config edits, not the every-pass status heartbeat. */
export function setFsMappingSyncStatus(id: string, at: number, resultJson: string): void {
  getDb()
    .prepare('UPDATE fs_mappings SET last_sync_at = ?, last_sync_json = ? WHERE id = ?')
    .run(at, resultJson, id);
}

export function countObjectsByOwner(userId: string): number {
  return (
    getDb().prepare('SELECT COUNT(*) AS c FROM knowledge_objects WHERE user_id = ?').get(userId) as {
      c: number;
    }
  ).c;
}

/** Purge one owner's objects (mapping delete) — one DELETE statement, atomic
 *  on its own and safe inside a caller's transaction (the libsql driver can't
 *  nest BEGINs, so this must NOT open one; the mapping-delete route wraps
 *  this + the row delete in ONE enclosing transaction). The orphaned vectors
 *  are reaped by the next pruneEmbeddings pass. */
export function deleteObjectsByOwner(userId: string): number {
  return getDb().prepare('DELETE FROM knowledge_objects WHERE user_id = ?').run(userId).changes;
}

/** Flip visibility on every object of one owner — the ACL half of a mapping
 *  visibility PATCH. Must work WITHOUT a sync pass: a disabled mapping or an
 *  unmounted root can't resync, and leaving previously-shared mirrors in
 *  every user's graph until one succeeds would silently ignore the admin's
 *  intent. frontmatter.cfg stays stale on purpose — the next successful
 *  sync's cfg-hash mismatch rewrites the rows fully (idempotent after).
 *  Visibility is not part of objectText, so no corpus-dirty mark is needed. */
export function setObjectVisibilityByOwner(userId: string, visibility: string): number {
  return getDb()
    .prepare('UPDATE knowledge_objects SET visibility = ? WHERE user_id = ?')
    .run(visibility, userId).changes;
}

export interface ObjectSyncIndexEntry {
  id: string;
  links: unknown[];
  frontmatter?: Record<string, unknown>;
}

/** id → {links, frontmatter} for one owner — the sync engine's skip/prune
 *  index. Deliberately NOT getObjects: no bodies (a full pass would otherwise
 *  haul up to 20k × 4000-char bodies through JSON.parse for nothing). */
export function getObjectSyncIndex(userId: string): Map<string, ObjectSyncIndexEntry> {
  const rows = getDb()
    .prepare('SELECT id, links, frontmatter FROM knowledge_objects WHERE user_id = ?')
    .all(userId) as Array<{ id: string; links: string | null; frontmatter: string | null }>;
  return new Map(
    rows.map((r) => [
      r.id,
      {
        id: r.id,
        links: r.links ? JSON.parse(r.links) : [],
        frontmatter: r.frontmatter ? JSON.parse(r.frontmatter) : undefined,
      },
    ]),
  );
}

/** Graph-scope visibility: own objects + ANYTHING shared — mapping mirrors
 *  and manually shared cards alike (deliberate: 'shared' has always meant
 *  world-readable via direct GET; the graph lists what was already readable).
 *  Used ONLY by /api/graph — /api/objects lists stay owner-scoped (admins see
 *  all), so a 5k-file shared mapping never floods every user's Objects page. */
// `groups` is REQUIRED (no default): the S2⁶ visibility-ladder fix (spec §4)
// replaces the flat `visibility='shared'` filter with the rbac tier ladder, so
// a tier-scoped object (e.g. a 'tier-users' table card) reaches the callers
// rbac.ts entitles — not admins only. 'shared' stays rank-99, so the set is a
// STRICT SUPERSET of today's; 'private' (rank 0) is never granted by a tier.
export function getVisibleObjects(
  userId: string,
  seeAll: boolean,
  groups: string[],
): KnowledgeObject[] {
  const d = getDb();
  if (seeAll) {
    return (
      d.prepare('SELECT * FROM knowledge_objects ORDER BY updated_at DESC').all() as ObjectDbRow[]
    ).map((r) => mapObjectRow(r));
  }
  const vis = readableVisibilitiesFor(groups); // always includes 'shared'
  const placeholders = vis.map(() => '?').join(', ');
  const rows = d
    .prepare(
      `SELECT * FROM knowledge_objects WHERE user_id = ? OR visibility IN (${placeholders}) ORDER BY updated_at DESC`,
    )
    .all(userId, ...vis);
  return (rows as ObjectDbRow[]).map((r) => mapObjectRow(r));
}

// ── Baked layout (U1 — deterministic star positions) ─────────────────────────

export function getLayoutVersion(): string | null {
  const row = getDb().prepare('SELECT layout_version FROM taxonomy_layout LIMIT 1').get() as
    | { layout_version: string }
    | undefined;
  return row?.layout_version ?? null;
}

export function getLayout(): Map<string, { x: number; y: number; z: number }> {
  const rows = getDb().prepare('SELECT node_id, x, y, z FROM taxonomy_layout').all() as Array<{
    node_id: string;
    x: number;
    y: number;
    z: number;
  }>;
  return new Map(rows.map((r) => [r.node_id, { x: r.x, y: r.y, z: r.z }]));
}

export function saveLayout(
  points: Array<{ nodeId: string; x: number; y: number; z: number }>,
  version: string,
): void {
  const d = getDb();
  const tx = d.transaction(() => {
    d.prepare('DELETE FROM taxonomy_layout').run();
    const ins = d.prepare(
      'INSERT INTO taxonomy_layout (node_id, x, y, z, layout_version) VALUES (?, ?, ?, ?, ?)',
    );
    for (const p of points) ins.run(p.nodeId, p.x, p.y, p.z, version);
  });
  tx();
}

// ── Taxonomy full-text index (agent surface) ─────────────────────────────────
// FTS5 over the static taxonomy tree. Rebuilt on every startup — the dataset
// is a compiled-in constant, so the index is derived state, never a source.

export interface FtsHit {
  id: string;
  rank: number;
}

export function rebuildTaxonomyFts(
  nodes: Array<{ id: string; name: string; description?: string; path: string }>,
): void {
  const d = getDb();
  d.exec(
    `CREATE VIRTUAL TABLE IF NOT EXISTS taxonomy_fts USING fts5(id UNINDEXED, name, description, path)`,
  );
  const rebuild = d.transaction(() => {
    d.prepare('DELETE FROM taxonomy_fts').run();
    const insert = d.prepare('INSERT INTO taxonomy_fts (id, name, description, path) VALUES (?, ?, ?, ?)');
    for (const n of nodes) insert.run(n.id, n.name, n.description ?? '', n.path);
  });
  rebuild();
}

export function searchTaxonomyFts(query: string, limit: number): FtsHit[] {
  const match = ftsQuery(query);
  if (!match) return [];
  try {
    return getDb()
      .prepare('SELECT id, rank FROM taxonomy_fts WHERE taxonomy_fts MATCH ? ORDER BY rank LIMIT ?')
      .all(match, limit) as FtsHit[];
  } catch {
    return [];
  }
}

/** Quote each token so user input can't inject FTS5 syntax (NEAR, *, etc.). */
function ftsQuery(query: string): string {
  return query
    .split(/\s+/)
    .filter(Boolean)
    .map((t) => `"${t.replace(/"/g, '')}"`)
    .join(' ');
}

// ── Corpus full-text index (S4 — lexical leg of RRF hybrid search) ───────────
// One FTS5 table over EVERY searchable item (taxonomy nodes, captures,
// curated notes, knowledge objects). Rebuilt from the same canonical texts
// the embedding pipeline uses, so the lexical and vector legs of the hybrid
// search always describe the same corpus.

export function rebuildCorpusFts(
  rows: Array<{ kind: EmbeddingKind; refId: string; text: string }>,
): void {
  const d = getDb();
  d.exec(
    `CREATE VIRTUAL TABLE IF NOT EXISTS corpus_fts USING fts5(kind UNINDEXED, ref_id UNINDEXED, text)`,
  );
  const rebuild = d.transaction(() => {
    d.prepare('DELETE FROM corpus_fts').run();
    const insert = d.prepare('INSERT INTO corpus_fts (kind, ref_id, text) VALUES (?, ?, ?)');
    for (const r of rows) insert.run(r.kind, r.refId, r.text);
  });
  rebuild();
}

export interface CorpusFtsHit {
  kind: EmbeddingKind;
  refId: string;
  rank: number;
}

export function searchCorpusFts(query: string, kinds: EmbeddingKind[], limit: number): CorpusFtsHit[] {
  const match = ftsQuery(query);
  if (!match) return [];
  const kindFilter = kinds.length ? `AND kind IN (${kinds.map(() => '?').join(',')})` : '';
  try {
    return getDb()
      .prepare(
        `SELECT kind, ref_id AS refId, rank FROM corpus_fts
         WHERE corpus_fts MATCH ? ${kindFilter} ORDER BY rank LIMIT ?`,
      )
      .all(match, ...kinds, limit) as CorpusFtsHit[];
  } catch {
    return [];
  }
}

// ── Corpus stats (agent health endpoint) ─────────────────────────────────────

export function corpusStats(): { captures: number; curatedNotes: number; objects: number } {
  const d = getDb();
  const captures = (d.prepare('SELECT COUNT(*) AS c FROM api_taxonomy_metadata').get() as { c: number }).c;
  const curatedNotes = (d.prepare('SELECT COUNT(*) AS c FROM taxonomy_metadata').get() as { c: number }).c;
  const objects = (d.prepare('SELECT COUNT(*) AS c FROM knowledge_objects').get() as { c: number }).c;
  return { captures, curatedNotes, objects };
}

// ── Embeddings (libSQL vector layer) ──────────────────────────────────────────
// Vectors are written by the host-side sync job (nOS Pulse: Ollama on the host
// loopback → POST /agent/v1/embeddings) — the container never needs to reach
// an embedder for node-anchored distance queries.

export type EmbeddingKind = 'taxonomy' | 'capture' | 'note' | 'object';

export interface NeighborHit {
  kind: EmbeddingKind;
  refId: string;
  distance: number;
}

export function embeddingStats(): { total: number; byKind: Record<string, number>; model: string | null } {
  if (!vectorsOk) return { total: 0, byKind: {}, model: null };
  const d = getDb();
  const rows = d.prepare('SELECT kind, COUNT(*) AS c FROM embeddings GROUP BY kind').all() as Array<{
    kind: string;
    c: number;
  }>;
  const byKind: Record<string, number> = {};
  let total = 0;
  for (const r of rows) {
    byKind[r.kind] = r.c;
    total += r.c;
  }
  const m = d.prepare('SELECT model FROM embeddings LIMIT 1').get() as { model: string } | undefined;
  return { total, byKind, model: m?.model ?? null };
}

/** ref_id → content_hash for one kind — drives the pending/stale diff. */
export function getEmbeddingHashes(kind: EmbeddingKind): Map<string, string> {
  if (!vectorsOk) return new Map();
  const rows = getDb().prepare('SELECT ref_id, content_hash FROM embeddings WHERE kind = ?').all(kind) as Array<{
    ref_id: string;
    content_hash: string;
  }>;
  return new Map(rows.map((r) => [r.ref_id, r.content_hash]));
}

// ── Semantic-lens derived features ────────────────────────────────────────────
/** All taxonomy embeddings as {id, vector} — the host-side keap-features-sync job
 *  reads these (GET /agent/v1/features/vectors), projects them onto its axis
 *  vectors, and POSTs the scalars back. vector_extract unpacks the F32_BLOB. */
export function readTaxonomyVectors(): { id: string; vector: number[] }[] {
  if (!vectorsOk) return [];
  const rows = getDb()
    .prepare("SELECT ref_id, vector_extract(vector) AS v FROM embeddings WHERE kind = 'taxonomy'")
    .all() as Array<{ ref_id: string; v: string }>;
  return rows.map((r) => ({ id: r.ref_id, vector: JSON.parse(r.v) }));
}

export interface NodeFeatureRow {
  node_id: string;
  abstractness?: number; scale?: number; formalness?: number; dynamism?: number;
  centrality?: number; cluster?: number; axis_json?: string;
}

/** Upsert the derived features computed host-side (keap-features-sync). */
export function upsertNodeFeatures(rows: NodeFeatureRow[], model: string): number {
  const d = getDb();
  const stmt = d.prepare(
    `INSERT INTO node_features (node_id, abstractness, scale, formalness, dynamism, centrality, cluster, axis_json, model, updated_at)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, strftime('%s','now'))
     ON CONFLICT(node_id) DO UPDATE SET abstractness=excluded.abstractness, scale=excluded.scale,
       formalness=excluded.formalness, dynamism=excluded.dynamism, centrality=excluded.centrality,
       cluster=excluded.cluster, axis_json=excluded.axis_json, model=excluded.model, updated_at=excluded.updated_at`);
  const txn = d.transaction((rs: NodeFeatureRow[]) => {
    for (const r of rs) stmt.run(r.node_id, r.abstractness ?? null, r.scale ?? null, r.formalness ?? null,
      r.dynamism ?? null, r.centrality ?? null, r.cluster ?? null, r.axis_json ?? null, model);
  });
  txn(rows);
  return rows.length;
}

/** node_id → derived-feature scalars, for the graph payload's semantic lens. */
export function getNodeFeatures(): Map<string, Record<string, number>> {
  try {
    // Columns are nullable in the schema; the payload passes the values through
    // untouched, so the row is typed to the declared map contract.
    const rows = getDb().prepare('SELECT * FROM node_features').all() as Array<{
      node_id: string;
      abstractness: number;
      scale: number;
      formalness: number;
      dynamism: number;
      centrality: number;
      cluster: number;
    }>;
    return new Map(rows.map((r) => [r.node_id, {
      abstractness: r.abstractness, scale: r.scale, formalness: r.formalness,
      dynamism: r.dynamism, centrality: r.centrality, cluster: r.cluster }]));
  } catch { return new Map(); }
}

export interface NodeMetadataRow {
  node_id: string;
  qid?: string | null; keap_type?: string | null; schema_type?: string | null;
  wd_label?: string | null; confidence?: string | null;
  scope_rank?: number | null; scope_norm?: number | null;
}

/** Upsert linked-data metadata resolved host-side (resolve-typing.py). When
 *  replace=true the derived layer is reconciled to the posted set — rows no
 *  longer resolved (e.g. a node newly P31-rejected) are pruned, so the layer
 *  always reflects the last full resolve. Prune deletes per-id (no bound-param
 *  limit) to stay safe as the usable set grows. */
export function upsertNodeMetadata(rows: NodeMetadataRow[], model: string, replace = false): { upserted: number; pruned: number } {
  const d = getDb();
  const stmt = d.prepare(
    `INSERT INTO node_metadata (node_id, qid, keap_type, schema_type, wd_label, confidence, scope_rank, scope_norm, model, updated_at)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, strftime('%s','now'))
     ON CONFLICT(node_id) DO UPDATE SET qid=excluded.qid, keap_type=excluded.keap_type,
       schema_type=excluded.schema_type, wd_label=excluded.wd_label,
       confidence=excluded.confidence, scope_rank=excluded.scope_rank,
       scope_norm=excluded.scope_norm, model=excluded.model, updated_at=excluded.updated_at`);
  const del = d.prepare('DELETE FROM node_metadata WHERE node_id = ?');
  let pruned = 0;
  const txn = d.transaction((rs: NodeMetadataRow[]) => {
    for (const r of rs) stmt.run(r.node_id, r.qid ?? null, r.keap_type ?? null,
      r.schema_type ?? null, r.wd_label ?? null, r.confidence ?? null,
      r.scope_rank ?? null, r.scope_norm ?? null, model);
    if (replace) {
      const keep = new Set(rs.map((r) => r.node_id));
      for (const { node_id } of d.prepare('SELECT node_id FROM node_metadata').all() as { node_id: string }[]) {
        if (!keep.has(node_id)) { del.run(node_id); pruned++; }
      }
    }
  });
  txn(rows);
  return { upserted: rows.length, pruned };
}

/** node_id → external identity + typing + scope, for the graph payload. */
export function getNodeMetadata(): Map<string, Record<string, string | number>> {
  try {
    // Same passthrough contract as getNodeFeatures — nullable columns ride
    // through to the payload untouched.
    const rows = getDb().prepare('SELECT * FROM node_metadata').all() as Array<{
      node_id: string;
      qid: string;
      keap_type: string;
      schema_type: string;
      wd_label: string;
      confidence: string;
      scope_rank: number;
      scope_norm: number;
    }>;
    return new Map(rows.map((r) => [r.node_id, {
      qid: r.qid, keapType: r.keap_type, schemaType: r.schema_type,
      wdLabel: r.wd_label, confidence: r.confidence,
      scopeRank: r.scope_rank, scopeNorm: r.scope_norm }]));
  } catch { return new Map(); }
}

export function upsertEmbeddings(
  model: string,
  dim: number,
  items: Array<{ kind: EmbeddingKind; refId: string; contentHash: string; vector: number[] }>,
): number {
  if (!vectorsOk) throw new Error('vector layer unavailable');
  const d = getDb();
  const insert = d.prepare(
    `INSERT INTO embeddings (kind, ref_id, model, dim, content_hash, vector, updated_at)
     VALUES (?, ?, ?, ?, ?, vector32(?), strftime('%s','now'))
     ON CONFLICT(kind, ref_id) DO UPDATE SET
       model = excluded.model,
       dim = excluded.dim,
       content_hash = excluded.content_hash,
       vector = excluded.vector,
       updated_at = excluded.updated_at`,
  );
  const tx = d.transaction((rows: typeof items) => {
    for (const it of rows) {
      insert.run(it.kind, it.refId, model, dim, it.contentHash, JSON.stringify(it.vector));
    }
  });
  tx(items);
  return items.length;
}

/** Drop vectors whose source row no longer exists (deleted capture/note). */
export function pruneEmbeddings(kind: EmbeddingKind, liveIds: Set<string>): number {
  if (!vectorsOk) return 0;
  const d = getDb();
  const stored = d.prepare('SELECT ref_id FROM embeddings WHERE kind = ?').all(kind) as Array<{ ref_id: string }>;
  const del = d.prepare('DELETE FROM embeddings WHERE kind = ? AND ref_id = ?');
  let pruned = 0;
  const tx = d.transaction(() => {
    for (const r of stored) {
      if (!liveIds.has(r.ref_id)) {
        del.run(kind, r.ref_id);
        pruned++;
      }
    }
  });
  tx();
  return pruned;
}

/**
 * k nearest (mode=related) or farthest (mode=unrelated) stored vectors from an
 * anchor row. Nearest uses the DiskANN index (vector_top_k); farthest is a
 * full scan — DiskANN has no "farthest" query, and at ~1k rows a scan is free.
 */
export function vectorNeighbors(
  anchorKind: EmbeddingKind,
  anchorRefId: string,
  mode: 'related' | 'unrelated',
  kinds: EmbeddingKind[],
  limit: number,
): NeighborHit[] | null {
  if (!vectorsOk) return null;
  const d = getDb();
  const anchor = d
    .prepare('SELECT vector_extract(vector) AS v FROM embeddings WHERE kind = ? AND ref_id = ?')
    .get(anchorKind, anchorRefId) as { v: string | null } | undefined;
  if (!anchor?.v) return null;
  return vectorNeighborsOf(anchor.v, mode, kinds, limit, { kind: anchorKind, refId: anchorRefId });
}

/** Same as vectorNeighbors but anchored on a raw query vector (live embed). */
export function vectorNeighborsOf(
  vectorJson: string,
  mode: 'related' | 'unrelated',
  kinds: EmbeddingKind[],
  limit: number,
  exclude?: { kind: string; refId: string },
): NeighborHit[] {
  if (!vectorsOk) return [];
  const d = getDb();
  const kindFilter = kinds.length ? `AND e.kind IN (${kinds.map(() => '?').join(',')})` : '';
  if (mode === 'related') {
    // Over-fetch from the ANN index, then kind-filter + self-exclude in SQL.
    const rows = d
      .prepare(
        `SELECT e.kind, e.ref_id AS refId,
                vector_distance_cos(e.vector, vector32(?)) AS distance
         FROM vector_top_k('embeddings_vec_idx', vector32(?), ?) AS v
         JOIN embeddings e ON e.rowid = v.id
         WHERE 1=1 ${kindFilter}
         ORDER BY distance ASC`,
      )
      .all(vectorJson, vectorJson, Math.min(limit * 4 + 1, 256), ...kinds) as NeighborHit[];
    return rows
      .filter((r) => !(exclude && r.kind === exclude.kind && r.refId === exclude.refId))
      .slice(0, limit);
  }
  const rows = d
    .prepare(
      `SELECT e.kind, e.ref_id AS refId,
              vector_distance_cos(e.vector, vector32(?)) AS distance
       FROM embeddings e
       WHERE 1=1 ${kindFilter}
       ORDER BY distance DESC
       LIMIT ?`,
    )
    .all(vectorJson, ...kinds, limit + 1) as NeighborHit[];
  return rows
    .filter((r) => !(exclude && r.kind === exclude.kind && r.refId === exclude.refId))
    .slice(0, limit);
}

// ── Topic clusters (server/topics.ts) ─────────────────────────────────────────
// Server-side spherical k-means over kind='object' vectors with sticky
// identities. Migration 005 tables are plain SQL (not part of VECTOR_SCHEMA),
// so persisted topics/assignments read + render even when vectorsOk=false —
// only the clustering pass itself needs the vector layer. See topic-mode-spec.

/** Dominant object-vector model (decision #5): most rows win, ties break
 *  lexicographically. Object-kind-scoped — never the arbitrary LIMIT 1 row of
 *  embeddingStats(). null when no object vectors.
 *
 *  NB: the MAX(updated_at) tie-break was REMOVED (topic-mode slot-stability
 *  hardening). It handed dominance to whichever model was touched last, so at
 *  count-parity — the norm when a parallel nOS sidekick embeds under a second
 *  model — the dominant model flipped on essentially every embed POST, and each
 *  flip triggered a wholesale topic reset (un-caused slot loss). Count + a
 *  stable lexicographic tie leaves the choice unchanged near parity; the reset
 *  decision itself is additionally margin-gated in server/topics.ts. */
export function dominantObjectModel(): string | null {
  if (!vectorsOk) return null;
  const row = getDb()
    .prepare(
      `SELECT model FROM embeddings WHERE kind = 'object'
       GROUP BY model ORDER BY COUNT(*) DESC, model ASC LIMIT 1`,
    )
    .get() as { model: string } | undefined;
  return row?.model ?? null;
}

/** Object-vector row count per model. The topic-mode model-hysteresis guard
 *  (server/topics.ts) needs both the incumbent's and the candidate's counts to
 *  decide whether a dominant-model flip has a sustained margin worth a reset. */
export function objectVectorModelCounts(): Map<string, number> {
  if (!vectorsOk) return new Map();
  const rows = getDb()
    .prepare("SELECT model, COUNT(*) AS c FROM embeddings WHERE kind = 'object' GROUP BY model")
    .all() as Array<{ model: string; c: number }>;
  return new Map(rows.map((r) => [r.model, r.c]));
}

/** Object vectors of one model as raw JSON strings — NOT parsed in the SQL
 *  layer (decision #2: the caller tile-parses directly into a Float32Array,
 *  never a transient number[][]). */
export function readObjectVectorsRaw(model: string): { id: string; v: string }[] {
  if (!vectorsOk) return [];
  return getDb()
    .prepare("SELECT ref_id AS id, vector_extract(vector) AS v FROM embeddings WHERE kind = 'object' AND model = ?")
    .all(model) as Array<{ id: string; v: string }>;
}

/** Count + latest updated_at of object vectors for one model — the stale check
 *  (topicsStale) compares these against the last run's n + ran_at. */
export function objectVectorStats(model: string): { count: number; maxUpdated: number } {
  if (!vectorsOk) return { count: 0, maxUpdated: 0 };
  const row = getDb()
    .prepare(
      "SELECT COUNT(*) AS c, COALESCE(MAX(updated_at), 0) AS u FROM embeddings WHERE kind = 'object' AND model = ?",
    )
    .get(model) as { c: number; u: number };
  return { count: row.c, maxUpdated: row.u };
}

export interface TopicClusterRow {
  id: string;
  label: string;
  labelAuto: string;
  labelLocked: boolean;
  terms: string[];
  churnAccum: number;
  centroid: number[];
  theta: number;
  memberCount: number;
  emptyRuns: number;
  model: string;
  updatedAt: number;
}

interface TopicClusterDbRow {
  id: string;
  label: string;
  label_auto: string;
  label_locked: number;
  terms_json: string;
  churn_accum: number;
  centroid_json: string;
  theta: number;
  model: string;
  member_count: number;
  empty_runs: number;
  updated_at: number;
}

function mapTopicClusterRow(r: TopicClusterDbRow): TopicClusterRow {
  return {
    id: r.id,
    label: r.label,
    labelAuto: r.label_auto,
    labelLocked: r.label_locked === 1,
    terms: r.terms_json ? (JSON.parse(r.terms_json) as string[]) : [],
    churnAccum: r.churn_accum,
    centroid: r.centroid_json ? (JSON.parse(r.centroid_json) as number[]) : [],
    theta: r.theta,
    memberCount: r.member_count,
    emptyRuns: r.empty_runs,
    model: r.model,
    updatedAt: r.updated_at,
  };
}

/** All persisted topic clusters (with centroids — the warm-start seeds). The
 *  payload layer strips centroid_json before shipping; the pipeline needs it. */
export function listTopicClusters(): TopicClusterRow[] {
  try {
    return (getDb().prepare('SELECT * FROM topic_clusters ORDER BY id').all() as TopicClusterDbRow[]).map(
      mapTopicClusterRow,
    );
  } catch {
    return [];
  }
}

/** object_id → topic_id for every persisted assignment. */
export function getTopicAssignments(): Map<string, string> {
  try {
    const rows = getDb().prepare('SELECT object_id, topic_id FROM topic_assignments').all() as Array<{
      object_id: string;
      topic_id: string;
    }>;
    return new Map(rows.map((r) => [r.object_id, r.topic_id]));
  } catch {
    return new Map();
  }
}

/** Persist a whole clustering run in ONE transaction — readers never see a
 *  half-written map (decision #9 §1.2.9). Replaces the cluster + assignment
 *  tables wholesale from the pass's final state; `retired` ids are dropped.
 *  created_at survives for surviving ids (ON CONFLICT keeps the birth stamp). */
export function applyTopicRun(r: {
  clusters: TopicClusterRow[];
  retired: string[];
  assignments: Array<{ objectId: string; topicId: string; distance: number }>;
  run: { model: string; k: number; n: number; moved: number; paramsJson: string };
}): void {
  const d = getDb();
  const upC = d.prepare(
    `INSERT INTO topic_clusters
       (id, label, label_auto, label_locked, terms_json, churn_accum, centroid_json,
        theta, model, member_count, empty_runs, updated_at)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, strftime('%s','now'))
     ON CONFLICT(id) DO UPDATE SET
       label = excluded.label, label_auto = excluded.label_auto,
       label_locked = excluded.label_locked, terms_json = excluded.terms_json,
       churn_accum = excluded.churn_accum, centroid_json = excluded.centroid_json,
       theta = excluded.theta, model = excluded.model,
       member_count = excluded.member_count, empty_runs = excluded.empty_runs,
       updated_at = excluded.updated_at`,
  );
  const delC = d.prepare('DELETE FROM topic_clusters WHERE id = ?');
  const delA = d.prepare('DELETE FROM topic_assignments');
  const insA = d.prepare(
    `INSERT INTO topic_assignments (object_id, topic_id, distance, updated_at)
     VALUES (?, ?, ?, strftime('%s','now'))`,
  );
  const insRun = d.prepare(
    'INSERT INTO topic_runs (model, k, n, moved, params_json) VALUES (?, ?, ?, ?, ?)',
  );
  const tx = d.transaction(() => {
    for (const id of r.retired) delC.run(id);
    for (const c of r.clusters) {
      upC.run(
        c.id, c.label, c.labelAuto, c.labelLocked ? 1 : 0, JSON.stringify(c.terms),
        c.churnAccum, JSON.stringify(c.centroid), c.theta, c.model, c.memberCount, c.emptyRuns,
      );
    }
    delA.run();
    for (const a of r.assignments) insA.run(a.objectId, a.topicId, a.distance);
    insRun.run(r.run.model, r.run.k, r.run.n, r.run.moved, r.run.paramsJson);
  });
  tx();
}

/** Admin rename (decision #8): a label sets label_locked=1 (auto never
 *  overwrites); null unlocks and restores label_auto. false when id unknown. */
export function renameTopic(id: string, label: string | null): boolean {
  const d = getDb();
  if (label === null) {
    return (
      d
        .prepare(
          `UPDATE topic_clusters SET label = label_auto, label_locked = 0,
             updated_at = strftime('%s','now') WHERE id = ?`,
        )
        .run(id).changes > 0
    );
  }
  return (
    d
      .prepare(
        `UPDATE topic_clusters SET label = ?, label_locked = 1,
           updated_at = strftime('%s','now') WHERE id = ?`,
      )
      .run(label, id).changes > 0
  );
}

/** Admin re-anchor only (decision #9) — the one sanctioned θ change outside a
 *  full reset. false when id unknown. */
export function setTopicTheta(id: string, theta: number): boolean {
  return (
    getDb()
      .prepare("UPDATE topic_clusters SET theta = ?, updated_at = strftime('%s','now') WHERE id = ?")
      .run(theta, id).changes > 0
  );
}

/** Topic-mode summary for the payload meta + agent/admin status endpoints. */
export function topicStats(): { available: boolean; k: number; assigned: number; lastRunAt: number | null } {
  try {
    const k = (getDb().prepare('SELECT COUNT(*) AS c FROM topic_clusters').get() as { c: number }).c;
    const assigned = (getDb().prepare('SELECT COUNT(*) AS c FROM topic_assignments').get() as { c: number }).c;
    const last = getDb().prepare('SELECT MAX(ran_at) AS t FROM topic_runs').get() as { t: number | null };
    return { available: vectorsOk, k, assigned, lastRunAt: last?.t ?? null };
  } catch {
    return { available: false, k: 0, assigned: 0, lastRunAt: null };
  }
}

/** Most recent topic_runs row (params_json parsed) — the agent status endpoint's
 *  "last run summary". null before the first run or without the tables. */
export function lastTopicRun(): {
  ranAt: number;
  model: string;
  k: number;
  n: number;
  moved: number;
  params: unknown;
} | null {
  try {
    const r = getDb()
      .prepare('SELECT ran_at, model, k, n, moved, params_json FROM topic_runs ORDER BY ran_at DESC, id DESC LIMIT 1')
      .get() as
      | { ran_at: number; model: string; k: number; n: number; moved: number; params_json: string }
      | undefined;
    if (!r) return null;
    return {
      ranAt: r.ran_at,
      model: r.model,
      k: r.k,
      n: r.n,
      moved: r.moved,
      params: r.params_json ? JSON.parse(r.params_json) : null,
    };
  } catch {
    return null;
  }
}

// ── Lint findings (server/lint.ts) ────────────────────────────────────────────

export interface LintFindingRow {
  id: string;
  checkId: string;
  severity: string;
  refKind?: string;
  refId?: string;
  message: string;
  data?: Record<string, unknown>;
  firstSeen: number;
  lastSeen: number;
  resolvedAt: number | null;
}

/** Raw lint_findings row — snake_case DB columns before mapping. */
interface LintDbRow {
  id: string;
  check_id: string;
  severity: string;
  ref_kind: string | null;
  ref_id: string | null;
  message: string;
  data: string | null;
  first_seen: number;
  last_seen: number;
  resolved_at: number | null;
}

function mapLintRow(row: LintDbRow): LintFindingRow {
  return {
    id: row.id,
    checkId: row.check_id,
    severity: row.severity,
    refKind: row.ref_kind ?? undefined,
    refId: row.ref_id ?? undefined,
    message: row.message,
    data: row.data ? JSON.parse(row.data) : undefined,
    firstSeen: row.first_seen,
    lastSeen: row.last_seen,
    resolvedAt: row.resolved_at ?? null,
  };
}

/**
 * Reconcile a full lint run against the stored findings:
 *   - unknown id            -> insert (NEW finding)
 *   - known, open           -> refresh last_seen
 *   - known, was resolved   -> reopen (resolved_at = NULL, new first_seen)
 *   - open but not in run   -> stamp resolved_at
 * Returns the ids that are new/reopened this run and those just resolved.
 */
export function syncLintFindings(
  findings: Array<{
    id: string;
    checkId: string;
    severity: string;
    refKind?: string;
    refId?: string;
    message: string;
    data?: unknown;
  }>,
): { newIds: string[]; resolvedIds: string[] } {
  const d = getDb();
  const newIds: string[] = [];
  const resolvedIds: string[] = [];
  const tx = d.transaction(() => {
    const openRows = d
      .prepare('SELECT id FROM lint_findings WHERE resolved_at IS NULL')
      .all() as Array<{ id: string }>;
    const open = new Set(openRows.map((r) => r.id));
    const seen = new Set<string>();
    const insert = d.prepare(
      `INSERT INTO lint_findings (id, check_id, severity, ref_kind, ref_id, message, data)
       VALUES (?, ?, ?, ?, ?, ?, ?)
       ON CONFLICT(id) DO UPDATE SET
         severity = excluded.severity,
         message = excluded.message,
         data = excluded.data,
         last_seen = strftime('%s','now'),
         first_seen = CASE WHEN lint_findings.resolved_at IS NOT NULL
                           THEN strftime('%s','now') ELSE lint_findings.first_seen END,
         resolved_at = NULL`,
    );
    const wasKnown = d.prepare('SELECT resolved_at, severity, data FROM lint_findings WHERE id = ?');
    for (const f of findings) {
      if (seen.has(f.id)) continue; // a check may emit the same pair twice
      const prior = wasKnown.get(f.id) as
        | { resolved_at: number | null; severity: string; data: string | null }
        | undefined;
      const priorData = prior?.data ? JSON.parse(prior.data) : null;
      const verdict = priorData?.verdict?.verdict;
      // A standing librarian/human verdict outlives the re-detection:
      //   fine          -> stays resolved (skip entirely, no reopen)
      //   dup/contradic -> stays open at the ESCALATED severity, verdict kept
      if (verdict === 'fine') continue;
      seen.add(f.id);
      let severity = f.severity;
      let data = f.data;
      if (verdict === 'duplicate' || verdict === 'contradiction') {
        // A verdict only exists when a prior row carried it.
        severity = prior!.severity; // escalation from applyLintVerdict wins
        data = { ...((f.data ?? {}) as Record<string, unknown>), verdict: priorData.verdict };
      }
      if (!prior || prior.resolved_at !== null) newIds.push(f.id);
      insert.run(
        f.id, f.checkId, severity, f.refKind ?? null, f.refId ?? null,
        f.message, data === undefined ? null : JSON.stringify(data),
      );
    }
    const resolve = d.prepare(
      "UPDATE lint_findings SET resolved_at = strftime('%s','now') WHERE id = ?",
    );
    for (const id of open) {
      if (!seen.has(id)) {
        resolve.run(id);
        resolvedIds.push(id);
      }
    }
  });
  tx();
  return { newIds, resolvedIds };
}

export function getLintFindings(includeResolved = false, limit = 500): LintFindingRow[] {
  const d = getDb();
  // Semantic severity ranking — a bare ORDER BY severity is alphabetical
  // (critical, high, info, low, medium) and buries low under info.
  const rank =
    "CASE severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 WHEN 'low' THEN 3 ELSE 4 END";
  const rows = includeResolved
    ? d.prepare(`SELECT * FROM lint_findings ORDER BY resolved_at IS NULL DESC, ${rank}, last_seen DESC LIMIT ?`).all(limit)
    : d.prepare(`SELECT * FROM lint_findings WHERE resolved_at IS NULL ORDER BY ${rank}, last_seen DESC LIMIT ?`).all(limit);
  return (rows as LintDbRow[]).map(mapLintRow);
}

/**
 * Pairwise near-neighbour scan for the lint duplicate checks. O(n²) in SQL,
 * which is fine for the non-taxonomy corpus (tens–hundreds of rows) and
 * acceptable for the 790-node taxonomy sweep inside a nightly job. rowid
 * ordering dedupes the symmetric pair.
 */
export function nearPairs(
  kinds: EmbeddingKind[],
  maxDistance: number,
  limit: number,
): Array<{ aKind: string; aRefId: string; bKind: string; bRefId: string; distance: number }> {
  if (!vectorsOk || kinds.length === 0) return [];
  const kindList = kinds.map(() => '?').join(',');
  return getDb()
    .prepare(
      `SELECT a.kind AS aKind, a.ref_id AS aRefId,
              b.kind AS bKind, b.ref_id AS bRefId,
              vector_distance_cos(a.vector, b.vector) AS distance
       FROM embeddings a
       JOIN embeddings b ON a.rowid < b.rowid
       WHERE a.kind IN (${kindList}) AND b.kind IN (${kindList})
         AND vector_distance_cos(a.vector, b.vector) < ?
       ORDER BY distance ASC
       LIMIT ?`,
    )
    .all(...kinds, ...kinds, maxDistance, limit) as Array<{
    aKind: string;
    aRefId: string;
    bKind: string;
    bRefId: string;
    distance: number;
  }>;
}

export function countRows(table: 'taxonomy_fts' | 'taxonomy_layout'): number {
  try {
    return (getDb().prepare(`SELECT COUNT(*) AS c FROM ${table}`).get() as { c: number }).c;
  } catch {
    return -1;
  }
}

/**
 * Librarian verdict on a lint finding (the Layer-2 judgment loop):
 *   fine          -> finding resolves (judged a false positive / acceptable)
 *   duplicate     -> stays open, escalated to medium (human should merge)
 *   contradiction -> stays open, escalated to high (knowledge conflict!)
 * The verdict is preserved in data.verdict even after resolution, so a
 * re-appearing pair carries its judgment history.
 */
export function applyLintVerdict(
  findingId: string,
  verdict: 'fine' | 'duplicate' | 'contradiction',
  note: string | undefined,
  by: string,
): LintFindingRow | null {
  const d = getDb();
  const row = d.prepare('SELECT * FROM lint_findings WHERE id = ?').get(findingId) as LintDbRow | undefined;
  if (!row) return null;
  const data = row.data ? JSON.parse(row.data) : {};
  data.verdict = { verdict, note: note ?? null, by, at: Math.floor(Date.now() / 1000) };
  if (verdict === 'fine') {
    d.prepare(
      "UPDATE lint_findings SET data = ?, resolved_at = strftime('%s','now') WHERE id = ?",
    ).run(JSON.stringify(data), findingId);
  } else {
    const severity = verdict === 'contradiction' ? 'high' : 'medium';
    d.prepare('UPDATE lint_findings SET data = ?, severity = ? WHERE id = ?').run(
      JSON.stringify(data), severity, findingId,
    );
  }
  return mapLintRow(d.prepare('SELECT * FROM lint_findings WHERE id = ?').get(findingId) as LintDbRow);
}

// ── Promotion proposals (server/promotions.ts) ────────────────────────────────

/** Union-of-drafts payload of a promotion — the concrete shape depends on
 *  `kind` (ObjectDraft | NodeDraft | DescDraft | BriefDraft, defined in
 *  server/promotions.ts). Kept structural here so db.ts stays below
 *  promotions.ts in the import graph. */
export type PromotionDraft = {
  id?: string;
  type?: string;
  title?: string;
  description?: string;
  body?: string;
  resource?: string;
  tags?: string[];
  parentId?: string;
  name?: string;
  nodeId?: string;
  descriptionEn?: string;
  descriptionCs?: string;
  briefEn?: string;
  briefCs?: string;
};

export interface PromotionRow {
  id: string;
  kind: 'object' | 'node' | 'desc' | 'brief';
  captureId: string;
  proposedBy: string;
  rationale?: string;
  object: PromotionDraft;
  status: 'proposed' | 'approved' | 'rejected';
  votes: Array<{ by: string; value: 1 | -1; at: number }>;
  decidedBy?: string;
  decidedAt?: number;
  objectId?: string;
  createdAt: number;
}

/** Raw promotions row — snake_case DB columns before mapping. */
interface PromotionDbRow {
  id: string;
  kind: PromotionRow['kind'] | null;
  capture_id: string;
  proposed_by: string;
  rationale: string | null;
  object_json: string;
  status: PromotionRow['status'];
  votes: string | null;
  decided_by: string | null;
  decided_at: number | null;
  object_id: string | null;
  created_at: number;
}

function mapPromotionRow(row: PromotionDbRow): PromotionRow {
  return {
    id: row.id,
    kind: row.kind ?? 'object',
    captureId: row.capture_id,
    proposedBy: row.proposed_by,
    rationale: row.rationale ?? undefined,
    object: JSON.parse(row.object_json),
    status: row.status,
    votes: JSON.parse(row.votes || '[]'),
    decidedBy: row.decided_by ?? undefined,
    decidedAt: row.decided_at ?? undefined,
    objectId: row.object_id ?? undefined,
    createdAt: row.created_at,
  };
}

export function upsertPromotion(p: {
  id: string;
  captureId: string;
  proposedBy: string;
  rationale?: string;
  object: PromotionDraft;
  kind?: 'object' | 'node' | 'desc' | 'brief';
}): void {
  getDb()
    .prepare(
      `INSERT INTO promotions (id, kind, capture_id, proposed_by, rationale, object_json)
       VALUES (?, ?, ?, ?, ?, ?)
       ON CONFLICT(id) DO UPDATE SET
         rationale = excluded.rationale,
         object_json = excluded.object_json,
         proposed_by = excluded.proposed_by`,
    )
    .run(p.id, p.kind ?? 'object', p.captureId, p.proposedBy, p.rationale ?? null, JSON.stringify(p.object));
}

export function getPromotion(id: string): PromotionRow | null {
  const row = getDb().prepare('SELECT * FROM promotions WHERE id = ?').get(id) as
    | PromotionDbRow
    | undefined;
  return row ? mapPromotionRow(row) : null;
}

export function listPromotions(status?: string, limit = 200): PromotionRow[] {
  const d = getDb();
  const rows = status
    ? d.prepare('SELECT * FROM promotions WHERE status = ? ORDER BY created_at DESC LIMIT ?').all(status, limit)
    : d.prepare('SELECT * FROM promotions ORDER BY created_at DESC LIMIT ?').all(limit);
  return (rows as PromotionDbRow[]).map(mapPromotionRow);
}

/**
 * ALL open proposals, uncapped. The dup-guards in promotions.ts and the
 * pending-exclusion sets in agent.ts MUST see every open row — reading them
 * through listPromotions' LIMIT 200 made the guards blind past 200 open
 * proposals (duplicate desc rows, re-served pending nodes).
 */
export function openPromotions(): PromotionRow[] {
  const rows = getDb()
    .prepare("SELECT * FROM promotions WHERE status = 'proposed' ORDER BY created_at DESC")
    .all();
  return (rows as PromotionDbRow[]).map(mapPromotionRow);
}

export function setPromotionVotes(id: string, votes: unknown[]): void {
  getDb().prepare('UPDATE promotions SET votes = ? WHERE id = ?').run(JSON.stringify(votes), id);
}

export function setPromotionDecision(
  id: string,
  status: 'approved' | 'rejected',
  decidedBy: string,
  objectId: string | null,
): void {
  getDb()
    .prepare(
      "UPDATE promotions SET status = ?, decided_by = ?, decided_at = strftime('%s','now'), object_id = ? WHERE id = ?",
    )
    .run(status, decidedBy, objectId, id);
}

/** Provenance back-link on the source capture: metadata.promotedTo. */
export function markCapturePromoted(captureId: string, objectId: string): void {
  const d = getDb();
  const row = d.prepare('SELECT metadata FROM api_taxonomy_metadata WHERE id = ?').get(captureId) as
    | { metadata: string | null }
    | undefined;
  if (!row) return;
  const meta = row.metadata ? JSON.parse(row.metadata) : {};
  meta.promotedTo = objectId;
  d.prepare("UPDATE api_taxonomy_metadata SET metadata = ?, updated_at = strftime('%s','now') WHERE id = ?")
    .run(JSON.stringify(meta), captureId);
}

// ── Dynamic taxonomy nodes (Track T) ──────────────────────────────────────────

export interface ExtNodeRow {
  id: string;
  parentId: string;
  name: string;
  description: string;
  zone: string;
  ordinal: number;
  proposedBy: string;
  approvedBy: string;
  createdAt: number;
}

export function listExtNodes(): ExtNodeRow[] {
  return (
    getDb().prepare('SELECT * FROM taxonomy_nodes_ext ORDER BY created_at, ordinal').all() as Array<{
      id: string;
      parent_id: string;
      name: string;
      description: string;
      zone: string;
      ordinal: number;
      proposed_by: string;
      approved_by: string;
      created_at: number;
    }>
  ).map(
    (r) => ({
      id: r.id,
      parentId: r.parent_id,
      name: r.name,
      description: r.description,
      zone: r.zone,
      ordinal: r.ordinal,
      proposedBy: r.proposed_by,
      approvedBy: r.approved_by,
      createdAt: r.created_at,
    }),
  );
}

export function insertExtNode(n: Omit<ExtNodeRow, 'createdAt'>): void {
  getDb()
    .prepare(
      `INSERT INTO taxonomy_nodes_ext (id, parent_id, name, description, zone, ordinal, proposed_by, approved_by)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
    )
    .run(n.id, n.parentId, n.name, n.description, n.zone, n.ordinal, n.proposedBy, n.approvedBy);
}

// ── Curated node descriptions (Track K, K1) ───────────────────────────────────

export interface NodeDescriptionRow {
  nodeId: string;
  descriptionEn: string;
  descriptionCs?: string;
  proposedBy: string;
  approvedBy: string;
  updatedAt: number;
}

export function listNodeDescriptions(): NodeDescriptionRow[] {
  return (
    getDb().prepare('SELECT * FROM node_descriptions').all() as Array<{
      node_id: string;
      description_en: string;
      description_cs: string | null;
      proposed_by: string;
      approved_by: string;
      updated_at: number;
    }>
  ).map((r) => ({
    nodeId: r.node_id,
    descriptionEn: r.description_en,
    descriptionCs: r.description_cs ?? undefined,
    proposedBy: r.proposed_by,
    approvedBy: r.approved_by,
    updatedAt: r.updated_at,
  }));
}

export function upsertNodeDescription(row: Omit<NodeDescriptionRow, 'updatedAt'>): void {
  getDb()
    .prepare(
      `INSERT INTO node_descriptions (node_id, description_en, description_cs, proposed_by, approved_by)
       VALUES (?, ?, ?, ?, ?)
       ON CONFLICT(node_id) DO UPDATE SET
         description_en = excluded.description_en,
         description_cs = excluded.description_cs,
         proposed_by = excluded.proposed_by,
         approved_by = excluded.approved_by,
         updated_at = strftime('%s','now')`,
    )
    .run(row.nodeId, row.descriptionEn, row.descriptionCs ?? null, row.proposedBy, row.approvedBy);
}

/** How many ext children a parent already has — the next append ordinal. */
export function extChildCount(parentId: string): number {
  return (
    getDb().prepare('SELECT COUNT(*) AS c FROM taxonomy_nodes_ext WHERE parent_id = ?').get(parentId) as {
      c: number;
    }
  ).c;
}

export interface ConceptRelation {
  from: string;
  to: string;
  type: string;
  explored: string | null;
}

/** Upsert one typed concept relation (idempotent on from,to,type). */
export function insertConceptRelation(r: ConceptRelation & { source?: string }): void {
  getDb()
    .prepare(
      `INSERT INTO concept_relations (from_id, to_id, type, explored, source)
       VALUES (?, ?, ?, ?, ?)
       ON CONFLICT(from_id, to_id, type) DO UPDATE SET explored = excluded.explored`,
    )
    .run(r.from, r.to, r.type, r.explored ?? null, r.source ?? 'toe');
}

/** All concept relations. `typedOnly` drops the generic 'related-concept' edges. */
export function listConceptRelations(typedOnly = true): ConceptRelation[] {
  const sql = typedOnly
    ? `SELECT from_id, to_id, type, explored FROM concept_relations WHERE type != 'related-concept'`
    : `SELECT from_id, to_id, type, explored FROM concept_relations`;
  return (
    getDb().prepare(sql).all() as Array<{ from_id: string; to_id: string; type: string; explored: string | null }>
  ).map((r) => ({
    from: r.from_id,
    to: r.to_id,
    type: r.type,
    explored: r.explored ?? null,
  }));
}

// ── Typed cross-type relations (Track R3 stage 1) ───────────────────────────
// A GENERALIZED store beside concept_relations (which stays the ToE ingest
// target, shape-frozen). `relations` carries node↔object edges with provenance
// + a moderation status; the ToE set is mirrored in as source='toe',
// status='confirmed' (syncToeRelations, a boot step). Derived edges land
// status='proposed' from the host-side classifier via /agent/v1/relations and
// stay hidden until stage-2 moderation confirms them. See server/migrations.ts
// (006-typed-relations) and server/relations.ts (candidate recall).

export type RelationKind = 'node' | 'object';
export type RelationSource = 'toe' | 'derived' | 'manual';
export type RelationStatus = 'proposed' | 'confirmed' | 'rejected';

export interface RelationRow {
  id: string;
  fromRef: string;
  fromKind: RelationKind;
  toRef: string;
  toKind: RelationKind;
  type: string;
  confidence: number | null;
  justification: string | null;
  source: RelationSource;
  status: RelationStatus;
  model: string | null;
  createdAt: number | null;
}

export interface RelationTypeRow {
  type: string;
  label: string;
  color: string | null;
  description: string | null;
  status: 'seed' | 'proposed' | 'confirmed';
}

interface RelationDbRow {
  id: string;
  from_ref: string;
  from_kind: string;
  to_ref: string;
  to_kind: string;
  type: string;
  confidence: number | null;
  justification: string | null;
  source: string;
  status: string;
  model: string | null;
  created_at: number | null;
}

function mapRelationRow(r: RelationDbRow): RelationRow {
  return {
    id: r.id,
    fromRef: r.from_ref,
    fromKind: r.from_kind as RelationKind,
    toRef: r.to_ref,
    toKind: r.to_kind as RelationKind,
    type: r.type,
    confidence: r.confidence,
    justification: r.justification,
    source: r.source as RelationSource,
    status: r.status as RelationStatus,
    model: r.model,
    createdAt: r.created_at,
  };
}

/** Stable id for a relation row — a hash of its idempotency key so the same
 *  edge always resolves to the same PK regardless of who writes it. */
function relationId(fromRef: string, toRef: string, type: string): string {
  return `r-${crypto.createHash('sha1').update(`${fromRef} ${toRef} ${type}`).digest('hex').slice(0, 16)}`;
}

/** ToE `explored` rating → a confidence scalar for the generalized store. */
function exploredToConfidence(explored: string | null): number | null {
  switch (explored) {
    case 'well':
      return 1.0;
    case 'partially':
      return 0.6;
    case 'barely':
      return 0.3;
    default:
      return null;
  }
}

// The base controlled vocabulary (status='seed'), seeded idempotently at boot.
// color reuses the ToE edge palette hues (GraphCanvas REL_COLOR) where a verb
// overlaps in spirit; the rest get distinct hues for stage-2 rendering.
const RELATION_TYPE_SEED: Array<{ type: string; label: string; color: string; description: string }> = [
  { type: 'depends-on', label: 'depends on', color: '#22d3ee', description: 'The source requires the target to hold or exist.' },
  // The skill router's precondition verb: (skill card) —requires→ (credential
  // node). Written by the MECHANICAL Requires:-line producer, never the LLM
  // classifier — distinct from depends-on, which the classifier uses for
  // conceptual dependency between knowledge items.
  { type: 'requires', label: 'requires', color: '#f59e0b', description: 'The source cannot run or apply without the target.' },
  { type: 'prerequisite-for', label: 'prerequisite for', color: '#38bdf8', description: 'The source must be understood before the target.' },
  { type: 'supports', label: 'supports', color: '#34d399', description: 'The source is evidence for the target.' },
  { type: 'refutes', label: 'refutes', color: '#f87171', description: 'The source is evidence against the target.' },
  { type: 'contradicts', label: 'contradicts', color: '#ef4444', description: 'The two are in direct conflict.' },
  { type: 'generalizes', label: 'generalizes', color: '#a78bfa', description: 'The source is a broader case of the target.' },
  { type: 'specializes', label: 'specializes', color: '#c084fc', description: 'The source is a narrower case of the target.' },
  { type: 'exemplifies', label: 'exemplifies', color: '#fbbf24', description: 'The source is an instance or example of the target.' },
  { type: 'defines', label: 'defines', color: '#fcd34d', description: 'The source gives the definition of the target.' },
  { type: 'supersedes', label: 'supersedes', color: '#fb923c', description: 'The source replaces or obsoletes the target.' },
  { type: 'causes', label: 'causes', color: '#f472b6', description: 'The source brings about the target.' },
  { type: 'derived-from', label: 'derived from', color: '#e879f9', description: 'The source is derived from the target.' },
  { type: 'analogous-to', label: 'analogous to', color: '#5eead4', description: 'The two share an analogous structure.' },
  { type: 'duality', label: 'duality', color: '#f472b6', description: 'The two are dual formulations of one another.' },
  { type: 'related-concept', label: 'related', color: 'rgba(120,130,150,0.30)', description: 'A generic semantic relation.' },
];

/** Idempotently seed the base controlled vocabulary. Existing rows (including
 *  any an admin or agent already grew) are left untouched. Boot step. */
export function seedRelationTypes(): void {
  const d = getDb();
  const stmt = d.prepare(
    `INSERT OR IGNORE INTO relation_types (type, label, color, description, status, created_at)
     VALUES (?, ?, ?, ?, 'seed', strftime('%s','now'))`,
  );
  const tx = d.transaction(() => {
    for (const t of RELATION_TYPE_SEED) stmt.run(t.type, t.label, t.color, t.description);
  });
  tx();
}

export function listRelationTypes(): RelationTypeRow[] {
  return (
    getDb()
      .prepare('SELECT type, label, color, description, status FROM relation_types ORDER BY type')
      .all() as Array<{ type: string; label: string; color: string | null; description: string | null; status: string }>
  ).map((r) => ({ ...r, status: r.status as RelationTypeRow['status'] }));
}

export function getRelationType(type: string): RelationTypeRow | null {
  const r = getDb()
    .prepare('SELECT type, label, color, description, status FROM relation_types WHERE type = ?')
    .get(type) as
    | { type: string; label: string; color: string | null; description: string | null; status: string }
    | undefined;
  return r ? { ...r, status: r.status as RelationTypeRow['status'] } : null;
}

/** Grow the vocabulary under moderation: an unknown proposed type lands as
 *  status='proposed' (stage-2 admin confirms/retires). Idempotent — a second
 *  proposal of the same type is a no-op. Returns true iff a new row was added. */
export function insertProposedRelationType(type: string, proposedBy: string): boolean {
  const res = getDb()
    .prepare(
      `INSERT OR IGNORE INTO relation_types (type, label, color, description, status, created_at)
       VALUES (?, ?, NULL, ?, 'proposed', strftime('%s','now'))`,
    )
    .run(type, type, `Proposed by ${proposedBy}.`);
  return res.changes > 0;
}

/** Mirror the ToE concept_relations set into the generalized store as
 *  node↔node, source='toe', status='confirmed'. A LIVE mirror (delete + rebuild
 *  the source='toe' partition), so a re-ingest that rewrites concept_relations
 *  is reflected on the next boot; derived rows (source!='toe') are untouched.
 *  When a concept_relation collides with a pre-existing derived row on the same
 *  (from_ref,to_ref,type), that row is claimed by ToE: it flips to source='toe',
 *  status='confirmed' AND its classifier provenance (justification, model) is
 *  reset to NULL — a ToE-partition row carries no derived provenance.
 *  Boot step, runs after migrations. */
export function syncToeRelations(): void {
  const d = getDb();
  const rows = d
    .prepare('SELECT from_id, to_id, type, explored FROM concept_relations')
    .all() as Array<{ from_id: string; to_id: string; type: string; explored: string | null }>;
  const now = Math.floor(Date.now() / 1000);
  const ins = d.prepare(
    `INSERT INTO relations (id, from_ref, to_ref, from_kind, to_kind, type, confidence, justification, source, status, model, created_at)
     VALUES (?, ?, ?, 'node', 'node', ?, ?, NULL, 'toe', 'confirmed', NULL, ?)
     ON CONFLICT(from_ref, to_ref, type) DO UPDATE SET
       from_kind = 'node', to_kind = 'node',
       confidence = excluded.confidence, source = 'toe', status = 'confirmed',
       justification = NULL, model = NULL`,
  );
  const tx = d.transaction(() => {
    d.prepare("DELETE FROM relations WHERE source = 'toe'").run();
    for (const r of rows) {
      ins.run(relationId(r.from_id, r.to_id, r.type), r.from_id, r.to_id, r.type, exploredToConfidence(r.explored), now);
    }
  });
  tx();
}

/** Upsert one derived typed relation (host-side classifier output). Lands
 *  status='proposed', source='derived' — the moderation gate. Idempotent on
 *  (from_ref,to_ref,type): a re-propose refreshes confidence/justification/model,
 *  never a duplicate row. A prior ADMIN VERDICT is sticky: once an admin set the
 *  row terminal ('confirmed'|'rejected'), a re-POST keeps that status — the
 *  classifier can refresh provenance but MUST NOT resurrect a rejected edge back
 *  to 'proposed' (spatial-memory / moderation invariant). Only a still-'proposed'
 *  row is re-armed as 'proposed'. */
export function insertDerivedRelation(r: {
  fromRef: string;
  fromKind: RelationKind;
  toRef: string;
  toKind: RelationKind;
  type: string;
  confidence: number;
  justification: string;
  model: string | null;
}): void {
  const now = Math.floor(Date.now() / 1000);
  getDb()
    .prepare(
      `INSERT INTO relations (id, from_ref, to_ref, from_kind, to_kind, type, confidence, justification, source, status, model, created_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'derived', 'proposed', ?, ?)
       ON CONFLICT(from_ref, to_ref, type) DO UPDATE SET
         from_kind = excluded.from_kind, to_kind = excluded.to_kind,
         confidence = excluded.confidence, justification = excluded.justification,
         model = excluded.model, source = 'derived',
         status = CASE WHEN relations.status IN ('confirmed', 'rejected')
                       THEN relations.status ELSE 'proposed' END`,
    )
    .run(
      relationId(r.fromRef, r.toRef, r.type),
      r.fromRef,
      r.toRef,
      r.fromKind,
      r.toKind,
      r.type,
      r.confidence,
      r.justification,
      r.model,
      now,
    );
}

/** Full relation rows for the agent + moderation readers, optionally filtered
 *  by status and/or source. Ordered newest-first for the moderation queue. */
export function listRelations(filter?: { status?: RelationStatus; source?: RelationSource }): RelationRow[] {
  const clauses: string[] = [];
  const args: string[] = [];
  if (filter?.status) {
    clauses.push('status = ?');
    args.push(filter.status);
  }
  if (filter?.source) {
    clauses.push('source = ?');
    args.push(filter.source);
  }
  const where = clauses.length ? `WHERE ${clauses.join(' AND ')}` : '';
  return (
    getDb()
      .prepare(
        `SELECT id, from_ref, from_kind, to_ref, to_kind, type, confidence, justification, source, status, model, created_at
         FROM relations ${where} ORDER BY created_at DESC, id`,
      )
      .all(...args) as RelationDbRow[]
  ).map(mapRelationRow);
}

/** One relation row by id (moderation gate reads it to check the verb's vocab
 *  status before confirming). Null when the id no longer resolves. */
export function getRelation(id: string): RelationRow | null {
  const r = getDb()
    .prepare(
      `SELECT id, from_ref, from_kind, to_ref, to_kind, type, confidence, justification, source, status, model, created_at
       FROM relations WHERE id = ?`,
    )
    .get(id) as RelationDbRow | undefined;
  return r ? mapRelationRow(r) : null;
}

/** Stage-2 moderation: flip one relation's status (proposed→confirmed/rejected).
 *  Returns true iff a row was updated. The graph overlay + brain endpoint read
 *  status='confirmed'; 'rejected' never renders (spatial-memory invariant). */
export function setRelationStatus(id: string, status: RelationStatus): boolean {
  return getDb().prepare('UPDATE relations SET status = ? WHERE id = ?').run(status, id).changes > 0;
}

/** Stage-2 vocab growth: confirm a proposed relation_type into the live palette,
 *  assigning it a render colour (COALESCE keeps any existing colour when the
 *  caller passes none). A confirmed verb re-enters the classifier vocabulary
 *  (agent.ts filters seed|confirmed). Returns true iff a row was updated. */
export function setRelationTypeStatus(
  type: string,
  status: RelationTypeRow['status'],
  color?: string,
): boolean {
  return getDb()
    .prepare('UPDATE relation_types SET status = ?, color = COALESCE(?, color) WHERE type = ?')
    .run(status, color ?? null, type).changes > 0;
}

/** Stage-2 vocab moderation: retire a PROPOSED verb (rejecting the growth). Seed
 *  and confirmed vocabulary is protected — only the proposed partition deletes.
 *  Returns true iff a row was removed. */
export function deleteRelationType(type: string): boolean {
  return getDb()
    .prepare("DELETE FROM relation_types WHERE type = ? AND status = 'proposed'")
    .run(type).changes > 0;
}

/** True iff a relation already exists between two refs in EITHER direction (any
 *  type). Used to skip already-stored pairs during candidate recall. */
export function relationPairExists(aRef: string, bRef: string): boolean {
  return Boolean(
    getDb()
      .prepare(
        `SELECT 1 FROM relations
         WHERE (from_ref = ? AND to_ref = ?) OR (from_ref = ? AND to_ref = ?) LIMIT 1`,
      )
      .get(aRef, bRef, bRef, aRef),
  );
}

/**
 * Cross-kind near-neighbour sweep for typed-relation candidate generation
 * (server/relations.ts). Same O(n²) SQL shape as nearPairs, but: restricted to
 * CROSS-kind pairs (a.kind<>b.kind), already-stored pairs excluded in-SQL
 * (NOT EXISTS over relations, either direction), and optionally INCREMENTAL —
 * `sinceTs` keeps only pairs where at least one endpoint's vector changed after
 * that watermark. rowid ordering dedupes the symmetric pair. Bounded by `limit`.
 */
export function nearCrossKindPairs(
  kinds: EmbeddingKind[],
  maxDistance: number,
  limit: number,
  sinceTs?: number,
): Array<{ aKind: string; aRefId: string; bKind: string; bRefId: string; distance: number }> {
  if (!vectorsOk || kinds.length === 0) return [];
  const kindList = kinds.map(() => '?').join(',');
  const sinceClause = sinceTs != null ? 'AND (a.updated_at > ? OR b.updated_at > ?)' : '';
  const sinceArgs = sinceTs != null ? [sinceTs, sinceTs] : [];
  return getDb()
    .prepare(
      `SELECT a.kind AS aKind, a.ref_id AS aRefId,
              b.kind AS bKind, b.ref_id AS bRefId,
              vector_distance_cos(a.vector, b.vector) AS distance
       FROM embeddings a
       JOIN embeddings b ON a.rowid < b.rowid
       WHERE a.kind IN (${kindList}) AND b.kind IN (${kindList})
         AND a.kind <> b.kind
         AND vector_distance_cos(a.vector, b.vector) < ?
         ${sinceClause}
         AND NOT EXISTS (
           SELECT 1 FROM relations r
           WHERE (r.from_ref = a.ref_id AND r.to_ref = b.ref_id)
              OR (r.from_ref = b.ref_id AND r.to_ref = a.ref_id)
         )
       ORDER BY distance ASC, aKind, aRefId, bKind, bRefId
       LIMIT ?`,
    )
    .all(...kinds, ...kinds, maxDistance, ...sinceArgs, limit) as Array<{
    aKind: string;
    aRefId: string;
    bKind: string;
    bRefId: string;
    distance: number;
  }>;
}

// ── Curator work-log (docs/plans/keap-curator-agent.md §9) ──────────────────
export interface CuratorVisit {
  visitedAt: number;
  contentHash: string | null;
  runId: string;
}

/** Latest visit per node across ALL runs — the frontier's staleness signal. */
export function curatorVisitMap(): Map<string, CuratorVisit> {
  const rows = getDb()
    .prepare(
      `SELECT node_id, run_id, content_hash, MAX(visited_at) AS visited_at
         FROM curator_visits GROUP BY node_id`,
    )
    .all() as Array<{ node_id: string; run_id: string; content_hash: string | null; visited_at: number }>;
  const m = new Map<string, CuratorVisit>();
  for (const r of rows) m.set(r.node_id, { visitedAt: r.visited_at, contentHash: r.content_hash ?? null, runId: r.run_id });
  return m;
}

/** Open a run row (idempotent — re-opening the same run_id is a no-op reset). */
export function startCuratorRun(runId: string, paramsJson: string | null, budgetTokens: number | null): void {
  getDb()
    .prepare(
      `INSERT INTO curator_runs (run_id, params_json, budget_tokens, status)
       VALUES (?, ?, ?, 'running')
       ON CONFLICT(run_id) DO UPDATE SET
         params_json = excluded.params_json,
         budget_tokens = excluded.budget_tokens,
         status = 'running',
         ended_at = NULL`,
    )
    .run(runId, paramsJson, budgetTokens);
}

/** Close a run row with the final tallies. */
export function finishCuratorRun(
  runId: string,
  t: { tokensSpent?: number; nodesVisited?: number; proposalsMade?: number; proposalsApproved?: number; status?: string },
): void {
  getDb()
    .prepare(
      `UPDATE curator_runs SET
         ended_at = strftime('%s','now'),
         tokens_spent = COALESCE(?, tokens_spent),
         nodes_visited = COALESCE(?, nodes_visited),
         proposals_made = COALESCE(?, proposals_made),
         proposals_approved = COALESCE(?, proposals_approved),
         status = COALESCE(?, 'done')
       WHERE run_id = ?`,
    )
    .run(
      t.tokensSpent ?? null,
      t.nodesVisited ?? null,
      t.proposalsMade ?? null,
      t.proposalsApproved ?? null,
      t.status ?? null,
      runId,
    );
}

/** Upsert one node visit and bump the run's rolling counters. */
export function recordCuratorVisit(v: {
  nodeId: string;
  runId: string;
  pass?: number;
  contentHash?: string | null;
  findingsCount?: number;
  proposalsCount?: number;
  action?: string | null;
}): void {
  const d = getDb();
  const existed = d.prepare('SELECT 1 FROM curator_visits WHERE node_id = ? AND run_id = ?').get(v.nodeId, v.runId);
  d.prepare(
    `INSERT INTO curator_visits (node_id, run_id, pass, content_hash, findings_count, proposals_count, action)
     VALUES (?, ?, ?, ?, ?, ?, ?)
     ON CONFLICT(node_id, run_id) DO UPDATE SET
       pass = excluded.pass,
       visited_at = strftime('%s','now'),
       content_hash = excluded.content_hash,
       findings_count = excluded.findings_count,
       proposals_count = excluded.proposals_count,
       action = excluded.action`,
  ).run(
    v.nodeId,
    v.runId,
    v.pass ?? 0,
    v.contentHash ?? null,
    v.findingsCount ?? 0,
    v.proposalsCount ?? 0,
    v.action ?? null,
  );
  // Advance the run's node cursor on a FRESH node visit only (a re-post of the
  // same node doesn't double-count). proposals_made is owned by run/finish (the
  // agent's authoritative tally) so a frontier-served pre-checkpoint that later
  // gets enriched by /visit never mis-counts proposals.
  if (!existed) {
    d.prepare(`UPDATE curator_runs SET nodes_visited = nodes_visited + 1 WHERE run_id = ?`).run(v.runId);
  }
}

/** Append one star to the baked layout under the CURRENT version (U1 append). */
export function appendLayoutPoint(nodeId: string, x: number, y: number, z: number): void {
  const version = getLayoutVersion() ?? 'v1:unbaked';
  getDb()
    .prepare(
      `INSERT INTO taxonomy_layout (node_id, x, y, z, layout_version)
       VALUES (?, ?, ?, ?, ?)
       ON CONFLICT(node_id) DO UPDATE SET x = excluded.x, y = excluded.y, z = excluded.z`,
    )
    .run(nodeId, x, y, z, version);
}
