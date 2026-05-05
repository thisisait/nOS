-- AUTO-GENERATED — do not edit by hand.
-- Source: files/anatomy/wing/bin/init-db.php +
--         files/anatomy/wing/db/schema-extensions.sql +
--         files/anatomy/wing/db/gdpr-seed.sql
-- Regenerate: php files/anatomy/wing/bin/export-schema.php
-- CI drift check: .github/workflows/ci.yml — contracts-drift job.

PRAGMA foreign_keys = ON;

-- ============================================================
-- TABLES (25)
-- ============================================================

CREATE TABLE advisories (
		id          INTEGER PRIMARY KEY AUTOINCREMENT,
		filename    TEXT NOT NULL UNIQUE,
		title       TEXT,
		date        TEXT NOT NULL,
		has_critical INTEGER NOT NULL DEFAULT 0,
		has_pentest INTEGER NOT NULL DEFAULT 0,
		full_text   TEXT NOT NULL,
		scan_cycle  INTEGER,
		created_at  TEXT NOT NULL DEFAULT (datetime('now'))
	);

CREATE TABLE api_tokens (
		id          INTEGER PRIMARY KEY AUTOINCREMENT,
		token       TEXT NOT NULL UNIQUE,
		name        TEXT NOT NULL DEFAULT 'default',
		created_by  TEXT,
		created_at  TEXT NOT NULL DEFAULT (datetime('now')),
		last_used_at TEXT,
		active      INTEGER NOT NULL DEFAULT 1
	);

CREATE TABLE attack_probes (
		id          INTEGER PRIMARY KEY AUTOINCREMENT,
		cycle_mod   INTEGER NOT NULL,
		name        TEXT NOT NULL UNIQUE,
		description TEXT,
		last_run    TEXT,
		findings    INTEGER NOT NULL DEFAULT 0,
		completed   INTEGER NOT NULL DEFAULT 0
	);

CREATE TABLE coexistence_tracks (
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

CREATE TABLE component_scan_state (
		component_id        TEXT NOT NULL PRIMARY KEY REFERENCES systems(id) ON DELETE CASCADE,
		last_checked        TEXT,
		last_cve_scan       TEXT,
		last_misconfig_scan TEXT,
		last_attack_probe   TEXT,
		findings_count      INTEGER NOT NULL DEFAULT 0,
		status              TEXT NOT NULL DEFAULT 'pending'
	);

CREATE TABLE events (
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
    -- source: who wrote this event. Anatomy P1 (2026-05-05) closes the
    -- pre-A8 attribution gap noted in CLAUDE.md "Wing /events table
    -- schema mismatch" tech debt. Bone's POST handler accepted `source`
    -- in JSON but silently dropped it on insert; analysts had to guess
    -- attribution from `task` text prefixes. Common values:
    --   "callback" — Ansible callback plugin (default for playbook runs)
    --   "operator" — manual curl/API hit
    --   "agent:<name>" — A8 conductor + future agent runs (with run id)
    -- Pre-A10 this is hint-level; A10 lands `actor_id` (FK Authentik
    -- client) + `actor_action_id` (UUID) for cryptographic attribution.
    source        TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE gdpr_breaches (
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

CREATE TABLE gdpr_dsar (
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

CREATE TABLE gdpr_processing (
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

CREATE TABLE migrations_applied (
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

CREATE TABLE patches (
		id              TEXT PRIMARY KEY,
		finding_ref     TEXT,
		component_id    TEXT,
		upstream_repo   TEXT,
		description     TEXT,
		patch_file      TEXT,
		tests_added     TEXT,
		upstream_pr     TEXT,
		status          TEXT NOT NULL DEFAULT 'draft',
		created_at      TEXT NOT NULL DEFAULT (datetime('now')),
		updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
	);

CREATE TABLE patches_applied (
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

CREATE TABLE pentest_areas_planned (
		id                  INTEGER PRIMARY KEY AUTOINCREMENT,
		target_id           TEXT NOT NULL REFERENCES pentest_targets(id) ON DELETE CASCADE,
		area                TEXT NOT NULL,
		description         TEXT,
		files_of_interest   TEXT,
		methods_of_interest TEXT,
		attack_class        TEXT,
		priority            TEXT DEFAULT 'medium',
		rationale           TEXT,
		created_at          TEXT NOT NULL DEFAULT (datetime('now'))
	);

CREATE TABLE pentest_areas_tested (
		id              INTEGER PRIMARY KEY AUTOINCREMENT,
		target_id       TEXT NOT NULL REFERENCES pentest_targets(id) ON DELETE CASCADE,
		area            TEXT NOT NULL,
		date            TEXT NOT NULL DEFAULT (datetime('now')),
		technique       TEXT,
		files_reviewed  TEXT,
		result          TEXT NOT NULL CHECK (result IN ('no_findings','potential_vuln','confirmed_vuln')),
		details         TEXT,
		next_steps      TEXT,
		created_at      TEXT NOT NULL DEFAULT (datetime('now'))
	);

CREATE TABLE pentest_findings (
		id                      TEXT PRIMARY KEY,
		target_id               TEXT NOT NULL REFERENCES pentest_targets(id) ON DELETE CASCADE,
		severity                TEXT NOT NULL CHECK (severity IN ('CRITICAL','HIGH','MEDIUM','LOW')),
		title                   TEXT NOT NULL,
		description             TEXT,
		affected_versions       TEXT,
		proof_of_concept        TEXT,
		files                   TEXT,
		attack_class            TEXT,
		exploitability          TEXT,
		confidence              TEXT DEFAULT 'medium',
		disclosure_status       TEXT DEFAULT 'not_reported',
		upstream_issue          TEXT,
		patch_pr                TEXT,
		nos_mitigation    TEXT,
		remediation             TEXT,
		found_at                TEXT NOT NULL DEFAULT (datetime('now')),
		created_at              TEXT NOT NULL DEFAULT (datetime('now'))
	);

CREATE TABLE pentest_targets (
		id              TEXT PRIMARY KEY,
		component_id    TEXT NOT NULL,
		version_tested  TEXT,
		upstream_repo   TEXT,
		language        TEXT,
		attack_surface  TEXT,
		status          TEXT NOT NULL DEFAULT 'planned',
		created_at      TEXT NOT NULL DEFAULT (datetime('now')),
		updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
	);

CREATE TABLE pulse_jobs (
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

CREATE TABLE pulse_runs (
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

CREATE TABLE remediation_items (
		id                  TEXT PRIMARY KEY,
		finding_ref         TEXT,
		component_id        TEXT,
		severity            TEXT NOT NULL CHECK (severity IN ('CRITICAL','HIGH','MEDIUM','LOW')),
		current_version     TEXT,
		fix_version         TEXT,
		remediation_type    TEXT,
		remediation_detail  TEXT,
		status              TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','resolved','wontfix')),
		auto_fixable        INTEGER NOT NULL DEFAULT 0,
		source              TEXT,
		confidence          TEXT DEFAULT 'medium',
		found_at            TEXT NOT NULL DEFAULT (datetime('now')),
		resolved_at         TEXT,
		resolved_by         TEXT,
		scan_cycle          INTEGER,
		created_at          TEXT NOT NULL DEFAULT (datetime('now')),
		updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
	);

CREATE TABLE report_types (
		id              TEXT PRIMARY KEY,
		name            TEXT NOT NULL,
		api_namespace   TEXT NOT NULL UNIQUE,
		table_name      TEXT NOT NULL,
		template        TEXT,
		enabled         INTEGER NOT NULL DEFAULT 1,
		created_at      TEXT NOT NULL DEFAULT (datetime('now'))
	);

CREATE TABLE scan_config (
		id                              INTEGER PRIMARY KEY CHECK (id = 1),
		batch_size                      INTEGER NOT NULL DEFAULT 5,
		schedule                        TEXT NOT NULL DEFAULT '2x daily (06:00, 18:00)',
		strategy                        TEXT NOT NULL DEFAULT 'oldest_first',
		cve_refresh_interval_hours      INTEGER NOT NULL DEFAULT 24,
		misconfig_refresh_interval_days INTEGER NOT NULL DEFAULT 7,
		attack_probe_rotation_size      INTEGER NOT NULL DEFAULT 8,
		scanner_version                 TEXT NOT NULL DEFAULT '1.0.0',
		initialized_at                  TEXT NOT NULL DEFAULT (datetime('now')),
		last_full_scan                  TEXT,
		last_advisory_check             TEXT,
		last_remediation_applied        TEXT,
		next_batch                      TEXT
	);

CREATE TABLE scan_cycles (
		id                  INTEGER PRIMARY KEY AUTOINCREMENT,
		cycle_number        INTEGER NOT NULL UNIQUE,
		started_at          TEXT NOT NULL DEFAULT (datetime('now')),
		completed_at        TEXT,
		batch_components    TEXT,
		notes               TEXT
	);

CREATE TABLE systems (
		id              TEXT PRIMARY KEY,
		parent_id       TEXT REFERENCES systems(id) ON DELETE SET NULL,
		name            TEXT NOT NULL,
		description     TEXT,
		type            TEXT NOT NULL DEFAULT 'docker',
		category        TEXT NOT NULL DEFAULT 'service',
		stack           TEXT,
		image           TEXT,
		version         TEXT,
		version_var     TEXT,
		pinned          INTEGER NOT NULL DEFAULT 1,

		-- Network
		domain          TEXT,
		port            INTEGER,
		url             TEXT,
		network_exposed INTEGER NOT NULL DEFAULT 0,
		has_web_ui      INTEGER NOT NULL DEFAULT 0,

		-- Ansible integration
		toggle_var      TEXT,
		enabled         INTEGER NOT NULL DEFAULT 1,

		-- Security & scanning
		priority        TEXT NOT NULL DEFAULT 'medium',
		upstream_repo   TEXT,

		-- Health (updated by probes)
		health_status   TEXT NOT NULL DEFAULT 'unknown',
		health_http_code INTEGER,
		health_ms       INTEGER,
		health_checked_at TEXT,

		-- Provenance
		source          TEXT NOT NULL DEFAULT 'manual',

		created_at      TEXT NOT NULL DEFAULT (datetime('now')),
		updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
	);

CREATE TABLE upgrades_applied (
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

CREATE TABLE users (
		id              INTEGER PRIMARY KEY AUTOINCREMENT,
		username        TEXT NOT NULL UNIQUE,
		email           TEXT,
		display_name    TEXT,
		groups          TEXT,
		last_login      TEXT,
		created_at      TEXT NOT NULL DEFAULT (datetime('now'))
	);

-- ============================================================
-- VIEWS (1)
-- ============================================================

CREATE VIEW components AS
		SELECT id, name, category, stack, image, version_var,
			   version AS default_version, pinned, network_exposed, has_web_ui,
			   priority, upstream_repo, port, domain, created_at, updated_at
		FROM systems;

-- ============================================================
-- INDEXS (33)
-- ============================================================

CREATE INDEX idx_adv_date ON advisories(date);

CREATE INDEX idx_coexist_active  ON coexistence_tracks(active);

CREATE INDEX idx_coexist_service ON coexistence_tracks(service);

CREATE INDEX idx_events_migration ON events(migration_id);

CREATE INDEX idx_events_patch     ON events(patch_id);

CREATE INDEX idx_events_run_id    ON events(run_id);

CREATE INDEX idx_events_source    ON events(source);

CREATE INDEX idx_events_ts        ON events(ts);

CREATE INDEX idx_events_type      ON events(type);

CREATE INDEX idx_events_upgrade   ON events(upgrade_id);

CREATE INDEX idx_gdpr_dsar_email  ON gdpr_dsar(subject_email);

CREATE INDEX idx_gdpr_dsar_status ON gdpr_dsar(status);

CREATE INDEX idx_migrations_applied_at ON migrations_applied(applied_at);

CREATE INDEX idx_migrations_severity   ON migrations_applied(severity);

CREATE INDEX idx_pap_target ON pentest_areas_planned(target_id);

CREATE INDEX idx_pat_target ON pentest_areas_tested(target_id);

CREATE INDEX idx_patches_applied_at    ON patches_applied(applied_at);

CREATE INDEX idx_patches_applied_comp  ON patches_applied(component_id);

CREATE INDEX idx_patches_applied_patch ON patches_applied(patch_id);

CREATE INDEX idx_pulse_jobs_due        ON pulse_jobs(paused, next_fire_at);

CREATE INDEX idx_pulse_jobs_plugin     ON pulse_jobs(plugin_name);

CREATE INDEX idx_pulse_runs_fired_at   ON pulse_runs(fired_at);

CREATE INDEX idx_pulse_runs_job_id     ON pulse_runs(job_id);

CREATE INDEX idx_rem_component ON remediation_items(component_id);

CREATE INDEX idx_rem_severity ON remediation_items(severity);

CREATE INDEX idx_rem_status ON remediation_items(status);

CREATE INDEX idx_sys_category ON systems(category);

CREATE INDEX idx_sys_health ON systems(health_status);

CREATE INDEX idx_sys_parent ON systems(parent_id);

CREATE INDEX idx_sys_stack ON systems(stack);

CREATE INDEX idx_upgrades_applied_at ON upgrades_applied(applied_at);

CREATE INDEX idx_upgrades_service ON upgrades_applied(service);

CREATE UNIQUE INDEX uq_pulse_jobs_name ON pulse_jobs(plugin_name, job_name);

