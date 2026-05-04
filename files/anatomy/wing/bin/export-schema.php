<?php

declare(strict_types=1);

/**
 * Wing — Export wing.db schema (DDL) to a deterministic SQL artifact.
 *
 * Anatomy A5 (2026-05-04) — DDL half of the contracts pair.
 *
 * Usage:
 *   php bin/export-schema.php [--db=/path/to/wing.db] [--output=/path/to/file.sql]
 *
 * Defaults:
 *   --db      ~/wing/data/wing.db  (the host launchd Wing data dir)
 *             Falls back to a fresh in-memory build via init-db.php +
 *             schema-extensions.sql + gdpr-seed.sql when the data dir does
 *             not exist (CI-friendly).
 *   --output  files/anatomy/skills/contracts/wing.db-schema.sql
 *             relative to the repo root.
 *
 * The export reads ``sqlite_master`` for tables, indexes, views, and
 * triggers, sorted alphabetically per kind. Output is a regenerable
 * artifact committed to the repo for drift-check purposes.
 */

$args = [];
foreach (array_slice($argv, 1) as $a) {
	if (str_starts_with($a, '--')) {
		$kv = explode('=', substr($a, 2), 2);
		$args[$kv[0]] = $kv[1] ?? '1';
	}
}

$here = __DIR__;
$wingDir = dirname($here);
// bin/ -> wing/ -> anatomy/ -> files/ -> <repo>
$repoRoot = dirname($wingDir, 3);

$dbPath = $args['db'] ?? (getenv('HOME') . '/wing/data/wing.db');
$outPath = $args['output'] ?? ($repoRoot . '/files/anatomy/skills/contracts/wing.db-schema.sql');

// Build a temp DB from scratch if the host DB is missing. This is the
// CI path: spawn init-db.php via proc_open against a fresh dir, then dump.
$tempDir = null;
if (!is_file($dbPath)) {
	$tempDir = sys_get_temp_dir() . '/wing-schema-' . bin2hex(random_bytes(6));
	mkdir($tempDir, 0700, true);
	$cmd = [
		PHP_BINARY,
		$wingDir . '/bin/init-db.php',
		'--data-dir=' . $tempDir,
	];
	$descriptors = [
		1 => ['pipe', 'w'],
		2 => ['pipe', 'w'],
	];
	$proc = proc_open($cmd, $descriptors, $pipes);
	if (!is_resource($proc)) {
		fwrite(STDERR, "Failed to launch init-db.php\n");
		exit(1);
	}
	$stdout = stream_get_contents($pipes[1]);
	$stderr = stream_get_contents($pipes[2]);
	fclose($pipes[1]);
	fclose($pipes[2]);
	$rc = proc_close($proc);
	if ($rc !== 0) {
		fwrite(STDERR, "init-db.php failed (rc=$rc):\n$stdout\n$stderr\n");
		exit(1);
	}
	$dbPath = $tempDir . '/wing.db';
	if (!is_file($dbPath)) {
		fwrite(STDERR, "init-db.php did not produce $dbPath\n");
		exit(1);
	}
}

$db = new SQLite3($dbPath, SQLITE3_OPEN_READONLY);
$db->enableExceptions(true);

$kinds = ['table', 'view', 'index', 'trigger'];
$sections = [];
foreach ($kinds as $kind) {
	$res = $db->query(
		"SELECT name, sql FROM sqlite_master "
		. "WHERE type = '" . $kind . "' "
		. "AND name NOT LIKE 'sqlite_%' "
		. "AND sql IS NOT NULL "
		. "ORDER BY name"
	);
	$rows = [];
	while ($row = $res->fetchArray(SQLITE3_ASSOC)) {
		$rows[] = trim($row['sql']) . ';';
	}
	if ($rows) {
		$sections[$kind] = $rows;
	}
}

$db->close();

// Cleanup temp DB if we built one. WAL/SHM files may exist alongside.
if ($tempDir !== null) {
	foreach (glob($tempDir . '/wing.db*') ?: [] as $f) {
		@unlink($f);
	}
	@rmdir($tempDir);
}

$header = "-- AUTO-GENERATED — do not edit by hand.\n"
	. "-- Source: files/anatomy/wing/bin/init-db.php +\n"
	. "--         files/anatomy/wing/db/schema-extensions.sql +\n"
	. "--         files/anatomy/wing/db/gdpr-seed.sql\n"
	. "-- Regenerate: php files/anatomy/wing/bin/export-schema.php\n"
	. "-- CI drift check: .github/workflows/ci.yml — contracts-drift job.\n"
	. "\n"
	. "PRAGMA foreign_keys = ON;\n\n";

$body = '';
foreach ($kinds as $kind) {
	if (empty($sections[$kind])) {
		continue;
	}
	$body .= "-- ============================================================\n";
	$body .= "-- " . strtoupper($kind) . "S (" . count($sections[$kind]) . ")\n";
	$body .= "-- ============================================================\n\n";
	$body .= implode("\n\n", $sections[$kind]) . "\n\n";
}

if (!is_dir(dirname($outPath))) {
	mkdir(dirname($outPath), 0755, true);
}
file_put_contents($outPath, $header . $body);

$counts = array_map('count', $sections);
echo "Wrote $outPath\n";
foreach ($counts as $k => $n) {
	echo "  $k: $n\n";
}
