<?php

declare(strict_types=1);

/**
 * Wing — Provision/reconverge API token (called by Ansible).
 *
 * Idempotent UPSERT: DELETE all rows matching --name, then INSERT the new
 * token hash. Runs every playbook execution so prefix rotation propagates
 * to the live DB without leaving stale tokens behind.
 *
 * Usage: php bin/provision-token.php --db=/path/to/wing.db --token=VALUE --name=NAME
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
	// The three cortex axes. A token carrying fewer than all three reaches the
	// executor with NO capability at all — CortexCapability::fromToken returns
	// null unless every axis is populated, and CortexBindingGate answers 403.
	// That is deliberate (a token powerful elsewhere is not a way in), and it is
	// why these are provisioned together or not at all.
	if (str_starts_with($arg, '--cortex-verbs=')) {
		$cortexVerbs = substr($arg, 15);
	}
	if (str_starts_with($arg, '--cortex-namespaces=')) {
		$cortexNamespaces = substr($arg, 20);
	}
	if (str_starts_with($arg, '--cortex-tenants=')) {
		$cortexTenants = substr($arg, 17);
	}
}

$cortex = [$cortexVerbs ?? null, $cortexNamespaces ?? null, $cortexTenants ?? null];
$given = count(array_filter($cortex, static fn ($v) => $v !== null && $v !== ''));
if ($given > 0 && $given < 3) {
	// Refused rather than half-written: a row with two of three axes is a token
	// that looks cortex-scoped in the table and is refused at the door, which is
	// the most confusing of the three possible states.
	echo "All three cortex axes are required together (--cortex-verbs, "
		. "--cortex-namespaces, --cortex-tenants) or none. Got {$given}.\n";
	exit(1);
}

if (!$dbPath || !$token) {
	echo "Usage: php bin/provision-token.php --db=PATH --token=VALUE [--name=NAME]\n"
		. "       [--cortex-verbs=a,b --cortex-namespaces=x,y --cortex-tenants=t]\n";
	exit(1);
}

if (!file_exists($dbPath)) {
	echo "Database not found: $dbPath\n";
	exit(1);
}

$db = new SQLite3($dbPath);
$db->busyTimeout(5000); // WAL is on-file; per-conn timeout prevents 'database is locked' under concurrent writers (scout HIGH 2026-07-15)
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

// Idempotence compares the SCOPES as well as the secret. Comparing the hash
// alone made a scope change invisible: re-running with new cortex axes on an
// unchanged token printed "already up-to-date" and wrote nothing, so the row
// stayed as it was and the converge reported changed=false about a change it
// had refused to make.
$scopeStmt = $db->prepare(
	'SELECT cortex_verbs, cortex_namespaces, cortex_tenants FROM api_tokens WHERE name = :n'
);
$scopeStmt->bindValue(':n', $name);
$scopeRes = $scopeStmt->execute();
$existingScopes = $scopeRes->fetchArray(SQLITE3_ASSOC) ?: [];
$wantScopes = [
	'cortex_verbs' => $cortexVerbs ?? null,
	'cortex_namespaces' => $cortexNamespaces ?? null,
	'cortex_tenants' => $cortexTenants ?? null,
];
$scopesMatch = true;
foreach ($wantScopes as $col => $want) {
	if (($existingScopes[$col] ?? null) !== ($want === '' ? null : $want)) {
		$scopesMatch = false;
		break;
	}
}

if (count($existingHashes) === 1 && $existingHashes[0] === $hash && $scopesMatch) {
	echo "Token '$name' already up-to-date. Skipping.\n";
	$db->close();
	exit(0);
}

// Reconverge: drop any stale rows for this name, then insert fresh hash.
$db->exec('BEGIN TRANSACTION');

$deleteStmt = $db->prepare('DELETE FROM api_tokens WHERE name = :n');
$deleteStmt->bindValue(':n', $name);
$deleteStmt->execute();

$insertStmt = $db->prepare(
	'INSERT INTO api_tokens (token, name, created_by, cortex_verbs, cortex_namespaces, cortex_tenants) '
	. 'VALUES (:t, :n, :c, :cv, :cn, :ct)'
);
$insertStmt->bindValue(':t', $hash);
$insertStmt->bindValue(':n', $name);
$insertStmt->bindValue(':c', 'ansible');
foreach ([':cv' => $cortexVerbs ?? null, ':cn' => $cortexNamespaces ?? null,
	':ct' => $cortexTenants ?? null] as $bind => $value) {
	$insertStmt->bindValue($bind, ($value === null || $value === '') ? null : $value, SQLITE3_TEXT);
}
$insertStmt->execute();

$db->exec('COMMIT');
$db->close();

$action = count($existingHashes) > 0 ? 'Updated' : 'Created';
echo "$action API token '$name'\n";
