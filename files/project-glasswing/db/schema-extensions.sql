-- Glasswing schema extensions for the nOS State & Migration Framework.
-- Applied idempotently by bin/init-db.php after the base schema. Safe to
-- re-run: all statements use CREATE ... IF NOT EXISTS.

-- Events from the Ansible callback plugin (agent 3).
CREATE TABLE IF NOT EXISTS events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts            TEXT NOT NULL,           -- ISO-8601
    run_id        TEXT NOT NULL,
    type          TEXT NOT NULL,
    playbook      TEXT,
    play          TEXT,
    task          TEXT,
    role          TEXT,
    host          TEXT,
    duration_ms   INTEGER,
    changed       INTEGER,                 -- 0/1
    result_json   TEXT,                    -- JSON blob
    migration_id  TEXT,
    upgrade_id    TEXT,
    coexist_svc   TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_events_run_id    ON events(run_id);
CREATE INDEX IF NOT EXISTS idx_events_ts        ON events(ts);
CREATE INDEX IF NOT EXISTS idx_events_type      ON events(type);
CREATE INDEX IF NOT EXISTS idx_events_migration ON events(migration_id);
CREATE INDEX IF NOT EXISTS idx_events_upgrade   ON events(upgrade_id);

-- Migration history mirror. Source of truth lives in ~/.nos/state.yml; this
-- table is a read cache populated via BoxAPI /api/state pushes.
CREATE TABLE IF NOT EXISTS migrations_applied (
    id                TEXT PRIMARY KEY,
    title             TEXT NOT NULL,
    severity          TEXT NOT NULL,
    applied_at        TEXT NOT NULL,
    success           INTEGER NOT NULL,    -- 0/1
    duration_sec      INTEGER,
    steps_applied     INTEGER,
    steps_total       INTEGER,
    rolled_back_from  TEXT,
    event_run_id      TEXT,
    raw_record_json   TEXT                  -- full migration record
);
CREATE INDEX IF NOT EXISTS idx_migrations_applied_at ON migrations_applied(applied_at);
CREATE INDEX IF NOT EXISTS idx_migrations_severity   ON migrations_applied(severity);

-- Upgrade history. Each apply/rollback produces one row.
CREATE TABLE IF NOT EXISTS upgrades_applied (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    service           TEXT NOT NULL,
    recipe_id         TEXT NOT NULL,
    from_version      TEXT,
    to_version        TEXT,
    severity          TEXT,
    applied_at        TEXT NOT NULL,
    success           INTEGER NOT NULL,
    duration_sec      INTEGER,
    rolled_back       INTEGER NOT NULL DEFAULT 0,
    event_run_id      TEXT,
    raw_record_json   TEXT
);
CREATE INDEX IF NOT EXISTS idx_upgrades_service ON upgrades_applied(service);
CREATE INDEX IF NOT EXISTS idx_upgrades_applied_at ON upgrades_applied(applied_at);

-- Coexistence tracks mirror (shape matches ~/.nos/state.yml coexistence block).
CREATE TABLE IF NOT EXISTS coexistence_tracks (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    service       TEXT NOT NULL,
    tag           TEXT NOT NULL,
    version       TEXT,
    port          INTEGER,
    data_path     TEXT,
    active        INTEGER NOT NULL DEFAULT 0,
    read_only     INTEGER NOT NULL DEFAULT 0,
    started_at    TEXT,
    cutover_at    TEXT,
    ttl_until     TEXT,
    updated_at    TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(service, tag)
);
CREATE INDEX IF NOT EXISTS idx_coexist_service ON coexistence_tracks(service);
CREATE INDEX IF NOT EXISTS idx_coexist_active  ON coexistence_tracks(active);
