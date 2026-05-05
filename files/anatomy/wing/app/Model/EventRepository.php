<?php

declare(strict_types=1);

namespace App\Model;

use Nette\Database\Explorer;

/**
 * Ansible callback events. Schema mirrors state/schema/event.schema.json.
 * All writes go through insert(); no PDO outside this class.
 */
final class EventRepository
{
	/** @var string[] Whitelisted event types (see event.schema.json). */
	public const VALID_TYPES = [
		'playbook_start', 'playbook_end',
		'play_start', 'play_end',
		'task_start', 'task_ok', 'task_changed', 'task_failed',
		'task_skipped', 'task_unreachable',
		'handler_start', 'handler_ok',
		'migration_start', 'migration_step_ok', 'migration_step_failed', 'migration_end',
		'upgrade_start', 'upgrade_step_ok', 'upgrade_end',
		'patch_start', 'patch_step_ok', 'patch_step_failed', 'patch_end',
		'coexistence_provision', 'coexistence_cutover', 'coexistence_cleanup',
	];

	public function __construct(
		private Explorer $db,
	) {
	}

	/**
	 * Insert an event row. Returns the new event id.
	 * Caller must have validated payload shape already.
	 */
	public function insert(array $payload): int
	{
		$row = [
			'ts'           => (string) ($payload['ts'] ?? gmdate('c')),
			'run_id'       => (string) ($payload['run_id'] ?? ''),
			'type'         => (string) ($payload['type'] ?? ''),
			'playbook'     => $payload['playbook']     ?? null,
			'play'         => $payload['play']         ?? null,
			'task'         => $payload['task']         ?? null,
			'role'         => $payload['role']         ?? null,
			'host'         => $payload['host']         ?? null,
			'duration_ms'  => isset($payload['duration_ms']) ? (int) $payload['duration_ms'] : null,
			'changed'      => array_key_exists('changed', $payload)
				? ((bool) $payload['changed'] ? 1 : 0)
				: null,
			'result_json'  => isset($payload['result']) && is_array($payload['result'])
				? json_encode($payload['result'])
				: null,
			'migration_id' => $payload['migration_id'] ?? null,
			'upgrade_id'   => $payload['upgrade_id']   ?? null,
			'patch_id'     => $payload['patch_id']     ?? null,
			'coexist_svc'  => $payload['coexistence_service'] ?? null,
			// Anatomy P1 (2026-05-05). Closes CLAUDE.md "Wing /events
			// schema mismatch" tech debt — Bone POST handler accepted
			// `source` in JSON but the INSERT silently dropped it.
			// Free-text attribution hint pre-A10 ("callback" / "operator"
			// / "agent:<n>"); A10 lands actor_id + actor_action_id for
			// cryptographic attribution.
			'source'       => $payload['source']       ?? null,
		];

		$this->db->table('events')->insert($row);
		return (int) $this->db->getConnection()->getPdo()->lastInsertId();
	}

	/**
	 * Query events with filters. Supports run_id, type, since (ISO-8601),
	 * migration_id, upgrade_id, coexist_svc. `limit` caps at 500.
	 *
	 * @return array{items: array<int,array<string,mixed>>, total: int}
	 */
	public function query(array $filters = [], int $limit = 100): array
	{
		$limit = max(1, min(500, $limit));
		$query = $this->db->table('events')->order('id DESC');

		if (!empty($filters['run_id'])) {
			$query->where('run_id', $filters['run_id']);
		}
		if (!empty($filters['type'])) {
			$query->where('type', $filters['type']);
		}
		if (!empty($filters['since'])) {
			$query->where('ts >= ?', $filters['since']);
		}
		if (!empty($filters['migration_id'])) {
			$query->where('migration_id', $filters['migration_id']);
		}
		if (!empty($filters['upgrade_id'])) {
			$query->where('upgrade_id', $filters['upgrade_id']);
		}
		if (!empty($filters['patch_id'])) {
			$query->where('patch_id', $filters['patch_id']);
		}
		if (!empty($filters['coexist_svc'])) {
			$query->where('coexist_svc', $filters['coexist_svc']);
		}
		if (!empty($filters['source'])) {
			$query->where('source', $filters['source']);
		}

		$total = (clone $query)->count('*');
		$query->limit($limit);

		$items = [];
		foreach ($query->fetchAll() as $row) {
			$item = $row->toArray();
			if (!empty($item['result_json'])) {
				$item['result'] = json_decode($item['result_json'], true);
			}
			$items[] = $item;
		}

		return ['items' => $items, 'total' => $total];
	}

	/**
	 * All events tied to a migration_id (chronological).
	 */
	public function listForMigration(string $migrationId): array
	{
		$items = [];
		foreach ($this->db->table('events')
			->where('migration_id', $migrationId)
			->order('id ASC')
			->fetchAll() as $row) {
			$item = $row->toArray();
			if (!empty($item['result_json'])) {
				$item['result'] = json_decode($item['result_json'], true);
			}
			$items[] = $item;
		}
		return $items;
	}

	/**
	 * All events tied to an upgrade_id (chronological).
	 */
	public function listForUpgrade(string $upgradeId): array
	{
		$items = [];
		foreach ($this->db->table('events')
			->where('upgrade_id', $upgradeId)
			->order('id ASC')
			->fetchAll() as $row) {
			$item = $row->toArray();
			if (!empty($item['result_json'])) {
				$item['result'] = json_decode($item['result_json'], true);
			}
			$items[] = $item;
		}
		return $items;
	}

	/**
	 * All events tied to a patch_id (chronological). Mirrors listForUpgrade.
	 */
	public function listForPatch(string $patchId): array
	{
		$items = [];
		foreach ($this->db->table('events')
			->where('patch_id', $patchId)
			->order('id ASC')
			->fetchAll() as $row) {
			$item = $row->toArray();
			if (!empty($item['result_json'])) {
				$item['result'] = json_decode($item['result_json'], true);
			}
			$items[] = $item;
		}
		return $items;
	}

	/**
	 * Aggregated counts by type over the last N days. Used for timeline badges.
	 *
	 * @return array<string,int>
	 */
	public function countsByType(int $days = 30): array
	{
		$since = (new \DateTimeImmutable("-{$days} days"))->format('Y-m-d\TH:i:s\Z');
		$out = [];
		foreach ($this->db->query(
			'SELECT type, COUNT(*) AS n FROM events WHERE ts >= ? GROUP BY type',
			$since,
		)->fetchAll() as $row) {
			$out[$row['type']] = (int) $row['n'];
		}
		return $out;
	}
}
