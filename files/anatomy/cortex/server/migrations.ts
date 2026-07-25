import Database from 'libsql';

interface Migration {
  id: string;
  sql: string;
}

const MIGRATIONS: Migration[] = [
  {
    id: '001-extension-foundation',
    sql: `
      CREATE TABLE IF NOT EXISTS extension_pairings (
        id TEXT PRIMARY KEY,
        user_code TEXT NOT NULL UNIQUE,
        device_secret_hash TEXT NOT NULL,
        client_name TEXT NOT NULL,
        requested_scopes TEXT NOT NULL,
        approved_scopes TEXT,
        user_id TEXT,
        username TEXT,
        name TEXT,
        email TEXT,
        status TEXT NOT NULL DEFAULT 'pending',
        expires_at INTEGER NOT NULL,
        approved_at INTEGER,
        created_at INTEGER DEFAULT (strftime('%s','now'))
      );
      CREATE INDEX IF NOT EXISTS extension_pairings_expires_idx ON extension_pairings(expires_at);

      CREATE TABLE IF NOT EXISTS extension_credentials (
        id TEXT PRIMARY KEY,
        token_hash TEXT NOT NULL UNIQUE,
        user_id TEXT NOT NULL,
        username TEXT NOT NULL,
        name TEXT,
        email TEXT,
        client_name TEXT NOT NULL,
        scopes TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'active',
        expires_at INTEGER NOT NULL,
        last_used_at INTEGER,
        revoked_at INTEGER,
        created_at INTEGER DEFAULT (strftime('%s','now'))
      );
      CREATE INDEX IF NOT EXISTS extension_credentials_user_idx ON extension_credentials(user_id, status);

      CREATE TABLE IF NOT EXISTS extension_drafts (
        id TEXT PRIMARY KEY,
        credential_id TEXT NOT NULL,
        owner_id TEXT NOT NULL,
        kind TEXT NOT NULL,
        payload TEXT NOT NULL,
        expires_at INTEGER NOT NULL,
        consumed_at INTEGER,
        created_at INTEGER DEFAULT (strftime('%s','now')),
        updated_at INTEGER DEFAULT (strftime('%s','now'))
      );
      CREATE INDEX IF NOT EXISTS extension_drafts_owner_idx ON extension_drafts(owner_id, expires_at);

      CREATE TABLE IF NOT EXISTS object_type_definitions (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        name TEXT NOT NULL,
        description TEXT,
        schema_json TEXT NOT NULL DEFAULT '{}',
        ui_json TEXT NOT NULL DEFAULT '{}',
        connector_key TEXT,
        target_ref TEXT,
        version INTEGER NOT NULL DEFAULT 1,
        status TEXT NOT NULL DEFAULT 'active',
        created_at INTEGER DEFAULT (strftime('%s','now')),
        updated_at INTEGER DEFAULT (strftime('%s','now'))
      );
      CREATE INDEX IF NOT EXISTS object_type_definitions_user_idx ON object_type_definitions(user_id, status);

      CREATE TABLE IF NOT EXISTS extension_audit_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        credential_id TEXT,
        user_id TEXT,
        action TEXT NOT NULL,
        resource_kind TEXT,
        resource_id TEXT,
        detail TEXT,
        created_at INTEGER DEFAULT (strftime('%s','now'))
      );
      CREATE INDEX IF NOT EXISTS extension_audit_user_idx ON extension_audit_events(user_id, created_at);
    `,
  },
  {
    // Data tables (Track R2′): registry + rows + append-only history for the
    // libsql driver. Rows are one JSON blob per row — the schema lives in the
    // registry (shared/contracts/table.ts), aggregation reads via
    // json_extract. Other drivers (rustfs/postgres/grist) keep their data
    // elsewhere and only register here.
    id: '002-data-tables',
    sql: `
      CREATE TABLE IF NOT EXISTS data_tables (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        title TEXT NOT NULL,
        description TEXT,
        driver TEXT NOT NULL DEFAULT 'libsql',
        schema_json TEXT NOT NULL,
        visibility TEXT NOT NULL DEFAULT 'private',
        row_count INTEGER NOT NULL DEFAULT 0,
        created_at INTEGER DEFAULT (strftime('%s','now')),
        updated_at INTEGER DEFAULT (strftime('%s','now'))
      );
      CREATE INDEX IF NOT EXISTS data_tables_user_idx ON data_tables(user_id);

      CREATE TABLE IF NOT EXISTS table_rows (
        table_id TEXT NOT NULL,
        row_id TEXT NOT NULL,
        data TEXT NOT NULL,
        created_at INTEGER DEFAULT (strftime('%s','now')),
        updated_at INTEGER DEFAULT (strftime('%s','now')),
        updated_by TEXT NOT NULL,
        PRIMARY KEY (table_id, row_id)
      );

      CREATE TABLE IF NOT EXISTS table_row_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        table_id TEXT NOT NULL,
        row_id TEXT NOT NULL,
        op TEXT NOT NULL,
        data TEXT,
        actor TEXT NOT NULL,
        at INTEGER DEFAULT (strftime('%s','now'))
      );
      CREATE INDEX IF NOT EXISTS table_row_history_idx ON table_row_history(table_id, row_id, at);
    `,
  },
  {
    // The K1/brief dup-guards read open proposals through listPromotions'
    // default LIMIT 200 — beyond 200 open rows the guard went blind and
    // re-proposals landed as duplicate rows instead of superseding. The
    // guards now read uncapped (db.openPromotions); this clears the rows
    // the blind window let in, keeping the newest proposal per node.
    id: '003-dedupe-open-desc-brief-promotions',
    sql: `
      DELETE FROM promotions WHERE status = 'proposed' AND kind IN ('desc','brief') AND id NOT IN (
        SELECT id FROM (
          SELECT id, ROW_NUMBER() OVER (
            PARTITION BY kind, json_extract(object_json, '$.nodeId')
            ORDER BY created_at DESC, id DESC
          ) AS rn
          FROM promotions WHERE status = 'proposed' AND kind IN ('desc','brief')
        ) WHERE rn = 1
      );
    `,
  },
  {
    // Mapped folders (admin-managed read-only mirrors): each row maps a
    // directory inside a KEAP_FS_ROOTS mount onto a mirrored object set in
    // knowledge_objects (owner 'fsmap:<id>', object ids 'fsm:…'). CRUD lives
    // in server/db.ts, the walk in server/fs-sync.ts, the roots registry in
    // server/fs-roots.ts.
    id: '004-fs-mappings',
    sql: `
      CREATE TABLE IF NOT EXISTS fs_mappings (
        id               TEXT PRIMARY KEY,              -- 'm-'+8 hex, server-minted, immutable
        root_key         TEXT NOT NULL,                 -- key into KEAP_FS_ROOTS
        rel_path         TEXT NOT NULL DEFAULT '',      -- '/'-separated inside the root; '' = whole root
        label            TEXT NOT NULL,                 -- popisek; constellation hub name
        description      TEXT,
        nest_under_files INTEGER NOT NULL DEFAULT 1,    -- 1 = under central Files core, 0 = standalone
        schema_json      TEXT NOT NULL DEFAULT '{}',    -- {"type"?:string,"frontmatter"?:object}
        tags             TEXT NOT NULL DEFAULT '[]',    -- JSON string[]
        taxonomy_root    TEXT,                          -- primary anchor node id
        taxonomy_links   TEXT NOT NULL DEFAULT '[]',    -- JSON string[] of extra node ids
        visibility       TEXT NOT NULL DEFAULT 'shared',-- 'shared'|'private', copied to objects
        enabled          INTEGER NOT NULL DEFAULT 1,    -- 0 = paused: no sync, objects retained
        created_by       TEXT NOT NULL,                 -- admin uid (audit)
        last_sync_at     INTEGER,
        last_sync_json   TEXT,                          -- last FsMappingSyncResult (status survives restarts)
        created_at       INTEGER DEFAULT (strftime('%s','now')),
        updated_at       INTEGER DEFAULT (strftime('%s','now'))
      );
      CREATE UNIQUE INDEX IF NOT EXISTS fs_mappings_root_path_idx ON fs_mappings(root_key, rel_path);
      -- knowledge_objects has NO user_id index before this migration; the
      -- owner-scoped count/delete/sync-index queries (db.ts) need it.
      CREATE INDEX IF NOT EXISTS knowledge_objects_user_idx ON knowledge_objects(user_id);
    `,
  },
  {
    // Topics mode: server-side spherical k-means over stored kind='object'
    // vectors with sticky identities. Centroids are plain JSON text on
    // purpose (decision #16) — this migration runs before/independently of the
    // libSQL vector layer (db.ts VECTOR_SCHEMA try/catch), so persisted topics
    // stay readable and render frozen even when vectorsOk=false. The clustering
    // pipeline lives in server/topics.ts + server/topics-math.ts; readers/
    // writers in server/db.ts. A topic id, once minted, never changes meaning,
    // position, or membership without a measured cause (warm-start identity,
    // assignment hysteresis, birth-frozen θ).
    id: '005-topic-clusters',
    sql: `
      CREATE TABLE IF NOT EXISTS topic_clusters (
        id            TEXT PRIMARY KEY,             -- 't-'+8 hex, server-minted, IMMUTABLE (keys client geometry)
        label         TEXT NOT NULL,
        label_auto    TEXT NOT NULL,
        label_locked  INTEGER NOT NULL DEFAULT 0,   -- 1 = admin-renamed; auto never overwrites
        terms_json    TEXT NOT NULL DEFAULT '[]',   -- JSON string[] top-8 c-TF-IDF terms (panel chips)
        churn_accum   REAL NOT NULL DEFAULT 0,      -- cumulative membership churn since last label promotion
        centroid_json TEXT NOT NULL,                -- JSON number[768], unit-normalized (warm-start seed)
        theta         REAL NOT NULL,                -- ring angle, frozen at birth; changes ONLY via admin reanchor/reset
        model         TEXT NOT NULL,                -- embedding model of the vector space
        member_count  INTEGER NOT NULL DEFAULT 0,   -- corpus-global (server bookkeeping; payload counts are per-viewer)
        empty_runs    INTEGER NOT NULL DEFAULT 0,
        created_at    INTEGER DEFAULT (strftime('%s','now')),
        updated_at    INTEGER DEFAULT (strftime('%s','now'))
      );
      CREATE TABLE IF NOT EXISTS topic_assignments (
        object_id  TEXT PRIMARY KEY,                -- knowledge_objects.id == embeddings.ref_id (kind='object')
        topic_id   TEXT NOT NULL,
        distance   REAL NOT NULL,                   -- cosine distance at assignment time
        updated_at INTEGER DEFAULT (strftime('%s','now'))
      );
      CREATE INDEX IF NOT EXISTS topic_assignments_topic_idx ON topic_assignments(topic_id);
      CREATE TABLE IF NOT EXISTS topic_runs (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        ran_at      INTEGER DEFAULT (strftime('%s','now')),
        model       TEXT NOT NULL,
        k           INTEGER NOT NULL,
        n           INTEGER NOT NULL,
        moved       INTEGER NOT NULL,
        params_json TEXT NOT NULL                   -- {tau, kTarget, reset?, born, retired, ms}
      );
    `,
  },
  {
    // Track R3 stage 1 — the typed cross-type relation store. `concept_relations`
    // (server/db.ts SCHEMA + knowledge/ingest.mjs) STAYS the ToE ingest target,
    // shape-frozen, so ingest's ON CONFLICT(from_id,to_id,type) and per-domain
    // prefix resets keep working untouched. This migration adds a GENERALIZED
    // store beside it: `relations` carries node↔object edges with provenance +
    // a moderation status, and `relation_types` is the growable controlled
    // vocabulary. The ToE set is MIRRORED into `relations` at boot
    // (db.syncToeRelations) as source='toe', status='confirmed' — a live mirror,
    // not a one-time copy, so a re-ingest (which rewrites concept_relations) is
    // reflected on the next start. Derived edges (source='derived') live ONLY
    // here, so ingest.mjs's reset never touches them. Pure DDL only — the seed
    // (relation_types) and the mirror (relations) are idempotent boot steps.
    id: '006-typed-relations',
    sql: `
      CREATE TABLE IF NOT EXISTS relations (
        id            TEXT PRIMARY KEY,             -- deterministic: hash(from_ref|to_ref|type)
        from_ref      TEXT NOT NULL,                -- taxonomy node id | knowledge_objects.id
        to_ref        TEXT NOT NULL,
        from_kind     TEXT NOT NULL DEFAULT 'node', -- 'node' | 'object'
        to_kind       TEXT NOT NULL DEFAULT 'node',
        type          TEXT NOT NULL,                -- relation_types.type
        confidence    REAL,                         -- 0..1 (ToE: mapped from the explored rating)
        justification TEXT,                         -- moderation rationale (derived) — the Sonnet reason
        source        TEXT NOT NULL DEFAULT 'derived', -- 'toe' | 'derived' | 'manual'
        status        TEXT NOT NULL DEFAULT 'proposed', -- 'proposed' | 'confirmed' | 'rejected'
        model         TEXT,                         -- classifier model that typed a derived edge
        created_at    INTEGER,
        UNIQUE (from_ref, to_ref, type)             -- idempotency key for upserts + dedupe
      );
      CREATE INDEX IF NOT EXISTS relations_status_idx ON relations(status);
      CREATE INDEX IF NOT EXISTS relations_from_idx   ON relations(from_ref, from_kind);
      CREATE INDEX IF NOT EXISTS relations_to_idx     ON relations(to_ref, to_kind);

      CREATE TABLE IF NOT EXISTS relation_types (
        type        TEXT PRIMARY KEY,
        label       TEXT NOT NULL,                  -- verb shown on the edge (stage-2 render)
        color       TEXT,                           -- edge hue (stage-2 render)
        description TEXT,
        status      TEXT NOT NULL DEFAULT 'seed',   -- 'seed' | 'proposed' | 'confirmed'
        created_at  INTEGER
      );
    `,
  },
];

export function runMigrations(db: Database.Database): void {
  db.exec(`CREATE TABLE IF NOT EXISTS schema_migrations (
    id TEXT PRIMARY KEY,
    applied_at INTEGER DEFAULT (strftime('%s','now'))
  )`);
  const applied = new Set(
    (db.prepare('SELECT id FROM schema_migrations').all() as Array<{ id: string }>).map((row) => row.id),
  );
  for (const migration of MIGRATIONS) {
    if (applied.has(migration.id)) continue;
    const apply = db.transaction(() => {
      db.exec(migration.sql);
      db.prepare('INSERT INTO schema_migrations (id) VALUES (?)').run(migration.id);
    });
    apply();
  }
}
