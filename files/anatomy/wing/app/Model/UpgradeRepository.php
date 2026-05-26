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
		private BoneClient $box,
		private EventRepository $events,
	) {
	}

	/**
	 * Full matrix of services — installed vs target vs recipe vs planned.
	 *
	 * W5-B1 (2026-05-26): built offline from the local upgrade_recipes catalog
	 * (ingested from upgrades/*.yml) joined to systems (best-effort installed
	 * version) and upgrades_planned (queued upgrades). Was a Bone /api/upgrades
	 * proxy that 401'd (HMAC vs the endpoint's JWT-scope gate) → empty matrix.
	 *
	 * @return array<int,array<string,mixed>>
	 */
	public function matrix(): array
	{
		// Recipe catalog grouped by service (target version DESC → [0] is latest).
		$recipes = [];
		foreach ($this->db->table('upgrade_recipes')->order('service ASC, to_version DESC') as $r) {
			$recipes[$r->service][] = $r->toArray();
		}
		// Queued upgrades, keyed by service.
		$planned = [];
		foreach ($this->db->table('upgrades_planned')->where('status', 'planned') as $p) {
			$planned[$p->service] = $p->toArray();
		}
		// Installed versions, best-effort from the systems registry.
		$installed = [];
		foreach ($this->db->table('systems') as $s) {
			$key = strtolower(str_replace([' ', '_', '-'], '', (string) $s->name));
			$installed[$key] = (string) ($s->version ?? '');
		}

		$out = [];
		foreach ($recipes as $service => $svcRecipes) {
			$latest = $svcRecipes[0];
			$instKey = strtolower(str_replace([' ', '_', '-'], '', (string) $service));
			$inst = null;
			foreach ($installed as $k => $v) {
				if ($v !== '' && ($k === $instKey || str_contains($k, $instKey) || str_contains($instKey, $k))) {
					$inst = $v;
					break;
				}
			}
			$sev = $latest['severity'] ?? 'minor';
			$sevClass = match ($sev) {
				'breaking'             => 'breaking',
				'security', 'critical' => 'critical',
				'patch', 'minor'       => 'minor',
				default                => 'unknown',
			};
			$target = $latest['to_version'] ?? null;
			$out[] = [
				'id'               => $service,
				'service'          => $service,
				'category'         => null,
				'installed'        => $inst,
				'installed_class'  => $inst !== null ? 'current' : 'unknown',
				'stable'           => $target,
				'stable_class'     => $sevClass,
				'latest'           => $target,
				'latest_class'     => $sevClass,
				'upstream'         => null,        // offline matrix — no upstream scanner (B1 decision)
				'upstream_class'   => 'unknown',
				'severity'         => $sev,
				'recipe_available' => true,
				'recipe_count'     => count($svcRecipes),
				'recipes'          => $svcRecipes,
				'planned'          => isset($planned[$service]),
				'planned_target'   => $planned[$service]['target_version'] ?? null,
				'planned_by'       => $planned[$service]['planned_by'] ?? null,
			];
		}
		return $out;
	}

	/**
	 * Planned (queued) upgrades. status defaults to 'planned'.
	 *
	 * @return array<int,array<string,mixed>>
	 */
	public function listPlanned(string $status = 'planned'): array
	{
		$out = [];
		foreach ($this->db->table('upgrades_planned')->where('status', $status)->order('planned_at DESC') as $r) {
			$out[] = $r->toArray();
		}
		return $out;
	}

	/**
	 * Queue an upgrade as planned (idempotent on service+recipe+status).
	 * planned_by carries the attribution (operator / agent name).
	 */
	public function planUpgrade(string $service, string $recipeId, ?string $targetVersion, string $plannedBy, ?string $notes = null): bool
	{
		$exists = $this->db->table('upgrades_planned')
			->where('service', $service)
			->where('recipe_id', $recipeId)
			->where('status', 'planned')
			->fetch();
		if ($exists) {
			return false; // already queued
		}
		$this->db->table('upgrades_planned')->insert([
			'service'        => $service,
			'recipe_id'      => $recipeId,
			'target_version' => $targetVersion,
			'planned_by'     => $plannedBy,
			'status'         => 'planned',
			'notes'          => $notes,
		]);
		return true;
	}

	/** Mark a queued upgrade as applied (called by the upgrade-engine). */
	public function markPlannedApplied(string $service, string $recipeId): void
	{
		$this->db->table('upgrades_planned')
			->where('service', $service)
			->where('recipe_id', $recipeId)
			->where('status', 'planned')
			->update(['status' => 'applied', 'applied_at' => gmdate('c')]);
	}

	/** Cancel a queued upgrade. */
	public function cancelPlanned(int $id): void
	{
		$this->db->table('upgrades_planned')
			->where('id', $id)
			->where('status', 'planned')
			->update(['status' => 'cancelled']);
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
