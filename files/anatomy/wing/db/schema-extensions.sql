-- Wing schema extensions for the nOS State & Migration Framework.
-- Applied idempotently by bin/init-db.php after the base schema. Safe to
-- re-run: all statements use CREATE ... IF NOT EXISTS.

-- Events from the Ansible callback plugin (agent 3).
-- NOTE: for already-initialized DBs, bin/init-db.php performs an idempotent
-- ALTER TABLE ADD COLUMN sweep to add patch_id / any future typed ids.
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
    patch_id      TEXT,
    coexist_svc   TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_events_run_id    ON events(run_id);
CREATE INDEX IF NOT EXISTS idx_events_ts        ON events(ts);
CREATE INDEX IF NOT EXISTS idx_events_type      ON events(type);
CREATE INDEX IF NOT EXISTS idx_events_migration ON events(migration_id);
CREATE INDEX IF NOT EXISTS idx_events_upgrade   ON events(upgrade_id);
CREATE INDEX IF NOT EXISTS idx_events_patch     ON events(patch_id);

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

-- Patch apply history. Each apply/rollback produces one row. Mirrors
-- upgrades_applied so the UI can render a unified "maintenance timeline".
-- Source of truth is ~/.nos/state.yml patches_applied[] populated by the
-- apply-patches engine; this table is a BoxAPI-pushed read cache.
CREATE TABLE IF NOT EXISTS patches_applied (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    patch_id          TEXT NOT NULL,           -- PATCH-NNN (FK to patches.id)
    component_id      TEXT,
    finding_ref       TEXT,
    applied_at        TEXT NOT NULL,
    success           INTEGER NOT NULL,
    duration_sec      INTEGER,
    rolled_back       INTEGER NOT NULL DEFAULT 0,
    event_run_id      TEXT,
    raw_record_json   TEXT
);
CREATE INDEX IF NOT EXISTS idx_patches_applied_patch ON patches_applied(patch_id);
CREATE INDEX IF NOT EXISTS idx_patches_applied_at    ON patches_applied(applied_at);
CREATE INDEX IF NOT EXISTS idx_patches_applied_comp  ON patches_applied(component_id);

-- ── GDPR Article 30 register (Track D, 2026-04-26) ─────────────────────
-- Each row is one entry in the "register of processing activities" required
-- of EU operators by GDPR Art. 30. Wing's /gdpr UI renders these as a CSV-
-- exportable table. Authoritative seed data ships in
-- files/project-wing/db/gdpr-seed.sql; operators add custom processing
-- activities by inserting more rows.
CREATE TABLE IF NOT EXISTS gdpr_processing (
    id                  TEXT PRIMARY KEY,           -- stable slug (auth, telemetry, …)
    name                TEXT NOT NULL,              -- human-readable
    purpose             TEXT NOT NULL,              -- why we process this data
    legal_basis         TEXT NOT NULL,              -- contract | consent | legitimate-interest | …
    data_categories     TEXT NOT NULL,              -- JSON array of names
    data_subjects       TEXT NOT NULL,              -- JSON array (operators, end-users, …)
    retention_days      INTEGER,                    -- NULL = indefinite (justify in notes)
    storage_location    TEXT NOT NULL,              -- where the data physically lives
    transfers_outside_eu INTEGER NOT NULL DEFAULT 0, -- 0/1
    processors          TEXT NOT NULL DEFAULT '[]', -- JSON array of third-party processors
    security_measures   TEXT NOT NULL DEFAULT '[]', -- JSON array of mitigations
    notes               TEXT,                       -- free-form
    updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Data Subject Access Request log. CNIL inspections check that DSAR responses
-- are tracked. Each row records an incoming request and its disposition.
CREATE TABLE IF NOT EXISTS gdpr_dsar (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    received_at         TEXT NOT NULL,
    subject_email       TEXT NOT NULL,
    request_type        TEXT NOT NULL,              -- access | rectify | erase | portability | object
    status              TEXT NOT NULL,              -- received | in-progress | completed | rejected
    completed_at        TEXT,
    rejection_reason    TEXT,
    processing_ids      TEXT NOT NULL DEFAULT '[]', -- JSON array of gdpr_processing.id touched
    notes               TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_gdpr_dsar_email  ON gdpr_dsar(subject_email);
CREATE INDEX IF NOT EXISTS idx_gdpr_dsar_status ON gdpr_dsar(status);

-- Personal data breach register (GDPR Art. 33-34). Inspectors expect a log
-- even if zero entries — proves the operator considered the question.
CREATE TABLE IF NOT EXISTS gdpr_breaches (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    detected_at         TEXT NOT NULL,
    notified_supervisor_at TEXT,                    -- 72h deadline tracker
    notified_subjects_at   TEXT,                    -- when "high risk"
    nature              TEXT NOT NULL,              -- short headline
    affected_subjects   INTEGER,
    likely_consequences TEXT,
    measures_taken      TEXT,
    status              TEXT NOT NULL,              -- detected | notified | resolved | non-reportable
    notes               TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ============================================================================
-- Pulse — scheduled-job catalog + run history (Anatomy A4, 2026-05-03)
-- ============================================================================
-- pulse_jobs: registered jobs (one row per (plugin_name, job_name)).
-- Owned by plugin loader (files/anatomy/module_utils/load_plugins.py); operators
-- may pause/resume via the Wing UI without touching the playbook.
--
-- Pulse polls /api/v1/pulse_jobs/due (server computes next_fire_at from
-- schedule + jitter) — Pulse itself stays dumb about cron syntax.

CREATE TABLE IF NOT EXISTS pulse_jobs (
    id              TEXT PRIMARY KEY,                 -- e.g. "wing-base:rotate-wing-db-backup"
    plugin_name     TEXT NOT NULL,                    -- owning plugin (FK soft)
    job_name        TEXT NOT NULL,                    -- unique within plugin
    runner          TEXT NOT NULL DEFAULT 'subprocess', -- subprocess | agent (A8)
    command         TEXT NOT NULL,
    args_json       TEXT NOT NULL DEFAULT '[]',       -- JSON array
    env_json        TEXT NOT NULL DEFAULT '{}',       -- JSON map (string→string)
    schedule        TEXT NOT NULL,                    -- cron expression
    jitter_min      INTEGER NOT NULL DEFAULT 0,
    max_runtime_s   INTEGER NOT NULL DEFAULT 300,
    max_concurrent  INTEGER NOT NULL DEFAULT 1,
    paused          INTEGER NOT NULL DEFAULT 0,       -- 0/1; manual operator pause
    paused_reason   TEXT,                             -- nullable
    next_fire_at    TEXT,                             -- ISO-8601; computed Wing-side
    last_fired_at   TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
    removed_at      TEXT                              -- soft-delete (plugin removal)
);
CREATE INDEX IF NOT EXISTS idx_pulse_jobs_plugin     ON pulse_jobs(plugin_name);
CREATE INDEX IF NOT EXISTS idx_pulse_jobs_due        ON pulse_jobs(paused, next_fire_at);
CREATE UNIQUE INDEX IF NOT EXISTS uq_pulse_jobs_name ON pulse_jobs(plugin_name, job_name);

-- pulse_runs: per-execution history. Pulse POSTs run_start (creates row)
-- + run_finish (UPDATE on run_id). Audit-relevant — actor_id-tagged for
-- the per-actor identity work in §11 of the refactor doc.
CREATE TABLE IF NOT EXISTS pulse_runs (
    run_id          TEXT PRIMARY KEY,                 -- UUID4
    job_id          TEXT NOT NULL,                    -- FK soft → pulse_jobs.id
    fired_at        TEXT NOT NULL,                    -- ISO-8601
    finished_at     TEXT,                             -- nullable until finish
    exit_code       INTEGER,                          -- nullable until finish (-9 = SIGKILL/timeout, 127 = no such command)
    duration_ms     INTEGER,                          -- nullable until finish
    stdout_tail     TEXT,                             -- last 2000 chars
    stderr_tail     TEXT,
    actor_id        TEXT,                             -- Authentik client_id of pulse instance
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_pulse_runs_job_id     ON pulse_runs(job_id);
CREATE INDEX IF NOT EXISTS idx_pulse_runs_fired_at   ON pulse_runs(fired_at);
