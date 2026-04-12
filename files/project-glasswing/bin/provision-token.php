<?php

declare(strict_types=1);

/**
 * Glasswing — Provision/reconverge API token (called by Ansible).
 *
 * Idempotent UPSERT: DELETE all rows matching --name, then INSERT the new
 * token hash. Runs every playbook execution so prefix rotation propagates
 * to the live DB without leaving stale tokens behind.
 *
 * Usage: php bin/provision-token.php --db=/path/to/glasswing.db --token=VALUE --name=NAME
 */

$dbPath = null;
$token = null;
$name = 'default';

foreach ($argv as $arg) {
	if (str_starts_with($arg, '--db=')) {
		$dbPath = substr($arg, 5);
	}
	if (str_starts_with($arg, '--token=')) {
		$token = substr($arg, 8);
	}
	if (str_starts_with($arg, '--name=')) {
		$name = substr($arg, 7);
	}
}

if (!$dbPath || !$token) {
	echo "Usage: php bin/provision-token.php --db=PATH --token=VALUE [--name=NAME]\n";
	exit(1);
}

if (!file_exists($dbPath)) {
	echo "Database not found: $dbPath\n";
	exit(1);
}

$db = new SQLite3($dbPath);
$db->enableExceptions(true);
$db->exec('PRAGMA journal_mode = WAL');

// Store SHA-256 hash, not plaintext
$hash = hash('sha256', $token);

// Check current state: is this hash the only token with this name?
$checkStmt = $db->prepare('SELECT token FROM api_tokens WHERE name = :n');
$checkStmt->bindValue(':n', $name);
$result = $checkStmt->execute();
$existingHashes = [];
while ($row = $result->fetchArray(SQLITE3_ASSOC)) {
	$existingHashes[] = $row['token'];
}

if (count($existingHashes) === 1 && $existingHashes[0] === $hash) {
	echo "Token '$name' already up-to-date. Skipping.\n";
	$db->close();
	exit(0);
}

// Reconverge: drop any stale rows for this name, then insert fresh hash.
$db->exec('BEGIN TRANSACTION');

$deleteStmt = $db->prepare('DELETE FROM api_tokens WHERE name = :n');
$deleteStmt->bindValue(':n', $name);
$deleteStmt->execute();

$insertStmt = $db->prepare('INSERT INTO api_tokens (token, name, created_by) VALUES (:t, :n, :c)');
$insertStmt->bindValue(':t', $hash);
$insertStmt->bindValue(':n', $name);
$insertStmt->bindValue(':c', 'ansible');
$insertStmt->execute();

$db->exec('COMMIT');
$db->close();

$action = count($existingHashes) > 0 ? 'Updated' : 'Created';
echo "$action API token '$name'\n";
