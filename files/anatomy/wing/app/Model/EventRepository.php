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
		'agent_run_start', 'agent_run_end',
		// Conductor-emitted introspection events (A8 + Phase 5, 2026-05-07).
		// agent_run_start/end bookend the runner's subprocess lifecycle;
		// these are what the conductor itself writes between them as it walks
		// through a Pulse-fired task. Without this whitelist the conductor
		// falls back to `task_ok` and loses semantic clarity in the audit
		// trail (caught during the 2026-05-07 first ceremony).
		'conductor_self_test_step', 'conductor_report',
		// Agent approval workflow (A11 — /approvals UI, 2026-05-07).
		//   agent_approval_request   — agent posts before high-blast-radius action
		//   agent_approval_decision  — operator clicks Approve / Reject in /approvals
		// Both share `actor_action_id` so a request + its decision pair via
		// `WHERE actor_action_id=?`. Decision payload carries
		// `result_json: {verdict: "approve"|"reject", operator_username, note}`.
		'agent_approval_request', 'agent_approval_decision',
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
			// Free-text attribution hint ("callback" / "operator" /
			// "agent:<n>") complementing A10 actor_id below.
			'source'           => $payload['source']           ?? null,
			// A10 actor audit (2026-05-08). actor_id = Authentik client_id
			// of the writer (operator / agent / plugin). actor_action_id =
			// UUID grouping events that belong to one logical action
			// (e.g. agent_run_start + agent_run_end emitted by the same
			// conductor pulse run share an actor_action_id with the
			// pulse_runs row). acted_at = wall-clock time of the action;
			// usually = ts but kept separate so backfilled rows can record
			// the original action time vs row insert time.
			'actor_id'         => $payload['actor_id']         ?? null,
			'actor_action_id'  => $payload['actor_action_id']  ?? null,
			'acted_at'         => $payload['acted_at']         ?? null,
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
		if (!empty($filters['actor_id'])) {
			$query->where('actor_id', $filters['actor_id']);
		}
		if (!empty($filters['actor_action_id'])) {
			$query->where('actor_action_id', $filters['actor_action_id']);
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
	 * List `agent_approval_request` events that have NOT yet been paired
	 * with an `agent_approval_decision` row (matched by actor_action_id).
	 * Newest first. Used by the /approvals UI (A11, 2026-05-07).
	 *
	 * @return array<int, array<string, mixed>>
	 */
	public function listPendingApprovals(int $limit = 50): array
	{
		$limit = max(1, min(200, $limit));
		// Subquery: actor_action_id values that already have a decision.
		$decided = $this->db->table('events')
			->where('type', 'agent_approval_decision')
			->select('actor_action_id');
		$decidedIds = [];
		foreach ($decided->fetchAll() as $row) {
			$decidedIds[$row->actor_action_id] = true;
		}

		$rows = [];
		foreach (
			$this->db->table('events')
				->where('type', 'agent_approval_request')
				->order('id DESC')
				->limit($limit)
				->fetchAll() as $row
		) {
			if (isset($decidedIds[$row->actor_action_id])) {
				continue;
			}
			$item = $row->toArray();
			if (!empty($item['result_json'])) {
				$item['result'] = json_decode($item['result_json'], true);
			}
			$rows[] = $item;
		}
		return $rows;
	}

	/**
	 * Recent decisions (last N), newest first. For the /approvals history
	 * panel beneath the pending queue.
	 *
	 * @return array<int, array<string, mixed>>
	 */
	public function listRecentDecisions(int $limit = 20): array
	{
		$limit = max(1, min(100, $limit));
		$rows = [];
		foreach (
			$this->db->table('events')
				->where('type', 'agent_approval_decision')
				->order('id DESC')
				->limit($limit)
				->fetchAll() as $row
		) {
			$item = $row->toArray();
			if (!empty($item['result_json'])) {
				$item['result'] = json_decode($item['result_json'], true);
			}
			$rows[] = $item;
		}
		return $rows;
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
