<?php
/**
 * EventRepository — insert, query, migration/upgrade scoping, type counts.
 */

declare(strict_types=1);

require __DIR__ . '/bootstrap.php';

use App\Model\EventRepository;

$db = gw_make_temp_db();
$explorer = gw_make_explorer($db);
$repo = new EventRepository($explorer);

// Insert three events across two run_ids, two types.
$id1 = $repo->insert([
	'ts'       => '2026-04-22T10:00:00Z',
	'run_id'   => 'run_A',
	'type'     => 'playbook_start',
	'playbook' => 'main.yml',
	'host'     => 'nos-local',
]);
$id2 = $repo->insert([
	'ts'       => '2026-04-22T10:00:05Z',
	'run_id'   => 'run_A',
	'type'     => 'task_changed',
	'task'     => 'Install brew pkg',
	'changed'  => true,
	'duration_ms' => 120,
]);
$id3 = $repo->insert([
	'ts'           => '2026-04-22T11:00:00Z',
	'run_id'       => 'run_B',
	'type'         => 'migration_end',
	'migration_id' => '2026-04-22-rebrand',
	'result'       => ['ok' => true, 'steps' => 4],
]);

T::truthy($id1 > 0, 'insert returns positive id');
T::eq(3, $id1 + 0 && $id2 && $id3 ? 3 : 0, 'three inserts succeeded');

// query with no filter returns all (newest first).
$all = $repo->query([], 10);
T::eq(3, $all['total'], 'total count matches');
T::eq(3, count($all['items']), 'items count matches');
T::eq('migration_end', $all['items'][0]['type'], 'newest first ordering');

// result_json decodes back into 'result'.
T::eq(['ok' => true, 'steps' => 4], $all['items'][0]['result'], 'result json decoded');

// Filter by run_id.
$runA = $repo->query(['run_id' => 'run_A']);
T::eq(2, $runA['total'], 'run_A filter total');

// Filter by type.
$changed = $repo->query(['type' => 'task_changed']);
T::eq(1, $changed['total'], 'type filter total');

// Filter by since.
$after = $repo->query(['since' => '2026-04-22T10:30:00Z']);
T::eq(1, $after['total'], 'since filter');

// Scoped lookups.
T::eq(1, count($repo->listForMigration('2026-04-22-rebrand')), 'listForMigration scoped');
T::eq(0, count($repo->listForMigration('nonexistent')), 'empty list for unknown migration');

// Counts by type (30 days).
$counts = $repo->countsByType(3650);
T::eq(1, $counts['playbook_start'] ?? 0, 'playbook_start count');
T::eq(1, $counts['task_changed'] ?? 0, 'task_changed count');
T::eq(1, $counts['migration_end'] ?? 0, 'migration_end count');

// Limit caps at 500 (and clamps 0 to 1).
$limited = $repo->query([], 10000);
T::eq(3, count($limited['items']), 'limit cap does not lose rows');

T::done('EventRepository');
