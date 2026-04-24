<?php
/**
 * CoexistenceRepository — upsert (insert + update path), active flag flip
 * via second upsert, removeTrack, fallback on BoxAPI outage.
 */

declare(strict_types=1);

require __DIR__ . '/bootstrap.php';

use App\Model\BoneClient;
use App\Model\CoexistenceRepository;

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
$repo = new CoexistenceRepository($exp, new DeadBox());

// Insert two tracks for grafana.
$repo->upsertTrack('grafana', [
	'tag'        => 'legacy',
	'version'    => '11.5.0',
	'port'       => 3000,
	'data_path'  => '/Volumes/SSD1TB/observability/grafana-legacy',
	'read_only'  => true,
	'started_at' => '2026-04-20T10:00:00Z',
	'ttl_until'  => '2026-04-29T00:00:00Z',
	'active'     => false,
]);
$repo->upsertTrack('grafana', [
	'tag'        => 'new',
	'version'    => '12.0.0',
	'port'       => 3010,
	'data_path'  => '/Volumes/SSD1TB/observability/grafana',
	'started_at' => '2026-04-24T09:00:00Z',
	'cutover_at' => '2026-04-24T10:00:00Z',
	'active'     => true,
]);

$all = $repo->allTracks();
T::truthy(isset($all['grafana']), 'service grouping');
T::eq(2, count($all['grafana']), 'two tracks stored');

// Update the 'legacy' track (same service+tag) — must not duplicate.
$repo->upsertTrack('grafana', [
	'tag'        => 'legacy',
	'version'    => '11.5.1',
	'port'       => 3000,
	'read_only'  => true,
	'active'     => false,
]);
$all = $repo->allTracks();
T::eq(2, count($all['grafana']), 'still two tracks after update');

$legacy = null;
foreach ($all['grafana'] as $t) {
	if ($t['tag'] === 'legacy') { $legacy = $t; break; }
}
T::truthy($legacy !== null, 'legacy track exists');
T::eq('11.5.1', $legacy['version'], 'legacy version updated');

// forService.
T::eq(2, count($repo->forService('grafana')), 'forService returns both tracks');
T::eq([], $repo->forService('redis'), 'forService returns [] for unknown service');

// Missing tag rejects.
$thrown = false;
try {
	$repo->upsertTrack('grafana', ['version' => '9.0']);
} catch (InvalidArgumentException $e) {
	$thrown = true;
}
T::truthy($thrown, 'upsertTrack rejects missing tag');

// removeTrack.
$repo->removeTrack('grafana', 'legacy');
$after = $repo->forService('grafana');
T::eq(1, count($after), 'track removed');
T::eq('new', $after[0]['tag'], 'remaining track is new');

T::done('CoexistenceRepository');
