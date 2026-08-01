<?php

declare(strict_types=1);

/**
 * Wing — Idempotent SQLite schema initialization.
 * Usage: php bin/init-db.php [--data-dir=/path/to/data]
 */

$dataDir = null;
foreach ($argv as $arg) {
	if (str_starts_with($arg, '--data-dir=')) {
		$dataDir = substr($arg, 11);
	}
}
$dataDir ??= __DIR__ . '/../data';

if (!is_dir($dataDir)) {
	mkdir($dataDir, 0755, true);
}

$dbPath = $dataDir . '/wing.db';
$isNew = !file_exists($dbPath);

$db = new SQLite3($dbPath);
$db->busyTimeout(5000); // WAL is on-file; per-conn timeout prevents 'database is locked' under concurrent writers (scout HIGH 2026-07-15)
$db->enableExceptions(true);
$db->exec('PRAGMA journal_mode = WAL');
$db->exec('PRAGMA foreign_keys = ON');

$statements = [
	// Systems — unified entity for services, components, stacks, sub-services.
	// Replaces the old `components` table with hierarchy support (parent_id),
	// health tracking, and service-registry integration.
	"CREATE TABLE IF NOT EXISTS systems (
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
		-- W6.4 (2026-06-10): probe target when it differs from the card link.
		-- Backend services (Prometheus, Loki, MariaDB, …) have no public url
		-- but DO have a loopback health endpoint; tcp://host:port = TCP-only
		-- liveness for DB-class services the HTTP probe can't reach.
		health_url      TEXT,
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
	)",
	"CREATE INDEX IF NOT EXISTS idx_sys_parent ON systems(parent_id)",
	"CREATE INDEX IF NOT EXISTS idx_sys_stack ON systems(stack)",
	"CREATE INDEX IF NOT EXISTS idx_sys_category ON systems(category)",
	"CREATE INDEX IF NOT EXISTS idx_sys_health ON systems(health_status)",

	// Backward-compat view — old code referencing `components` keeps working
	"CREATE VIEW IF NOT EXISTS components AS
		SELECT id, name, category, stack, image, version_var,
			   version AS default_version, pinned, network_exposed, has_web_ui,
			   priority, upstream_repo, port, domain, created_at, updated_at
		FROM systems",

	// Scan cycles
	"CREATE TABLE IF NOT EXISTS scan_cycles (
		id                  INTEGER PRIMARY KEY AUTOINCREMENT,
		cycle_number        INTEGER NOT NULL UNIQUE,
		started_at          TEXT NOT NULL DEFAULT (datetime('now')),
		completed_at        TEXT,
		batch_components    TEXT,
		notes               TEXT
	)",

	// Per-system scan state (FK references systems, not old components table)
	"CREATE TABLE IF NOT EXISTS component_scan_state (
		component_id        TEXT NOT NULL PRIMARY KEY REFERENCES systems(id) ON DELETE CASCADE,
		last_checked        TEXT,
		last_cve_scan       TEXT,
		last_misconfig_scan TEXT,
		last_attack_probe   TEXT,
		findings_count      INTEGER NOT NULL DEFAULT 0,
		status              TEXT NOT NULL DEFAULT 'pending'
	)",

	// Scan configuration (singleton)
	"CREATE TABLE IF NOT EXISTS scan_config (
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
	)",

	// Attack probe schedule
	"CREATE TABLE IF NOT EXISTS attack_probes (
		id          INTEGER PRIMARY KEY AUTOINCREMENT,
		cycle_mod   INTEGER NOT NULL,
		name        TEXT NOT NULL UNIQUE,
		description TEXT,
		last_run    TEXT,
		findings    INTEGER NOT NULL DEFAULT 0,
		completed   INTEGER NOT NULL DEFAULT 0
	)",

	// Remediation items
	"CREATE TABLE IF NOT EXISTS remediation_items (
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
	)",
	"CREATE INDEX IF NOT EXISTS idx_rem_status ON remediation_items(status)",
	"CREATE INDEX IF NOT EXISTS idx_rem_severity ON remediation_items(severity)",
	"CREATE INDEX IF NOT EXISTS idx_rem_component ON remediation_items(component_id)",

	// Advisories
	"CREATE TABLE IF NOT EXISTS advisories (
		id          INTEGER PRIMARY KEY AUTOINCREMENT,
		filename    TEXT NOT NULL UNIQUE,
		title       TEXT,
		date        TEXT NOT NULL,
		has_critical INTEGER NOT NULL DEFAULT 0,
		has_pentest INTEGER NOT NULL DEFAULT 0,
		full_text   TEXT NOT NULL,
		scan_cycle  INTEGER,
		created_at  TEXT NOT NULL DEFAULT (datetime('now'))
	)",
	"CREATE INDEX IF NOT EXISTS idx_adv_date ON advisories(date)",

	// Pentest targets
	"CREATE TABLE IF NOT EXISTS pentest_targets (
		id              TEXT PRIMARY KEY,
		component_id    TEXT NOT NULL,
		version_tested  TEXT,
		upstream_repo   TEXT,
		language        TEXT,
		attack_surface  TEXT,
		status          TEXT NOT NULL DEFAULT 'planned',
		-- A10 attribution (2026-05-17). Operator or inspektor agent. Filled
		-- via getActorId() in the PentestPresenter create + update paths;
		-- old rows stay NULL.
		created_by      TEXT,
		created_at      TEXT NOT NULL DEFAULT (datetime('now')),
		updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
	)",

	// Pentest areas tested
	"CREATE TABLE IF NOT EXISTS pentest_areas_tested (
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
	)",
	"CREATE INDEX IF NOT EXISTS idx_pat_target ON pentest_areas_tested(target_id)",

	// Pentest areas planned
	"CREATE TABLE IF NOT EXISTS pentest_areas_planned (
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
	)",
	"CREATE INDEX IF NOT EXISTS idx_pap_target ON pentest_areas_planned(target_id)",

	// Pentest findings
	"CREATE TABLE IF NOT EXISTS pentest_findings (
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
		-- A10 direct attribution (2026-05-17, A9.4): who discovered + who resolved.
		-- Pre-this only indirect via target_id → pentest_targets (which itself
		-- didn't carry attribution). Inspektor's runner (deferred) will write
		-- discovered_by='agent:inspektor'; operator + remediator close
		-- findings via /api/v1/pentest/findings/<id>/resolve with the bearer-
		-- token-derived actor_id (same canonical pattern as
		-- GitleaksPresenter::actionResolve post-2026-05-17 security fix).
		discovered_by           TEXT,
		resolved_at             TEXT,
		resolved_by             TEXT,
		nos_mitigation    TEXT,
		remediation             TEXT,
		found_at                TEXT NOT NULL DEFAULT (datetime('now')),
		created_at              TEXT NOT NULL DEFAULT (datetime('now'))
	)",

	// Patches
	"CREATE TABLE IF NOT EXISTS patches (
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
	)",

	// Report types (future extensibility)
	"CREATE TABLE IF NOT EXISTS report_types (
		id              TEXT PRIMARY KEY,
		name            TEXT NOT NULL,
		api_namespace   TEXT NOT NULL UNIQUE,
		table_name      TEXT NOT NULL,
		template        TEXT,
		enabled         INTEGER NOT NULL DEFAULT 1,
		created_at      TEXT NOT NULL DEFAULT (datetime('now'))
	)",

	// API tokens (for CLI/agent authentication)
	"CREATE TABLE IF NOT EXISTS api_tokens (
		id          INTEGER PRIMARY KEY AUTOINCREMENT,
		token       TEXT NOT NULL UNIQUE,
		name        TEXT NOT NULL DEFAULT 'default',
		created_by  TEXT,
		created_at  TEXT NOT NULL DEFAULT (datetime('now')),
		last_used_at TEXT,
		active      INTEGER NOT NULL DEFAULT 1
	)",

	// Users (populated from Authentik proxy auth headers)
	"CREATE TABLE IF NOT EXISTS users (
		id              INTEGER PRIMARY KEY AUTOINCREMENT,
		username        TEXT NOT NULL UNIQUE,
		email           TEXT,
		display_name    TEXT,
		groups          TEXT,
		last_login      TEXT,
		created_at      TEXT NOT NULL DEFAULT (datetime('now'))
	)",
];

foreach ($statements as $stmt) {
	$db->exec($stmt);
}

// Ensure singleton scan_config row exists
$count = $db->querySingle('SELECT COUNT(*) FROM scan_config');
if ($count === 0) {
	$db->exec('INSERT INTO scan_config (id) VALUES (1)');
}

// Apply schema extensions (State & Migration Framework tables) AND the
// GDPR Article 30 seed register (Track D, 2026-04-26). Both files are
// idempotent — schema uses CREATE TABLE IF NOT EXISTS, gdpr-seed uses
// INSERT OR IGNORE — so re-running this script never overwrites operator
// edits.
foreach ([__DIR__ . '/../db/schema-extensions.sql',
          __DIR__ . '/../db/gdpr-seed.sql'] as $sqlFile) {
	if (is_file($sqlFile)) {
		$sql = file_get_contents($sqlFile);
		if ($sql !== false && trim($sql) !== '') {
			$db->exec($sql);
		}
	}
}

/**
 * Idempotent ALTER TABLE ADD COLUMN sweep.
 *
 * SQLite has no "ALTER TABLE ADD COLUMN IF NOT EXISTS". For DBs that were
 * initialized before a new correlation column was added to schema-extensions.sql
 * (where CREATE TABLE IF NOT EXISTS is a no-op on existing tables), we detect
 * missing columns via PRAGMA table_info and ALTER them in.
 *
 * @param SQLite3 $db
 * @param string  $table
 * @param array<string,string> $columns  map: column name -> SQL type/constraints
 */
$addMissingColumns = static function (SQLite3 $db, string $table, array $columns): void {
	$have = [];
	$res = $db->query('PRAGMA table_info(' . $table . ')');
	if ($res instanceof SQLite3Result) {
		while ($row = $res->fetchArray(SQLITE3_ASSOC)) {
			$have[$row['name']] = true;
		}
	}
	foreach ($columns as $name => $type) {
		if (!isset($have[$name])) {
			$db->exec(sprintf('ALTER TABLE %s ADD COLUMN %s %s', $table, $name, $type));
		}
	}
};

// systems.health_url — W6.4 probe-target split (loopback health endpoints
// for backend services + tcp:// liveness). Existing DBs pick it up here.
$addMissingColumns($db, 'systems', [
	'health_url' => 'TEXT',
]);

// notifications.{ntfy,mail}_attempts — delivery retry counters (2026-08-01).
// Existing DBs pick them up here; every legacy row starts at 0, which is
// correct: an already-stamped row is never re-fetched, and an unstamped one
// deserves its full retry budget.
$addMissingColumns($db, 'notifications', [
	'ntfy_attempts' => 'INTEGER NOT NULL DEFAULT 0',
	'mail_attempts' => 'INTEGER NOT NULL DEFAULT 0',
]);

// events.patch_id — correlate events with apply-patches runs.
$addMissingColumns($db, 'events', [
	'patch_id' => 'TEXT',
]);
$db->exec('CREATE INDEX IF NOT EXISTS idx_events_patch ON events(patch_id)');

// events.{prev_hash,row_hash} — tamper-evident audit hash-chain (gov P1).
// Existing DBs pick these up here (schema-extensions.sql CREATE TABLE is a
// no-op on an existing table). NULL on every legacy / chain-off row, so the
// WORM triggers (WHEN OLD.row_hash IS NOT NULL) stay dormant. The triggers
// themselves are installed UNCONDITIONALLY by schema-extensions.sql above;
// init-db NEVER drops them (flag-independent contracts artifact).
$addMissingColumns($db, 'events', [
	'prev_hash' => 'TEXT',
	'row_hash'  => 'TEXT',
]);
$db->exec('CREATE INDEX IF NOT EXISTS idx_events_row_hash ON events(row_hash)');

// WORM triggers — created HERE (not in schema-extensions.sql) so row_hash is
// guaranteed present on BOTH fresh and pre-existing DBs: the ALTER sweep above
// adds it on existing installs where `CREATE TABLE IF NOT EXISTS events` was a
// no-op. Creating them in schema-extensions.sql failed ("no such column:
// row_hash") on every existing wing.db. Fire ONLY on already-chained rows
// (OLD.row_hash NOT NULL) -> dormant when the chain is off; UPDATE allows only
// actor_action_id to change; DELETE blocked unless purge_unlocked='1'.
$db->exec(<<<'SQL'
DROP TRIGGER IF EXISTS events_worm_update;
CREATE TRIGGER events_worm_update BEFORE UPDATE ON events FOR EACH ROW
  WHEN OLD.row_hash IS NOT NULL AND (
       NEW.ts IS NOT OLD.ts OR NEW.run_id IS NOT OLD.run_id OR NEW.type IS NOT OLD.type
    OR NEW.playbook IS NOT OLD.playbook OR NEW.play IS NOT OLD.play OR NEW.task IS NOT OLD.task
    OR NEW.role IS NOT OLD.role OR NEW.host IS NOT OLD.host OR NEW.duration_ms IS NOT OLD.duration_ms
    OR NEW.changed IS NOT OLD.changed OR NEW.result_json IS NOT OLD.result_json
    OR NEW.migration_id IS NOT OLD.migration_id OR NEW.upgrade_id IS NOT OLD.upgrade_id
    OR NEW.patch_id IS NOT OLD.patch_id OR NEW.coexist_svc IS NOT OLD.coexist_svc
    OR NEW.source IS NOT OLD.source OR NEW.actor_id IS NOT OLD.actor_id OR NEW.acted_at IS NOT OLD.acted_at
    OR NEW.row_hash IS NOT OLD.row_hash OR NEW.prev_hash IS NOT OLD.prev_hash)
  BEGIN SELECT RAISE(ABORT, 'events WORM: only actor_action_id may change on a chained row'); END;
DROP TRIGGER IF EXISTS events_worm_delete;
CREATE TRIGGER events_worm_delete BEFORE DELETE ON events FOR EACH ROW
  WHEN OLD.row_hash IS NOT NULL
   AND COALESCE((SELECT v FROM audit_chain_meta WHERE k='purge_unlocked'), '0') <> '1'
  BEGIN SELECT RAISE(ABORT, 'events WORM: DELETE only via the retention re-anchor path'); END;
SQL);

// Reset the WORM DELETE guard on every boot (cheap, idempotent). Closes the
// "purge crashed mid-transaction left purge_unlocked='1'" leak.
$db->exec("INSERT INTO audit_chain_meta (k,v) VALUES ('purge_unlocked','0') "
	. "ON CONFLICT(k) DO UPDATE SET v='0'");

// events.source — Anatomy P1 (2026-05-05). Closes attribution gap in
// CLAUDE.md "Wing /events table schema mismatch" tech-debt entry —
// Bone's POST handler accepted `source` in JSON but silently dropped
// it on insert; analysts had to guess attribution from `task` text
// prefixes. Hint-level free text pre-A10.
$addMissingColumns($db, 'events', [
	'source' => 'TEXT',
]);
$db->exec('CREATE INDEX IF NOT EXISTS idx_events_source ON events(source)');

// events.{actor_id,actor_action_id,acted_at} — A10 actor audit (2026-05-08).
// Cryptographic attribution: `actor_id` is the Authentik client_id of the
// writer (operator / agent / plugin); `actor_action_id` is a UUID
// grouping events that belong to one logical action (e.g. agent_run_start
// + agent_run_end emitted by the same conductor run share an
// actor_action_id). `acted_at` is the wall-clock time of the action
// (usually = ts, but kept separate so backfilled events can record
// when the row was inserted vs when the action happened). Existing DBs
// get the columns NULL-able; pre-A10 rows stay NULL — A10 is forward-
// looking attribution, not retroactive.
$addMissingColumns($db, 'events', [
	'actor_id'        => 'TEXT',
	'actor_action_id' => 'TEXT',
	'acted_at'        => 'TEXT',
]);
$db->exec('CREATE INDEX IF NOT EXISTS idx_events_actor_id        ON events(actor_id)');
$db->exec('CREATE INDEX IF NOT EXISTS idx_events_actor_action_id ON events(actor_action_id)');

// notifications.mail_digest_window — A9 daily-digest mail (2026-05-17).
// Pre-existing DBs from the A9.1 cutover (without daily-digest support)
// need the column ALTER'd in so the dispatch worker's digest-floor logic
// can stamp it. The CREATE TABLE IF NOT EXISTS above is a no-op on
// existing tables, so this sweep is the migration vehicle.
$addMissingColumns($db, 'notifications', [
    'mail_digest_window' => 'TEXT',
]);
$db->exec(
    'CREATE INDEX IF NOT EXISTS idx_notifications_mail_digest '
    . 'ON notifications(mail_digest_window) '
    . 'WHERE mail_digest_window IS NOT NULL AND mail_dispatched_at IS NULL'
);

// gdpr_breaches — GDPR Art-33/34 + NIS2/ZKB deadline engine columns
// (breach-notification engine, 2026-05-31). schema-extensions.sql CREATE TABLE
// IF NOT EXISTS is a no-op on existing tables, so this sweep ALTERs the new
// columns into pre-existing wing.db files. Types MUST match schema-extensions.sql
// (esp. the NOT NULL DEFAULT clauses) so the contract artifact stays aligned.
$addMissingColumns($db, 'gdpr_breaches', [
    'aware_at'                   => 'TEXT',
    'risk_level'                 => "TEXT NOT NULL DEFAULT 'none'",
    'data_categories'            => 'TEXT',
    'affected_records'           => 'INTEGER',
    'art33_due_at'               => 'TEXT',
    'art34_due_at'               => 'TEXT',
    'art34_exception'            => 'TEXT',
    'nis2_in_scope'              => 'INTEGER NOT NULL DEFAULT 0',
    'nis2_regime'                => 'TEXT',
    'nis2_cross_border'          => 'INTEGER NOT NULL DEFAULT 0',
    'nis2_intentional_suspected' => 'INTEGER NOT NULL DEFAULT 0',
    'nis2_early_warning_due_at'  => 'TEXT',
    'nis2_early_warning_done_at' => 'TEXT',
    'nis2_notification_due_at'   => 'TEXT',
    'nis2_notification_done_at'  => 'TEXT',
    'nis2_final_report_due_at'   => 'TEXT',
    'nis2_final_report_done_at'  => 'TEXT',
    'regulator_ref'              => 'TEXT',
    'escalated_stages_json'      => "TEXT NOT NULL DEFAULT '[]'",
]);
$db->exec('CREATE INDEX IF NOT EXISTS idx_gdpr_breaches_status ON gdpr_breaches(status, detected_at)');

// gdpr_consent — GDPR consent registry (Art. 6(1)(a) + Art. 7). The
// schema-extensions.sql CREATE TABLE IF NOT EXISTS is a no-op on a pre-existing
// wing.db, so ALTER the columns in for DBs that predate this table OR predate a
// future column add. Types MUST match schema-extensions.sql so the contract
// artifact stays aligned — EXCEPT the two timestamp columns: the fresh CREATE
// TABLE gives them DEFAULT (datetime('now')), but the ALTER fallback uses plain
// 'TEXT' (the repository stamps created_at/updated_at on every write, so a NULL
// default on a migrated row is harmless, and plain TEXT is portable across all
// SQLite ADD COLUMN builds — same constant-default discipline as the
// gdpr_breaches sweep above). The active-consent partial index references
// withdrawn_at and is therefore created HERE, AFTER the sweep guarantees the
// column exists on both fresh AND pre-existing DBs — same ordering rule that
// keeps idx_events_row_hash + the WORM triggers from failing on existing
// installs.
$addMissingColumns($db, 'gdpr_consent', [
	'subject_email'    => 'TEXT NOT NULL DEFAULT \'\'',
	'processing_id'    => 'TEXT',
	'activity'         => 'TEXT NOT NULL DEFAULT \'\'',
	'lawful_basis'     => "TEXT NOT NULL DEFAULT 'consent'",
	'tos_version_hash' => 'TEXT',
	'source'           => "TEXT NOT NULL DEFAULT 'operator'",
	'granted_at'       => 'TEXT NOT NULL DEFAULT \'\'',
	'withdrawn_at'     => 'TEXT',
	'notes'            => 'TEXT',
	'created_at'       => 'TEXT',
	'updated_at'       => 'TEXT',
]);
$db->exec('CREATE INDEX IF NOT EXISTS idx_gdpr_consent_subject    ON gdpr_consent(subject_email)');
$db->exec('CREATE INDEX IF NOT EXISTS idx_gdpr_consent_activity   ON gdpr_consent(activity)');
$db->exec('CREATE INDEX IF NOT EXISTS idx_gdpr_consent_processing ON gdpr_consent(processing_id)');
// Active-consent partial index — references withdrawn_at (ALTER-added above).
// MUST stay here, not in schema-extensions.sql, for the ordering reason above.
$db->exec(
	'CREATE INDEX IF NOT EXISTS idx_gdpr_consent_active '
	. 'ON gdpr_consent(subject_email, activity) '
	. 'WHERE withdrawn_at IS NULL'
);

// pulse_runs.{actor_action_id,acted_at} — pulse_runs already carries
// actor_id (from schema-extensions.sql:234), but lacks the action
// grouping + wall-clock fields. Adding them here aligns pulse_runs
// with events so a Pulse-driven agent run produces correlatable rows
// in both tables (start/finish events in `events` share the
// actor_action_id with the pulse_runs row).
$addMissingColumns($db, 'pulse_runs', [
	'actor_action_id' => 'TEXT',
	'acted_at'        => 'TEXT',
]);
$db->exec('CREATE INDEX IF NOT EXISTS idx_pulse_runs_actor_action_id ON pulse_runs(actor_action_id)');

// pentest_findings + pentest_targets direct attribution (A9.4, 2026-05-17).
// Pre-this, pentest had only indirect attribution (finding → target_id →
// pentest_targets, which itself had no created_by). The inspektor agent's
// runner (deferred until trivy/grype/nuclei substrates land) will write
// `discovered_by='agent:inspektor'`; operator + remediator close findings
// via /api/v1/pentest/findings/<id>/resolve which uses the bearer-token-
// derived actor_id (same pattern as the 2026-05-17 GitleaksPresenter +
// RemediationPresenter security fix).
$addMissingColumns($db, 'pentest_findings', [
	'discovered_by' => 'TEXT',
	'resolved_at'   => 'TEXT',
	'resolved_by'   => 'TEXT',
]);
$db->exec('CREATE INDEX IF NOT EXISTS idx_pf_discovered_by ON pentest_findings(discovered_by)');
$db->exec('CREATE INDEX IF NOT EXISTS idx_pf_resolved_at ON pentest_findings(resolved_at) WHERE resolved_at IS NULL');
$addMissingColumns($db, 'pentest_targets', [
	'created_by' => 'TEXT',
]);
$db->exec('CREATE INDEX IF NOT EXISTS idx_pt_created_by ON pentest_targets(created_by)');

// user_invitations.provisioning_json — A18 Cesta B (2026-05-20). Snapshot
// of the Infisical folder + Stalwart mailbox provisioning result so the
// /users/created landing page can show what was auto-provisioned. Pre-A18
// rows stay '{}'.
$addMissingColumns($db, 'user_invitations', [
	'provisioning_json' => "TEXT NOT NULL DEFAULT '{}'",
]);

// W5-B5c (2026-05-27): coexistence_planned gained target_version after the
// table first shipped (B5a). Existing DBs need the column ALTERed in — the
// --tags coexistence consumer (planned-coexistence.php) selects it.
$addMissingColumns($db, 'coexistence_planned', [
	'target_version' => 'TEXT',
]);

// ── Agentic upgrade→migration→coexistence epic (Phase B / B1) ────────────
// New columns on the EXISTING coexistence/upgrade tables land here (the
// schema-extensions.sql CREATE TABLE IF NOT EXISTS is a no-op on a pre-existing
// wing.db; ALTER is the migration vehicle). The migrations_authored TABLE is
// NEW so it lives in schema-extensions.sql, NOT here. Types/defaults documented
// in docs/plans/agentic-upgrade-migration-coexistence-design.md §2.2-2.4.

// coexistence_tracks — human-facing reversible primary/secondary state machine.
// `role`/`lifecycle` are the new state; the legacy `active 0/1` stays the live-
// routing pointer (active=1 ⟺ role='primary') so every existing reader keeps
// working untouched. source_migration_id is the soft FK to the migration this
// track is built ON (consumed at cutover via nos_migrate action=apply).
$addMissingColumns($db, 'coexistence_tracks', [
	'role'                => "TEXT NOT NULL DEFAULT 'secondary'",
	'lifecycle'           => "TEXT NOT NULL DEFAULT 'provisioned'",
	'source_migration_id' => 'TEXT',
	'promoted_at'         => 'TEXT',
	'deactivated_at'      => 'TEXT',
]);
// Single-primary DB invariant — created AFTER the sweep (role must exist first;
// same ordering discipline as idx_events_row_hash + the WORM triggers). The
// toggle writer demotes the old primary → 'secondary' in the SAME transaction
// as it promotes the new one, so a legitimate toggle never trips this; it only
// blocks a bug that would leave two primaries for one service.
$db->exec(
	'CREATE UNIQUE INDEX IF NOT EXISTS uq_coexist_one_primary '
	. "ON coexistence_tracks (service) WHERE role = 'primary'"
);

// coexistence_planned — cancel + plan-choice link + data-copy flag. The
// `cancelled` status was a documented enum value never written; cancelPlanned()
// makes it real. parent_upgrade_id back-links the path-(b) plan that spawned
// this row; source_migration_uuid is the migration the track is built ON;
// data_copy drives the cutover-time dump/restore (path (b) "with a copy").
$addMissingColumns($db, 'coexistence_planned', [
	'parent_upgrade_id'     => 'INTEGER',
	'source_migration_uuid' => 'TEXT',
	'data_copy'             => 'INTEGER NOT NULL DEFAULT 1',
	'cancelled_at'          => 'TEXT',
	'cancelled_by'          => 'TEXT',
]);

// upgrades_planned — the plan-choice branch point. plan_mode default 'migration'
// means a legacy row reads as today's only behaviour (in-place); coexistence_planned_id
// + migration_uuid back-link the chosen path. The existing UNIQUE(service,recipe_id,status)
// is untouched.
$addMissingColumns($db, 'upgrades_planned', [
	'plan_mode'              => "TEXT NOT NULL DEFAULT 'migration'",
	'coexistence_planned_id' => 'INTEGER',
	'migration_uuid'         => 'TEXT',
	'plan_choice_at'         => 'TEXT',
	// Reset-scope / session-safety (Phase 2): the resolved blast radius survives
	// queue → apply so the badge persists and the engine knows how to launch.
	// All constant-default (SQLite ADD COLUMN discipline).
	'reset_scope'            => 'TEXT',
	'session_risk'           => 'INTEGER NOT NULL DEFAULT 0',
	'run_mode'               => "TEXT NOT NULL DEFAULT 'attached'",
]);

// upgrade_recipes.coexistence_supported (F1) — the per-recipe coexistence flag,
// ingested from upgrades/*.yml. Carries the recipe's coexistence_supported into
// the /upgrades matrix → plan-choice modal option (b) enable/disable. Existing
// DBs pick it up here (schema-extensions.sql CREATE TABLE is a no-op on an
// existing table); the ingest then DELETE+reinserts every row with the real flag.
$addMissingColumns($db, 'upgrade_recipes', [
	'coexistence_supported' => 'INTEGER NOT NULL DEFAULT 0',
	// Reset-scope (Phase 1): the AUTHORED reset block JSON as written in
	// upgrades/<svc>.yml — bin/ingest-upgrade-recipes.php stores it verbatim and
	// does NOT derive the floor (the engine's resolve_reset does that at apply
	// time). NULL means the recipe authored no reset; the UI treats NULL as the
	// 'container' display floor. A CI gate (test_upgrade_reset_floor.py) pins that
	// every shipped recipe authors scope >= its derived floor, so the authored
	// value the matrix displays never understates risk. Mirrors coexistence_supported.
	'reset_json'            => 'TEXT',
]);

$db->close();

$status = $isNew ? 'Created' : 'Verified';
echo "$status database schema at $dbPath\n";
echo "Tables: components, scan_cycles, component_scan_state, scan_config, attack_probes,\n";
echo "        remediation_items, advisories, pentest_targets, pentest_areas_tested,\n";
echo "        pentest_areas_planned, pentest_findings, patches, report_types,\n";
echo "        events, migrations_applied, upgrades_applied, patches_applied,\n";
echo "        coexistence_tracks\n";
