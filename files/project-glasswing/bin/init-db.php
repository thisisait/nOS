<?php

declare(strict_types=1);

/**
 * Glasswing — Idempotent SQLite schema initialization.
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

$dbPath = $dataDir . '/glasswing.db';
$isNew = !file_exists($dbPath);

$db = new SQLite3($dbPath);
$db->enableExceptions(true);
$db->exec('PRAGMA journal_mode = WAL');
$db->exec('PRAGMA foreign_keys = ON');

$statements = [
	// Components (from versions.json)
	"CREATE TABLE IF NOT EXISTS components (
		id              TEXT PRIMARY KEY,
		name            TEXT NOT NULL,
		category        TEXT NOT NULL DEFAULT 'docker',
		stack           TEXT,
		image           TEXT,
		version_var     TEXT,
		default_version TEXT,
		pinned          INTEGER NOT NULL DEFAULT 1,
		network_exposed INTEGER NOT NULL DEFAULT 0,
		has_web_ui      INTEGER NOT NULL DEFAULT 0,
		priority        TEXT NOT NULL DEFAULT 'medium',
		upstream_repo   TEXT,
		port            INTEGER,
		domain          TEXT,
		created_at      TEXT NOT NULL DEFAULT (datetime('now')),
		updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
	)",

	// Scan cycles
	"CREATE TABLE IF NOT EXISTS scan_cycles (
		id                  INTEGER PRIMARY KEY AUTOINCREMENT,
		cycle_number        INTEGER NOT NULL UNIQUE,
		started_at          TEXT NOT NULL DEFAULT (datetime('now')),
		completed_at        TEXT,
		batch_components    TEXT,
		notes               TEXT
	)",

	// Per-component scan state
	"CREATE TABLE IF NOT EXISTS component_scan_state (
		component_id        TEXT NOT NULL PRIMARY KEY,
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
		created_at      TEXT NOT NULL DEFAULT (datetime('now')),
		updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
	)",

	// Pentest areas tested
	"CREATE TABLE IF NOT EXISTS pentest_areas_tested (
		id              INTEGER PRIMARY KEY AUTOINCREMENT,
		target_id       TEXT NOT NULL REFERENCES pentest_targets(id) ON DELETE CASCADE,
		area            TEXT NOT NULL,
		date            TEXT NOT NULL,
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
		devboxnos_mitigation    TEXT,
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

$db->close();

$status = $isNew ? 'Created' : 'Verified';
echo "$status database schema at $dbPath\n";
echo "Tables: components, scan_cycles, component_scan_state, scan_config, attack_probes,\n";
echo "        remediation_items, advisories, pentest_targets, pentest_areas_tested,\n";
echo "        pentest_areas_planned, pentest_findings, patches, report_types\n";
