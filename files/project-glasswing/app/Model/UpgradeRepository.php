<?php

declare(strict_types=1);

namespace App\Model;

use Nette\Database\Explorer;

/**
 * Upgrade read model.
 *
 * Static recipes live in upgrades/*.yml (agent 6). Live version/state comes
 * from BoxAPI. History mirror is `upgrades_applied` in SQLite.
 */
final class UpgradeRepository
{
	public function __construct(
		private Explorer $db,
		private BoxApiClient $box,
		private EventRepository $events,
	) {
	}

	/**
	 * Full matrix of services — installed vs stable vs latest vs recipe.
	 *
	 * @return array<int,array<string,mixed>>
	 */
	public function matrix(): array
	{
		$resp = $this->box->get('/api/upgrades');
		if ($resp['status'] >= 400 || !is_array($resp['body'])) {
			return [];
		}
		return $resp['body']['services'] ?? [];
	}

	/**
	 * All recipes for a given service.
	 */
	public function forService(string $service): ?array
	{
		$resp = $this->box->get('/api/upgrades/' . rawurlencode($service));
		if ($resp['status'] >= 400 || !is_array($resp['body'])) {
			return null;
		}
		return $resp['body'];
	}

	/**
	 * Single recipe detail.
	 */
	public function getRecipe(string $service, string $recipeId): ?array
	{
		$resp = $this->box->get(
			'/api/upgrades/' . rawurlencode($service) . '/' . rawurlencode($recipeId),
		);
		if ($resp['status'] >= 400 || !is_array($resp['body'])) {
			return null;
		}
		return $resp['body'];
	}

	/** Past upgrades for a service (local mirror). */
	public function history(?string $service = null, int $limit = 50): array
	{
		$query = $this->db->table('upgrades_applied')->order('applied_at DESC')->limit($limit);
		if ($service !== null) {
			$query->where('service', $service);
		}
		$out = [];
		foreach ($query->fetchAll() as $row) {
			$item = $row->toArray();
			if (!empty($item['raw_record_json'])) {
				$item['record'] = json_decode($item['raw_record_json'], true);
			}
			$out[] = $item;
		}
		return $out;
	}

	/** Append an upgrade history row. */
	public function recordApplied(array $record): int
	{
		$row = [
			'service'         => (string) ($record['service']      ?? ''),
			'recipe_id'       => (string) ($record['recipe_id']    ?? ''),
			'from_version'    => $record['from_version'] ?? null,
			'to_version'      => $record['to_version']   ?? null,
			'severity'        => $record['severity']     ?? null,
			'applied_at'      => (string) ($record['applied_at']   ?? gmdate('c')),
			'success'         => !empty($record['success']) ? 1 : 0,
			'duration_sec'    => isset($record['duration_sec']) ? (int) $record['duration_sec'] : null,
			'rolled_back'     => !empty($record['rolled_back']) ? 1 : 0,
			'event_run_id'    => $record['event_run_id'] ?? null,
			'raw_record_json' => json_encode($record),
		];
		$this->db->table('upgrades_applied')->insert($row);
		return (int) $this->db->getConnection()->getPdo()->lastInsertId();
	}

	/** Events tied to an upgrade_id. */
	public function getEventsFor(string $upgradeId): array
	{
		return $this->events->listForUpgrade($upgradeId);
	}

	/** BoxAPI passthroughs. */
	public function plan(string $service, string $recipeId): array
	{
		return $this->box->post(
			'/api/upgrades/' . rawurlencode($service) . '/' . rawurlencode($recipeId) . '/plan',
		);
	}

	public function apply(string $service, string $recipeId): array
	{
		return $this->box->post(
			'/api/upgrades/' . rawurlencode($service) . '/' . rawurlencode($recipeId) . '/apply',
		);
	}
}
