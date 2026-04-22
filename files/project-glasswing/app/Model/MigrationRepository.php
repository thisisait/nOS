<?php

declare(strict_types=1);

namespace App\Model;

use Nette\Database\Explorer;

/**
 * Migration read model.
 *
 * Static records live in migrations/*.yml on disk (agent 2's territory) — we
 * pull the live "applied" + "pending" split via BoxAPI which merges state.yml
 * with the on-disk migration definitions. The local SQLite mirror
 * (`migrations_applied`) is a cache updated by state-report pushes and by
 * callback-plugin migration events.
 */
final class MigrationRepository
{
	public function __construct(
		private Explorer $db,
		private BoxApiClient $box,
		private EventRepository $events,
	) {
	}

	/**
	 * List migrations pending (not yet applied, but eligible).
	 *
	 * @return array<int,array<string,mixed>>
	 */
	public function listPending(): array
	{
		$resp = $this->box->get('/api/migrations');
		if ($resp['status'] >= 400 || !is_array($resp['body'])) {
			return [];
		}
		return $resp['body']['pending'] ?? [];
	}

	/**
	 * List migrations already applied. Prefers BoxAPI (live state.yml); falls
	 * back to the local SQLite mirror if BoxAPI is unreachable.
	 *
	 * @return array<int,array<string,mixed>>
	 */
	public function listApplied(): array
	{
		$resp = $this->box->get('/api/migrations');
		if ($resp['status'] < 400 && is_array($resp['body']) && isset($resp['body']['applied'])) {
			return $resp['body']['applied'];
		}

		$out = [];
		foreach ($this->db->table('migrations_applied')
			->order('applied_at DESC')
			->fetchAll() as $row) {
			$item = $row->toArray();
			if (!empty($item['raw_record_json'])) {
				$item['record'] = json_decode($item['raw_record_json'], true);
			}
			$out[] = $item;
		}
		return $out;
	}

	/**
	 * Full record for a single migration by id, merging BoxAPI (static YAML +
	 * runtime status) with the local SQLite mirror.
	 */
	public function get(string $id): ?array
	{
		$resp = $this->box->get('/api/migrations/' . rawurlencode($id));
		if ($resp['status'] < 400 && is_array($resp['body'])) {
			return $resp['body'];
		}

		$row = $this->db->table('migrations_applied')->where('id', $id)->fetch();
		if (!$row) {
			return null;
		}
		$item = $row->toArray();
		if (!empty($item['raw_record_json'])) {
			$item['record'] = json_decode($item['raw_record_json'], true);
		}
		return $item;
	}

	/**
	 * Events tied to a migration (from callback plugin). Chronological.
	 */
	public function getEventsFor(string $id): array
	{
		return $this->events->listForMigration($id);
	}

	/**
	 * Upsert an applied migration into the local mirror. Called by
	 * Api\StatePresenter when BoxAPI pushes a state snapshot after a run.
	 */
	public function upsertApplied(array $record): void
	{
		$id = (string) ($record['id'] ?? '');
		if ($id === '') {
			throw new \InvalidArgumentException('migration record missing id');
		}

		$row = [
			'id'              => $id,
			'title'           => (string) ($record['title']    ?? $id),
			'severity'        => (string) ($record['severity'] ?? 'minor'),
			'applied_at'      => (string) ($record['at']       ?? gmdate('c')),
			'success'         => !empty($record['success']) ? 1 : 0,
			'duration_sec'    => isset($record['duration_sec']) ? (int) $record['duration_sec'] : null,
			'steps_applied'   => isset($record['steps_applied']) ? (int) $record['steps_applied'] : null,
			'steps_total'     => isset($record['steps_total'])   ? (int) $record['steps_total']   : null,
			'rolled_back_from'=> $record['rolled_back_from'] ?? null,
			'event_run_id'    => $record['event_run_id']     ?? null,
			'raw_record_json' => json_encode($record),
		];

		$existing = $this->db->table('migrations_applied')->where('id', $id)->fetch();
		if ($existing) {
			$this->db->table('migrations_applied')->where('id', $id)->update($row);
		} else {
			$this->db->table('migrations_applied')->insert($row);
		}
	}

	/** Delegates to BoxAPI for preview. */
	public function preview(string $id): array
	{
		return $this->box->post('/api/migrations/' . rawurlencode($id) . '/preview');
	}

	/** Delegates to BoxAPI for apply. */
	public function apply(string $id, bool $dryRun = false): array
	{
		return $this->box->post(
			'/api/migrations/' . rawurlencode($id) . '/apply',
			['dry_run' => $dryRun],
		);
	}

	/** Delegates to BoxAPI for rollback. */
	public function rollback(string $id): array
	{
		return $this->box->post('/api/migrations/' . rawurlencode($id) . '/rollback');
	}
}
