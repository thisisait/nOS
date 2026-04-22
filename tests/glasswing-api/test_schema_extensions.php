<?php
/**
 * Schema extensions — all expected tables + indexes exist after init.
 */

declare(strict_types=1);

require __DIR__ . '/bootstrap.php';

$db = gw_make_temp_db();
$pdo = new PDO('sqlite:' . $db);
$pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);

$tables = [];
foreach ($pdo->query("SELECT name FROM sqlite_master WHERE type='table'") as $row) {
	$tables[$row['name']] = true;
}

foreach (['events', 'migrations_applied', 'upgrades_applied', 'coexistence_tracks'] as $t) {
	T::truthy(isset($tables[$t]), "table $t exists");
}

// Indexes.
$indexes = [];
foreach ($pdo->query("SELECT name FROM sqlite_master WHERE type='index'") as $row) {
	$indexes[$row['name']] = true;
}
foreach ([
	'idx_events_run_id', 'idx_events_ts', 'idx_events_type',
	'idx_events_migration', 'idx_events_upgrade',
	'idx_migrations_applied_at', 'idx_migrations_severity',
	'idx_upgrades_service', 'idx_upgrades_applied_at',
	'idx_coexist_service', 'idx_coexist_active',
] as $idx) {
	T::truthy(isset($indexes[$idx]), "index $idx exists");
}

// UNIQUE constraint on coexistence_tracks(service,tag).
$stmt = $pdo->prepare(
	"INSERT INTO coexistence_tracks(service,tag,version) VALUES(?, ?, ?)"
);
$stmt->execute(['x', 'a', '1']);
$threw = false;
try {
	$stmt->execute(['x', 'a', '2']);
} catch (PDOException $e) {
	$threw = true;
}
T::truthy($threw, 'UNIQUE(service,tag) enforced');

T::done('schema-extensions.sql');
