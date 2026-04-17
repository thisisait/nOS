<?php

declare(strict_types=1);

/**
 * Glasswing — Migrate components -> systems table.
 *
 * Idempotent: safe to re-run. Checks if migration is needed by looking
 * for the old `components` TABLE (not VIEW). If `systems` table already
 * exists and `components` is a VIEW, does nothing.
 *
 * Usage: php bin/migrate-systems.php [--data-dir=/path/to/data]
 */

$dataDir = null;
foreach ($argv as $arg) {
	if (str_starts_with($arg, '--data-dir=')) {
		$dataDir = substr($arg, 11);
	}
}
$dataDir ??= __DIR__ . '/../data';
$dbPath = $dataDir . '/glasswing.db';

if (!is_file($dbPath)) {
	echo "No database at $dbPath -- run init-db.php first\n";
	exit(0);
}

$db = new SQLite3($dbPath);
$db->enableExceptions(true);
$db->busyTimeout(5000);

// Check current state
$systemsExists = (bool) $db->querySingle(
	"SELECT 1 FROM sqlite_master WHERE type='table' AND name='systems'"
);
$componentsIsTable = (bool) $db->querySingle(
	"SELECT 1 FROM sqlite_master WHERE type='table' AND name='components'"
);

if ($systemsExists && !$componentsIsTable) {
	echo "Already migrated -- systems table exists, components is a view\n";
	$db->close();
	exit(0);
}

echo "Migrating components -> systems...\n";

// 1. Create systems table
$db->busyTimeout(5000);
$db->exec("CREATE TABLE IF NOT EXISTS systems (
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
	domain          TEXT,
	port            INTEGER,
	url             TEXT,
	network_exposed INTEGER NOT NULL DEFAULT 0,
	has_web_ui      INTEGER NOT NULL DEFAULT 0,
	toggle_var      TEXT,
	enabled         INTEGER NOT NULL DEFAULT 1,
	priority        TEXT NOT NULL DEFAULT 'medium',
	upstream_repo   TEXT,
	health_status   TEXT NOT NULL DEFAULT 'unknown',
	health_http_code INTEGER,
	health_ms       INTEGER,
	health_checked_at TEXT,
	source          TEXT NOT NULL DEFAULT 'manual',
	created_at      TEXT NOT NULL DEFAULT (datetime('now')),
	updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
)");

// 2. Migrate data from old components table
if ($componentsIsTable) {
	$count = $db->querySingle('SELECT COUNT(*) FROM components');
	if ($count > 0) {
		$db->exec("INSERT OR IGNORE INTO systems
			(id, name, category, stack, image, version_var, version, pinned,
			 network_exposed, has_web_ui, priority, upstream_repo, port, domain,
			 source, created_at, updated_at)
			SELECT id, name, category, stack, image, version_var, default_version, pinned,
			       network_exposed, has_web_ui, priority, upstream_repo, port, domain,
			       'components_db', created_at, updated_at
			FROM components
		");
		echo "Migrated $count components into systems table\n";
	}

	// 3. Drop old table, create backward-compat view
	$db->exec('DROP TABLE components');
	echo "Dropped old components table\n";
}

// 4. Backward-compat view
$viewExists = (bool) $db->querySingle(
	"SELECT 1 FROM sqlite_master WHERE type='view' AND name='components'"
);
if (!$viewExists) {
	$db->exec("CREATE VIEW components AS
		SELECT id, name, category, stack, image, version_var,
		       version AS default_version, pinned, network_exposed, has_web_ui,
		       priority, upstream_repo, port, domain, created_at, updated_at
		FROM systems
	");
	echo "Created components backward-compat view\n";
}

// 5. Indexes
$db->exec('CREATE INDEX IF NOT EXISTS idx_sys_parent ON systems(parent_id)');
$db->exec('CREATE INDEX IF NOT EXISTS idx_sys_stack ON systems(stack)');
$db->exec('CREATE INDEX IF NOT EXISTS idx_sys_category ON systems(category)');
$db->exec('CREATE INDEX IF NOT EXISTS idx_sys_health ON systems(health_status)');

$db->close();
echo "Migration complete\n";
