<?php

declare(strict_types=1);

/**
 * Wing — Idempotent re-sync of remediation-queue.json into remediation_items.
 *
 * Usage:
 *   php bin/ingest-remediation.php [--json=/path/to/remediation-queue.json]
 *
 * The authoritative source is docs/llm/security/remediation-queue.json. The
 * one-shot bin/migrate.php imports it ONCE (it short-circuits forever after
 * systems.source='components_db' exists), so the /remediation page silently
 * drifts as the queue gains/loses items. This script is the ongoing re-sync:
 * it UPSERTs every item keyed on its stable `id` (the TEXT PRIMARY KEY,
 * REM-NNN), so running it twice yields the same row count and updated fields
 * reflect the JSON. It NEVER duplicates and NEVER deletes — the queue file is
 * append-mostly and resolved items keep their history.
 *
 * DB path: env WING_DB_PATH, else ~/wing/app/data/wing.db — identical
 * resolution to bin/dispatch-notifications.php, so it runs the same under the
 * playbook (WING_DB_PATH unset → HOME default) and standalone (WING_DB_PATH set).
 *
 * Exit codes:
 *   0  — clean upsert
 *   1  — fatal: JSON missing/unparseable, DB unreadable, or write failure
 */

$jsonPath = null;
foreach ($argv as $arg) {
	if (str_starts_with($arg, '--json=')) {
		$jsonPath = substr($arg, 7);
	}
}

// Default JSON: repo docs/llm/security/remediation-queue.json relative to this
// script (bin/ -> ../../../../docs/llm/security). Resolved with realpath so a
// missing file surfaces a clear error rather than a silent skip.
if (!$jsonPath) {
	$jsonPath = __DIR__ . '/../../../../docs/llm/security/remediation-queue.json';
}

$wingDb = getenv('WING_DB_PATH') ?: ($_SERVER['HOME'] . '/wing/app/data/wing.db');

if (!is_file($jsonPath)) {
	fwrite(STDERR, "fatal: remediation-queue.json not found at {$jsonPath}\n");
	exit(1);
}
if (!file_exists($wingDb)) {
	fwrite(STDERR, "fatal: wing.db not found at {$wingDb}\n");
	exit(1);
}

$raw = file_get_contents($jsonPath);
$data = json_decode($raw, true);
if (!is_array($data)) {
	fwrite(STDERR, "fatal: could not parse JSON at {$jsonPath}\n");
	exit(1);
}
$items = $data['items'] ?? $data;
if (!is_array($items)) {
	fwrite(STDERR, "fatal: no 'items' array in {$jsonPath}\n");
	exit(1);
}

// remediation_items.status has a CHECK constraint: IN ('pending','resolved',
// 'wontfix'). The queue JSON also carries 'vendor-blocked' (REM-014/046 — the
// abandoned tiredofit FreePBX image, CVEs UNFIXABLE; operators accept the risk
// per CLAUDE.md). That's the schema's "won't be fixed" bucket, so we coerce it
// to 'wontfix'. This is precisely why the one-shot migrate.php silently dropped
// those two rows: it used INSERT OR IGNORE, which swallows the CHECK rejection
// (83 in DB vs 85 in JSON). Normalize here so the /remediation page shows all 85.
$statusMap = [
	'vendor-blocked' => 'wontfix',
	'vendor_blocked' => 'wontfix',
];
$validStatus = ['pending', 'resolved', 'wontfix'];

$db = new SQLite3($wingDb);
$db->busyTimeout(5000); // WAL is on-file; per-conn timeout prevents 'database is locked' under concurrent writers (scout HIGH 2026-07-15)
$db->enableExceptions(true);
$db->exec('PRAGMA journal_mode = WAL');
$db->exec('PRAGMA foreign_keys = ON');

$before = (int) $db->querySingle('SELECT COUNT(*) FROM remediation_items');

// UPSERT keyed on the stable id (remediation_items.id is TEXT PRIMARY KEY).
// On conflict we refresh every JSON-sourced field but leave Wing-owned state
// alone: created_at is preserved (schema default fires only on first insert),
// resolved_by (operator/agent attribution, not in the JSON) is untouched, and
// found_at is INSERT-ONLY — "when first discovered" is immutable, so it is
// omitted from the UPDATE branch (a JSON row without found_at binds now() for
// the insert; re-syncs never touch it again).
//
// The DO UPDATE carries a WHERE guard so it fires ONLY when a JSON-sourced
// field actually differs. Without it, updated_at = now() rewrote every row on
// every run — making the task report "changed" on every idempotent playbook
// pass and turning updated_at into "last sync" instead of "last real change".
// With the guard, $db->changes() counts only real inserts/updates.
$sql = <<<SQL
INSERT INTO remediation_items
	(id, finding_ref, component_id, severity, current_version, fix_version,
	 remediation_type, remediation_detail, status, auto_fixable, source,
	 confidence, found_at, resolved_at, scan_cycle, updated_at)
VALUES
	(:id, :fr, :cid, :sev, :cv, :fv, :rt, :rd, :st, :af, :src, :conf,
	 :fa, :ra, :sc, datetime('now'))
ON CONFLICT(id) DO UPDATE SET
	finding_ref        = excluded.finding_ref,
	component_id       = excluded.component_id,
	severity           = excluded.severity,
	current_version    = excluded.current_version,
	fix_version        = excluded.fix_version,
	remediation_type   = excluded.remediation_type,
	remediation_detail = excluded.remediation_detail,
	status             = excluded.status,
	auto_fixable       = excluded.auto_fixable,
	source             = excluded.source,
	confidence         = excluded.confidence,
	resolved_at        = excluded.resolved_at,
	scan_cycle         = excluded.scan_cycle,
	updated_at         = datetime('now')
WHERE
	remediation_items.finding_ref        IS NOT excluded.finding_ref
	OR remediation_items.component_id    IS NOT excluded.component_id
	OR remediation_items.severity        IS NOT excluded.severity
	OR remediation_items.current_version IS NOT excluded.current_version
	OR remediation_items.fix_version     IS NOT excluded.fix_version
	OR remediation_items.remediation_type IS NOT excluded.remediation_type
	OR remediation_items.remediation_detail IS NOT excluded.remediation_detail
	OR remediation_items.status          IS NOT excluded.status
	OR remediation_items.auto_fixable    IS NOT excluded.auto_fixable
	OR remediation_items.source          IS NOT excluded.source
	OR remediation_items.confidence      IS NOT excluded.confidence
	OR remediation_items.resolved_at     IS NOT excluded.resolved_at
	OR remediation_items.scan_cycle      IS NOT excluded.scan_cycle
SQL;

$db->exec('BEGIN TRANSACTION');
$upserted = 0;
$changed = 0;
try {
	$stmt = $db->prepare($sql);
	foreach ($items as $item) {
		if (empty($item['id'])) {
			continue;
		}
		$stmt->bindValue(':id', $item['id']);
		$stmt->bindValue(':fr', $item['finding_ref'] ?? null);
		$stmt->bindValue(':cid', $item['component'] ?? ($item['component_id'] ?? null));
		$stmt->bindValue(':sev', $item['severity']);
		$stmt->bindValue(':cv', $item['current_version'] ?? null);
		$stmt->bindValue(':fv', $item['fix_version'] ?? null);
		$stmt->bindValue(':rt', $item['remediation_type'] ?? null);
		$stmt->bindValue(':rd', $item['remediation_detail'] ?? null);
		$rawStatus = $item['status'] ?? 'pending';
		$status = $statusMap[$rawStatus] ?? $rawStatus;
		if (!in_array($status, $validStatus, true)) {
			$status = 'pending';   // unknown status → safest schema-valid bucket
		}
		$stmt->bindValue(':st', $status);
		$stmt->bindValue(':af', (int) ($item['auto_fixable'] ?? false));
		$stmt->bindValue(':src', $item['source'] ?? null);
		$stmt->bindValue(':conf', $item['confidence'] ?? 'medium');
		// found_at is NOT NULL in schema; the column default only fires when
		// omitted, not on an explicit NULL bind — so fall back to now() like
		// migrate.php did. (None currently lack it, but stay defensive.)
		$stmt->bindValue(':fa', $item['found_at'] ?? date('c'));
		$stmt->bindValue(':ra', $item['resolved_at'] ?? null);
		$stmt->bindValue(':sc', $item['scan_cycle'] ?? null);
		$stmt->execute();
		$stmt->reset();
		$upserted++;
		$changed += $db->changes();   // 1 on real insert/update, 0 on WHERE-guarded no-op
	}
	$db->exec('COMMIT');
} catch (\Throwable $e) {
	$db->exec('ROLLBACK');
	fwrite(STDERR, "fatal: upsert failed: " . $e->getMessage() . "\n");
	$db->close();
	exit(1);
}

$after = (int) $db->querySingle('SELECT COUNT(*) FROM remediation_items');
$db->close();

echo "remediation_items: {$before} -> {$after} (scanned {$upserted}, changed={$changed}) from " . basename($jsonPath) . "\n";
exit(0);
