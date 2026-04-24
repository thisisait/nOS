<?php
/**
 * UpgradeRepository — history insert + query + event scoping.
 */

declare(strict_types=1);

require __DIR__ . '/bootstrap.php';

use App\Model\BoneClient;
use App\Model\EventRepository;
use App\Model\UpgradeRepository;

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
$repo = new UpgradeRepository($exp, new DeadBox(), $events);

// matrix/for_service degrade gracefully when BoxAPI is down.
T::eq([], $repo->matrix(), 'matrix falls back to empty');
T::eq(null, $repo->forService('grafana'), 'forService returns null on BoxAPI outage');

// Insert history rows.
$id = $repo->recordApplied([
	'service'      => 'grafana',
	'recipe_id'    => 'grafana-11-to-12',
	'from_version' => '11.5.0',
	'to_version'   => '12.0.0',
	'severity'     => 'breaking',
	'applied_at'   => '2026-04-22T13:00:00Z',
	'success'      => true,
	'duration_sec' => 45,
	'event_run_id' => 'run_gf',
]);
T::truthy($id > 0, 'recordApplied returns id');

// Unsuccessful + rolled-back row.
$repo->recordApplied([
	'service'      => 'grafana',
	'recipe_id'    => 'grafana-11-to-12',
	'from_version' => '11.5.0',
	'to_version'   => '12.0.0',
	'severity'     => 'breaking',
	'applied_at'   => '2026-04-22T14:00:00Z',
	'success'      => false,
	'rolled_back'  => true,
]);
// Different service.
$repo->recordApplied([
	'service'      => 'redis',
	'recipe_id'    => 'redis-7-to-8',
	'applied_at'   => '2026-04-22T15:00:00Z',
	'success'      => true,
]);

$all = $repo->history();
T::eq(3, count($all), 'three history rows');
T::eq('redis', $all[0]['service'], 'history ordered newest first');

$grafana = $repo->history('grafana');
T::eq(2, count($grafana), 'filter by service');

// Event scoping.
$events->insert([
	'ts' => '2026-04-22T13:00:00Z',
	'run_id' => 'run_gf',
	'type' => 'upgrade_end',
	'upgrade_id' => 'grafana-11-to-12',
]);
T::eq(1, count($repo->getEventsFor('grafana-11-to-12')), 'events scoped to upgrade');

T::done('UpgradeRepository');
