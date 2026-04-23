<?php
/**
 * MigrationRepository — upsert + local mirror fallback when BoxAPI is down.
 */

declare(strict_types=1);

require __DIR__ . '/bootstrap.php';

use App\Model\BoneClient;
use App\Model\EventRepository;
use App\Model\MigrationRepository;

/** Fake BoneClient that always returns 502 so repo falls back to SQLite. */
final class DeadBox extends BoneClient
{
	public function __construct() { parent::__construct('http://127.0.0.1:1', 'x', 1); }
	public function get(string $path, array $query = []): array
	{
		return ['status' => 502, 'body' => ['error' => 'down']];
	}
	public function post(string $path, ?array $body = null): array
	{
		return ['status' => 502, 'body' => ['error' => 'down']];
	}
}

$db = gw_make_temp_db();
$exp = gw_make_explorer($db);
$events = new EventRepository($exp);
$repo = new MigrationRepository($exp, new DeadBox(), $events);

// Upsert an applied migration record.
$repo->upsertApplied([
	'id'            => '2026-04-22-rebrand',
	'title'         => 'Rebrand devBoxNOS → nOS',
	'severity'      => 'breaking',
	'at'            => '2026-04-22T12:45:00Z',
	'success'       => true,
	'duration_sec'  => 12,
	'steps_applied' => 4,
	'steps_total'   => 4,
]);

// Second upsert with same id should update, not duplicate.
$repo->upsertApplied([
	'id'            => '2026-04-22-rebrand',
	'title'         => 'Rebrand devBoxNOS → nOS',
	'severity'      => 'breaking',
	'at'            => '2026-04-22T12:45:00Z',
	'success'       => true,
	'duration_sec'  => 13,
	'steps_applied' => 4,
	'steps_total'   => 4,
]);

// BoxAPI is down → listApplied must fall back to SQLite mirror.
$applied = $repo->listApplied();
T::eq(1, count($applied), 'single applied migration (dedup on upsert)');
T::eq('2026-04-22-rebrand', $applied[0]['id'], 'correct id returned');
T::eq(13, (int) $applied[0]['duration_sec'], 'upsert updated duration');
T::truthy(isset($applied[0]['record']), 'raw_record_json is decoded into record');

// get() also falls back.
$rec = $repo->get('2026-04-22-rebrand');
T::truthy($rec !== null, 'get returns record from mirror');
T::eq('breaking', $rec['severity'], 'severity preserved');

// Missing id returns null.
T::eq(null, $repo->get('does-not-exist'), 'missing id returns null');

// Events scoping: seed an event tied to this migration.
$events->insert([
	'ts' => '2026-04-22T12:45:00Z',
	'run_id' => 'run_x',
	'type' => 'migration_end',
	'migration_id' => '2026-04-22-rebrand',
]);
T::eq(1, count($repo->getEventsFor('2026-04-22-rebrand')), 'events scoped to migration');

// Empty-id upsert rejects.
$thrown = false;
try {
	$repo->upsertApplied(['title' => 'no id']);
} catch (InvalidArgumentException $e) {
	$thrown = true;
}
T::truthy($thrown, 'upsert rejects missing id');

// listPending returns [] when BoxAPI is down (no local source).
T::eq([], $repo->listPending(), 'listPending empty on BoxAPI outage');

T::done('MigrationRepository');
