<?php
/**
 * UpgradeRepository — history insert + query + event scoping.
 */

declare(strict_types=1);

require __DIR__ . '/bootstrap.php';

use App\Model\BoneClient;
use App\Model\CoexistenceRepository;
use App\Model\EventRepository;
use App\Model\UpgradeRepository;

final class DeadBox extends BoneClient
{
	public function __construct() { parent::__construct('http://127.0.0.1:1', null, 1); }
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
$coexistence = new CoexistenceRepository($exp, new DeadBox());
$repo = new UpgradeRepository($exp, new DeadBox(), $events, $coexistence);

// matrix degrades gracefully when there are no recipes (empty catalog).
T::eq([], $repo->matrix(), 'matrix falls back to empty');

// F4: forService() builds from the LOCAL upgrade_recipes catalog, not a live
// Bone call. With an empty catalog AND a dead Bone it returns null (notFound).
T::eq(null, $repo->forService('grafana'), 'forService returns null when no recipes exist');

// Seed the local recipe catalog — the SAME offline source matrix() reads. The
// detail page MUST render these even though Bone is down (the F4 bug: forService
// sourced from Bone → empty page despite a populated catalog).
$exp->table('upgrade_recipes')->insert([
	'service'               => 'grafana',
	'recipe_id'             => 'grafana-11-to-12',
	'from_pattern'          => '^11\\.',
	'to_version'            => '12.0.0',
	'severity'              => 'breaking',
	'docs_url'              => 'https://grafana.com/changelog/12',
	'title'                 => 'Grafana 11 → 12 (breaking)',
	'coexistence_supported' => 1,
]);
$exp->table('upgrade_recipes')->insert([
	'service'               => 'grafana',
	'recipe_id'             => 'grafana-10-to-11',
	'from_pattern'          => '^10\\.',
	'to_version'            => '11.5.0',
	'severity'              => 'minor',
	'docs_url'              => 'https://grafana.com/changelog/11',
	'title'                 => 'Grafana 10 → 11',
	'coexistence_supported' => 0,
]);

$fs = $repo->forService('grafana');
T::truthy(is_array($fs), 'forService returns the catalog payload (Bone is DOWN)');
T::eq('grafana', $fs['service'] ?? null, 'forService payload carries the service');
T::eq(2, count($fs['recipes'] ?? []), 'forService surfaces BOTH local recipes despite a dead Bone');
// Ordered to_version DESC → [0] is the latest target (12.0.0 before 11.5.0).
T::eq('grafana-11-to-12', $fs['recipes'][0]['id'] ?? null, 'recipes ordered to_version DESC ([0] = latest)');
// Each card carries the keys service.latte renders.
$r0 = $fs['recipes'][0];
T::eq('12.0.0', $r0['to'] ?? null, 'recipe maps to_version → to');
T::eq('^11\\.', $r0['from_regex'] ?? null, 'recipe maps from_pattern → from_regex');
T::eq('breaking', $r0['severity'] ?? null, 'recipe carries severity');
T::truthy(!empty($r0['coexistence_supported']), 'recipe carries coexistence_supported');
T::eq(false, $r0['applied'] ?? null, 'recipe not yet applied');
T::eq('https://grafana.com/changelog/12', $fs['docs_url'] ?? null, 'docs_url from the recipe rows');

// forService remains service-scoped (a different service → its own / no recipes).
T::eq(null, $repo->forService('redis'), 'forService null for a service with no recipes');

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
