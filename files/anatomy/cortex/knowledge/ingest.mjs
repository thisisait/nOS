/**
 * Canonical knowledge importer (the inverse of dump.mjs) — the single, idempotent
 * ingest path that makes knowledge/canonical/ the source of truth.
 *
 * Reads knowledge/canonical/<L0>/<L1>.json (each = one L1 domain: ext nodes +
 * K1 description overrides + briefs + typed relations), and materialises the
 * curated delta over the static seed spine into the live DB. Replaces the
 * per-domain import-domain.mjs / import-toe.mjs (one format, one code path).
 *
 * Also applies the ONTOLOGY layer from knowledge/ontology/ (the R3 verb registry
 * + moderated typed edges) — see the block near the end of this file for why it
 * is an additive upsert while the canonical layer is wipe-then-insert.
 *
 * Idempotent + version-driven: each domain file's sha256 is recorded in
 * knowledge_imports; an unchanged file is SKIPPED, a changed file re-applies
 * (reset its L1 subtree/overrides/relations, then re-insert). A blank DB has no
 * markers → everything applies. Raw-SQL rows; a CONTAINER RESTART then lets boot
 * materialise (registerExtNode → applyDescriptionOverride → rebuildFts →
 * ensureLayout APPEND — U1 layout of existing stars never re-bakes).
 *
 * Runs IN the container (libSQL driver — NEVER host sqlite3). Read-only on the
 * DB under --dry-run.
 *
 *   node knowledge/ingest.mjs [--dry-run] [--force] [--canonical <dir>]
 *   env: KEAP_DATA_DIR (default /app/data), CANONICAL_DIR
 *
 * Emits a machine-readable trailer line `INGEST_RESULT {json}` the role reads to
 * decide whether to restart (changed:true).
 */
import Database from 'libsql';
import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import {
  ONTOLOGY_DIR, RELATIONS_SUBDIR, TYPES_FILE,
  VALID_KINDS, VALID_SOURCES, VALID_STATUS,
  relationId, relationKey,
} from './_ontology.mjs';

const __dir = path.dirname(fileURLToPath(import.meta.url));
const DATA_DIR = process.env.KEAP_DATA_DIR ?? '/app/data';
const CANON = process.argv.includes('--canonical')
  ? process.argv[process.argv.indexOf('--canonical') + 1]
  : (process.env.CANONICAL_DIR ?? path.join(__dir, 'canonical'));
// The ontology layer follows --canonical, so a caller pointing at a fixture
// tree gets THAT tree's ontology rather than the repo's. Two layouts are legal
// and both occur in practice: in the repo, ontology/ is a SIBLING of canonical/
// (knowledge/canonical + knowledge/ontology); in a dump, OUT_DIR is shaped like
// the knowledge root, so the domain dirs and ontology/ sit side by side inside
// it and --canonical points AT that root. Probe for the nested form first —
// getting this wrong means silently ingesting the wrong tree's ontology, or
// none at all.
const ONTOLOGY = process.env.ONTOLOGY_DIR
  ?? (existsSync(path.join(CANON, ONTOLOGY_DIR))
    ? path.join(CANON, ONTOLOGY_DIR)
    : path.join(path.dirname(CANON), ONTOLOGY_DIR));
const DRY = process.argv.includes('--dry-run');
const FORCE = process.argv.includes('--force');
const DB_PATH = path.join(DATA_DIR, 'keap.db');

// ── discover domain files (recursively; skip manifest.json) ─────────────────
function walk(dir) {
  const out = [];
  for (const e of readdirSync(dir)) {
    const p = path.join(dir, e);
    // ontology/ is never a taxonomy domain directory. A dump writes it inside
    // OUT_DIR, and re-ingesting a dumped tree would otherwise read
    // relation-types.json as a domain document and die on its missing `nodes`.
    if (e === ONTOLOGY_DIR) continue;
    if (statSync(p).isDirectory()) out.push(...walk(p));
    else if (e.endsWith('.json') && e !== 'manifest.json') out.push(p);
  }
  return out;
}
const files = walk(CANON).sort();

// Dry-run must survive a missing DB file (the CI gate runs on a bare runner):
// no DB simply means "blank system — every domain file would apply".
const db = DRY && !existsSync(DB_PATH) ? null : new Database(DB_PATH, DRY ? { readonly: true } : {});
if (!DRY) db.exec('PRAGMA journal_mode=WAL');
// Marker + relation tables (ship in server/db.ts SCHEMA; guard for a pre-boot DB).
if (!DRY) {
  db.exec(`CREATE TABLE IF NOT EXISTS knowledge_imports (import_key TEXT PRIMARY KEY, source_sha TEXT NOT NULL, n_nodes INTEGER NOT NULL DEFAULT 0, n_relations INTEGER NOT NULL DEFAULT 0, applied_at TEXT NOT NULL)`);
  db.exec(`CREATE TABLE IF NOT EXISTS concept_relations (from_id TEXT NOT NULL, to_id TEXT NOT NULL, type TEXT NOT NULL, explored TEXT, source TEXT DEFAULT 'toe', PRIMARY KEY (from_id, to_id, type))`);
  // R3 ontology store — shape-identical to migration 006 (server/migrations.ts).
  // Guarded the same way the tables above are: ingest may run against a DB the
  // server has never booted (a fresh volume on a converge), and the alternative
  // is an ontology layer that silently no-ops on exactly the blank it exists to
  // repair.
  db.exec(`CREATE TABLE IF NOT EXISTS relations (
    id TEXT PRIMARY KEY, from_ref TEXT NOT NULL, to_ref TEXT NOT NULL,
    from_kind TEXT NOT NULL DEFAULT 'node', to_kind TEXT NOT NULL DEFAULT 'node',
    type TEXT NOT NULL, confidence REAL, justification TEXT,
    source TEXT NOT NULL DEFAULT 'derived', status TEXT NOT NULL DEFAULT 'proposed',
    model TEXT, created_at INTEGER, UNIQUE (from_ref, to_ref, type))`);
  db.exec(`CREATE TABLE IF NOT EXISTS relation_types (
    type TEXT PRIMARY KEY, label TEXT NOT NULL, color TEXT, description TEXT,
    status TEXT NOT NULL DEFAULT 'seed', created_at INTEGER)`);
}
const markerOf = (key) => {
  if (!db) return null; // dry-run without a DB — nothing applied yet
  try { return (db.prepare('SELECT source_sha FROM knowledge_imports WHERE import_key = ?').get(key) || {}).source_sha ?? null; }
  catch { return null; } // table may not exist yet under --dry-run on a fresh DB
};

const ACTOR = 'agent:knowledge-ingest';
const insNode = DRY ? null : db.prepare(`INSERT INTO taxonomy_nodes_ext (id, parent_id, name, description, zone, ordinal, proposed_by, approved_by, created_at) VALUES (?, ?, ?, ?, ?, ?, '${ACTOR}', '${ACTOR}', ?)`);
const insDesc = DRY ? null : db.prepare(`INSERT INTO node_descriptions (node_id, description_en, description_cs, proposed_by, approved_by) VALUES (?, ?, ?, '${ACTOR}', '${ACTOR}') ON CONFLICT(node_id) DO UPDATE SET description_en = excluded.description_en, description_cs = excluded.description_cs`);
const insMeta = DRY ? null : db.prepare(`INSERT INTO taxonomy_metadata (id, data, updated_by) VALUES (?, ?, '${ACTOR}') ON CONFLICT(id) DO UPDATE SET data = excluded.data`);
const insRel = DRY ? null : db.prepare(`INSERT INTO concept_relations (from_id, to_id, type, explored, source) VALUES (?, ?, ?, ?, ?) ON CONFLICT(from_id, to_id, type) DO UPDATE SET explored = excluded.explored`);
const insMarker = DRY ? null : db.prepare(`INSERT INTO knowledge_imports (import_key, source_sha, n_nodes, n_relations, applied_at) VALUES (?, ?, ?, ?, ?) ON CONFLICT(import_key) DO UPDATE SET source_sha = excluded.source_sha, n_nodes = excluded.n_nodes, n_relations = excluded.n_relations, applied_at = excluded.applied_at`);

let clock = Math.floor(Date.now() / 1000);
const tick = () => clock++;

// The domain key is interpolated into the wipe-scope SQL below. Lint validates
// it too, but ingest is the WRITE — a key like "nos' OR '1'='1" would widen the
// DELETE to every grown domain, so the write validates for itself.
const KEY_RE = /^(?:\d{2}(?:\.\d{2})*|[a-z][a-z0-9-]*(?:\.[a-z][a-z0-9-]*)*)$/;

function applyDomain(key, doc) {
  if (!KEY_RE.test(key)) throw new Error(`malformed domain key ${JSON.stringify(key)} — refusing to build a wipe scope from it`);
  // Reset scope = exactly the nodes this file OWNS (dump groups by l1(id), so a
  // file owns every id whose first two segments == key). An L1 key ("01.01")
  // owns its whole subtree (id = key OR id LIKE 'key.%'). An L0 key ("01", no
  // dot) owns ONLY itself — its subtree belongs to the L1 files ("01.01" …), so
  // a prefix wipe there would delete sibling files' just-inserted content.
  const self = `'${key}'`, sub = `'${key}.%'`;
  const hasDot = key.includes('.');
  const idC = hasDot ? `id = ${self} OR id LIKE ${sub}` : `id = ${self}`;
  // Identity drift detector. A producer that derives ids from sort position
  // renumbers siblings on every insert, and the result is NOT a dangling anchor:
  // every card still resolves — to the WRONG node. Nothing downstream can see
  // that (fs-sync's danglingAnchors reports zero, the constellation looks
  // healthy), because a valid-but-wrong id is indistinguishable from a correct
  // one after the fact. The only moment the evidence exists is HERE, across the
  // delete/insert boundary, where both the old and new name for an id are known.
  const priorNames = new Map(
    db.prepare(`SELECT id, name FROM taxonomy_nodes_ext WHERE ${idC}`).all().map((r) => [r.id, r.name]),
  );
  const ndC = hasDot ? `node_id = ${self} OR node_id LIKE ${sub}` : `node_id = ${self}`;
  const frC = hasDot ? `from_id = ${self} OR from_id LIKE ${sub}` : `from_id = ${self}`;
  let nRel = 0;
  // insert nodes parent-first (id-sorted → a parent id is a prefix of its children)
  const nodes = [...doc.nodes].sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
  // A domain is rewritten as WIPE-then-INSERT. Those were four bare db.exec calls
  // with the inserts loose after them, so a failure anywhere between left the
  // domain DELETED: the tree is rebuilt from this table at boot, so every node in
  // it would vanish and every card anchored to one would go invisible — a torn
  // ingest is not a window that closes, it is a hole that persists until the next
  // successful run. One transaction makes the rewrite all-or-nothing.
  const applyTxn = db.transaction(() => {
    db.exec(`DELETE FROM taxonomy_nodes_ext WHERE ${idC}`);
    db.exec(`DELETE FROM node_descriptions  WHERE ${ndC}`);
    db.exec(`DELETE FROM taxonomy_metadata  WHERE ${idC}`);
    db.exec(`DELETE FROM concept_relations  WHERE ${frC}`);
    for (const n of nodes) {
      // descriptions are the SoT — store VERBATIM (TEXT columns, no length cap);
      // clipping/normalising here would break the dump↔ingest round-trip identity.
      const en = n.en ?? '';
      const cs = n.cs ?? null;
      if (n.kind === 'ext') {
        // A root has no parent; the column is NOT NULL, so '' is the sentinel
        // (the same one registerExtNode reads as "this is a root").
        insNode.run(n.id, n.parentId ?? '', n.name, en, n.zone || 'votable', n.ordinal ?? 0, tick());
      }
      insDesc.run(n.id, en, cs);
      if (n.brief) insMeta.run(n.id, JSON.stringify({ brief: n.brief, briefMeta: { source: 'knowledge', domain: key } }));
    }
    for (const r of doc.relations || []) {
      insRel.run(r.from, r.to, r.type, r.explored ?? null, r.source || 'knowledge');
      nRel++;
    }
  });
  // An id that kept its slot but changed its name is either a deliberate rename
  // (rare, usually one) or a renumbering (many at once). Reporting the count and
  // a sample lets the caller tell them apart; a gate can fail on a threshold.
  const renamed = [];
  for (const n of nodes) {
    if (n.kind !== 'ext') continue;
    const was = priorNames.get(n.id);
    if (was !== undefined && was !== n.name) renamed.push({ id: n.id, was, now: n.name });
  }
  applyTxn();
  return { nNodes: nodes.length, nRel, renamed };
}

const applied = [], skipped = [], reidentified = [];
for (const f of files) {
  const bytes = readFileSync(f);
  const sha = createHash('sha256').update(bytes).digest('hex');
  const doc = JSON.parse(bytes.toString('utf8'));
  const key = doc.domain || path.basename(f, '.json');
  const unchanged = !FORCE && markerOf(key) === sha;
  if (unchanged) { skipped.push(key); continue; }
  if (DRY) { applied.push(key); console.log(`would apply ${key} (${doc.nodes.length} nodes, ${(doc.relations || []).length} rel)`); continue; }
  const { nNodes, nRel, renamed } = applyDomain(key, doc);
  insMarker.run(key, sha, nNodes, nRel, new Date(clock * 1000).toISOString());
  applied.push(key);
  console.log(`applied ${key}: ${nNodes} nodes, ${nRel} relations`);
  if (renamed.length) {
    reidentified.push(...renamed);
    console.warn(
      `  ⚠ ${renamed.length} id(s) kept their slot but changed name — every card anchored to them now points ` +
        `at a DIFFERENT node, and nothing downstream can detect that:\n` +
        renamed.slice(0, 5).map((r) => `      ${r.id}: "${r.was}" → "${r.now}"`).join('\n'),
    );
  }
}

// Stale-domain sweep (slug trees only): a canonical FILE that disappears or is
// renamed leaves its rows and marker behind — the subtree keeps registering at
// boot (its root still resolves), the drift detector sees nothing (wrong key
// scope), and the next dump resurrects the deleted file. Prune a stale slug
// domain ONLY when its ROOT is part of this run's file set — that is the signal
// that this run intends to define that root's whole tree; a subset run that
// does not carry the root leaves other domains untouched. Numeric seed domains
// are exempt: their lifecycle is the repo's, not a generator's.
const prunedDomains = [];
if (db && !DRY) {
  const fileKeys = new Set([...applied, ...skipped]);
  const rootsPresent = new Set([...fileKeys].filter((k) => /^[a-z][a-z0-9-]*$/.test(k)));
  const markers = db.prepare(`SELECT import_key FROM knowledge_imports`).all().map((r) => r.import_key);
  for (const key of markers) {
    if (fileKeys.has(key)) continue;
    if (!/^[a-z]/.test(key)) continue; // numeric spine: never swept
    const root = key.split('.')[0];
    if (!rootsPresent.has(root)) continue;
    const sub = `'${key}.%'`, self = `'${key}'`;
    const idC = key.includes('.') ? `id = ${self} OR id LIKE ${sub}` : `id = ${self}`;
    const ndC = key.includes('.') ? `node_id = ${self} OR node_id LIKE ${sub}` : `node_id = ${self}`;
    const frC = key.includes('.') ? `from_id = ${self} OR from_id LIKE ${sub}` : `from_id = ${self}`;
    const tx = db.transaction(() => {
      db.exec(`DELETE FROM taxonomy_nodes_ext WHERE ${idC}`);
      db.exec(`DELETE FROM node_descriptions  WHERE ${ndC}`);
      db.exec(`DELETE FROM taxonomy_metadata  WHERE ${idC}`);
      db.exec(`DELETE FROM concept_relations  WHERE ${frC}`);
      db.prepare(`DELETE FROM knowledge_imports WHERE import_key = ?`).run(key);
    });
    tx();
    prunedDomains.push(key);
    console.warn(`⚠ pruned stale domain '${key}' — its canonical file is gone and its root '${root}' is defined by this run`);
  }
}

// ── ontology layer (R3: the verb registry + moderated typed edges) ──────────
// Semantics differ DELIBERATELY from the canonical layer above. A domain file
// owns its subtree outright and is applied wipe-then-insert, because canonical/
// is the only writer. `relations` has TWO writers: this importer and the live
// agent surface (the host-side classifier proposes; admins moderate). A
// wipe-then-insert here would delete every edge proposed since the last dump —
// so the ontology is applied as a pure ADDITIVE UPSERT that never deletes.
//
// Nothing is lost by that: derived edges are never hard-deleted anywhere in the
// system (the only DELETE on `relations` is the ToE mirror rebuild, scoped to
// source='toe'). Removal is expressed as status='rejected', which IS carried in
// the files — and a rejected row restored from git also stops the classifier
// re-proposing that pair after a rebuild, which a mere absence would not.
const ontology = { types: 0, relations: 0, files: [], skipped: [], unknownVerbs: [], statusConflicts: [], malformed: [] };
if (existsSync(ONTOLOGY)) {
  const typesPath = path.join(ONTOLOGY, TYPES_FILE);
  // Verbs FIRST: a relation on a verb the registry does not carry would bypass
  // the vocabulary gate the moderation layer enforces (v1.16), so the registry
  // has to be in place before any edge is validated against it.
  if (existsSync(typesPath)) {
    const bytes = readFileSync(typesPath);
    const sha = createHash('sha256').update(bytes).digest('hex');
    const doc = JSON.parse(bytes.toString('utf8'));
    const list = doc.types || [];
    if (!FORCE && markerOf('ontology:types') === sha) {
      ontology.skipped.push('types');
    } else if (DRY) {
      console.log(`would apply ontology:types (${list.length} verbs)`);
      ontology.files.push('types');
    } else {
      const ins = db.prepare(
        `INSERT INTO relation_types (type, label, color, description, status, created_at)
         VALUES (?, ?, ?, ?, ?, ?)
         ON CONFLICT(type) DO UPDATE SET
           label = excluded.label, color = excluded.color,
           description = excluded.description, status = excluded.status`,
      );
      const tx = db.transaction(() => {
        for (const t of list) ins.run(t.type, t.label ?? t.type, t.color ?? null, t.description ?? null, t.status ?? 'seed', tick());
      });
      tx();
      insMarker.run('ontology:types', sha, list.length, 0, new Date(clock * 1000).toISOString());
      ontology.types = list.length;
      ontology.files.push('types');
      console.log(`applied ontology:types: ${list.length} verbs`);
    }
  }

  const relDir = path.join(ONTOLOGY, RELATIONS_SUBDIR);
  const relFiles = existsSync(relDir) ? readdirSync(relDir).filter((f) => f.endsWith('.json')).sort() : [];
  // Validate against the registry as it stands AFTER the types file applied.
  // A pre-006 DB has no registry table; under --dry-run the CREATE guards above
  // are skipped, so read defensively rather than failing the dry run on a
  // schema that a real run would have created for itself.
  let knownVerbs = new Set();
  try { knownVerbs = new Set(db.prepare('SELECT type FROM relation_types').all().map((r) => r.type)); } catch { /* pre-006 / no DB */ }
  const insOntRel = DRY ? null : db.prepare(
    `INSERT INTO relations (id, from_ref, to_ref, from_kind, to_kind, type, confidence, justification, source, status, model, created_at)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
     ON CONFLICT(from_ref, to_ref, type) DO UPDATE SET
       from_kind = excluded.from_kind, to_kind = excluded.to_kind,
       confidence = excluded.confidence, justification = excluded.justification,
       source = excluded.source, status = excluded.status, model = excluded.model,
       created_at = excluded.created_at`,
  );
  const statusOf = DRY ? null : db.prepare('SELECT status FROM relations WHERE from_ref = ? AND to_ref = ? AND type = ?');

  for (const f of relFiles) {
    const full = path.join(relDir, f);
    const bytes = readFileSync(full);
    const sha = createHash('sha256').update(bytes).digest('hex');
    const doc = JSON.parse(bytes.toString('utf8'));
    const key = `ontology:relations:${doc.partition || path.basename(f, '.json')}`;
    if (!FORCE && markerOf(key) === sha) { ontology.skipped.push(key); continue; }
    const rows = doc.relations || [];
    if (DRY) { console.log(`would apply ${key} (${rows.length} relations)`); ontology.files.push(key); continue; }

    const accepted = [];
    for (const r of rows) {
      // A malformed row is REPORTED, never silently dropped: a relation that
      // vanishes between git and the graph is invisible downstream — the edge
      // simply isn't drawn, which looks exactly like "the classifier found
      // nothing" rather than like a broken import.
      const why =
        !r.from || !r.to || !r.type ? 'missing from/to/type'
        : !VALID_KINDS.has(r.fromKind ?? 'node') || !VALID_KINDS.has(r.toKind ?? 'node') ? 'bad kind'
        : !VALID_STATUS.has(r.status ?? 'proposed') ? 'bad status'
        : !VALID_SOURCES.has(r.source ?? 'derived') ? `bad source (toe rows belong to canonical/, not here)`
        : r.confidence != null && (typeof r.confidence !== 'number' || r.confidence < 0 || r.confidence > 1) ? 'confidence out of 0..1'
        : null;
      if (why) { ontology.malformed.push({ file: f, key: relationKey(r), why }); continue; }
      if (!knownVerbs.has(r.type)) { ontology.unknownVerbs.push({ file: f, key: relationKey(r), type: r.type }); continue; }
      const prior = statusOf.get(r.from, r.to, r.type);
      // Git is the moderation record, so the file wins — but a live verdict
      // being overwritten is exactly the kind of change that must not happen
      // quietly, so every downgrade is named in the result trailer.
      if (prior && prior.status !== (r.status ?? 'proposed') && (prior.status === 'confirmed' || prior.status === 'rejected')) {
        ontology.statusConflicts.push({ key: relationKey(r), live: prior.status, file: r.status ?? 'proposed' });
      }
      accepted.push(r);
    }
    const tx = db.transaction(() => {
      for (const r of accepted) {
        const fromKind = r.fromKind ?? 'node', toKind = r.toKind ?? 'node';
        insOntRel.run(
          relationId(r.from, r.to, r.type, createHash), r.from, r.to, fromKind, toKind, r.type,
          r.confidence ?? null, r.justification ?? null, r.source ?? 'derived',
          r.status ?? 'proposed', r.model ?? null, r.createdAt ?? tick(),
        );
      }
    });
    tx();
    insMarker.run(key, sha, 0, accepted.length, new Date(clock * 1000).toISOString());
    ontology.relations += accepted.length;
    ontology.files.push(key);
    console.log(`applied ${key}: ${accepted.length} relations`);
  }

  if (ontology.unknownVerbs.length) {
    console.warn(
      `  ⚠ ${ontology.unknownVerbs.length} relation(s) reference a verb absent from the registry and were NOT imported — ` +
        `the vocabulary gate would reject them live too:\n` +
        ontology.unknownVerbs.slice(0, 5).map((u) => `      ${u.key} (${u.type})`).join('\n'),
    );
  }
  if (ontology.malformed.length) {
    console.warn(
      `  ⚠ ${ontology.malformed.length} malformed relation row(s) skipped:\n` +
        ontology.malformed.slice(0, 5).map((m) => `      ${m.key}: ${m.why}`).join('\n'),
    );
  }
  if (ontology.statusConflicts.length) {
    console.warn(
      `  ⚠ ${ontology.statusConflicts.length} live moderation verdict(s) overwritten by the versioned file — ` +
        `dump before editing, or the file re-applies a stale verdict:\n` +
        ontology.statusConflicts.slice(0, 5).map((c) => `      ${c.key}: live=${c.live} → file=${c.file}`).join('\n'),
    );
  }
} else {
  console.log(`ontology: no ${ONTOLOGY} — layer skipped`);
}

const changed = applied.length > 0 || prunedDomains.length > 0 || ontology.files.length > 0;
console.log(`${DRY ? '[dry-run] ' : ''}${applied.length} applied, ${skipped.length} skipped${DRY && changed ? ' — RESTART would follow' : changed ? ' — RESTART to materialize' : ''}`);
console.log(`INGEST_RESULT ${JSON.stringify({ applied, skipped, changed, dryRun: DRY, reidentified, prunedDomains, ontology })}`);
db?.close();
