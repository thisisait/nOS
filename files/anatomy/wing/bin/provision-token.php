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
	// Ops-plane route class: comma-separated wing.read / wing.write. Omitted
	// leaves NULL, which is unrestricted — see init-db.php's column note.
	if ($arg === '--deactivate') {
		$deactivate = true;
	}
	if (str_starts_with($arg, '--scopes=')) {
		$scopes = substr($arg, 9);
	}
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

// --deactivate: flip active=0 for --name and exit. Ruling 4 (docs/doctrine/
// agentkit.md §6.4): the roster close left retired/parked agents' unrestricted
// tokens live — "provision only upserts, it never reconciles absence" is over.
if ($deactivate ?? false) {
	if (!$dbPath || !($name ?? '') || $name === 'default') {
		echo "--deactivate needs --db and an explicit --name\n";
		exit(1);
	}
	$db = new SQLite3($dbPath);
	$db->busyTimeout(5000);
	$db->enableExceptions(true);
	$stmt = $db->prepare('UPDATE api_tokens SET active = 0 WHERE name = :n AND active = 1');
	$stmt->bindValue(':n', $name, SQLITE3_TEXT);
	$stmt->execute();
	echo $db->changes() > 0 ? "Deactivated {$name}\n" : "Already inactive or absent: {$name}\n";
	exit(0);
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
		. "       [--scopes=wing.read,wing.write]\n"
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
	'SELECT scopes, cortex_verbs, cortex_namespaces, cortex_tenants FROM api_tokens WHERE name = :n'
);
$scopeStmt->bindValue(':n', $name);
$scopeRes = $scopeStmt->execute();
$existingScopes = $scopeRes->fetchArray(SQLITE3_ASSOC) ?: [];
$wantScopes = [
	'scopes' => $scopes ?? null,
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
	'INSERT INTO api_tokens (token, name, created_by, scopes, cortex_verbs, cortex_namespaces, cortex_tenants) '
	. 'VALUES (:t, :n, :c, :s, :cv, :cn, :ct)'
);
$insertStmt->bindValue(':t', $hash);
$insertStmt->bindValue(':n', $name);
$insertStmt->bindValue(':c', 'ansible');
foreach ([':s' => $scopes ?? null, ':cv' => $cortexVerbs ?? null, ':cn' => $cortexNamespaces ?? null,
	':ct' => $cortexTenants ?? null] as $bind => $value) {
	$insertStmt->bindValue($bind, ($value === null || $value === '') ? null : $value, SQLITE3_TEXT);
}
$insertStmt->execute();

$db->exec('COMMIT');
$db->close();

$action = count($existingHashes) > 0 ? 'Updated' : 'Created';
echo "$action API token '$name'\n";
