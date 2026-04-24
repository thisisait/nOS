<?php

declare(strict_types=1);

namespace App\Model;

use Nette\Database\Explorer;

/**
 * Patch read/write model.
 *
 * Patches are developer-authored remediation records (id = PATCH-NNN) stored
 * in the `patches` table. The apply/plan actions are dispatched to the BoxAPI
 * daemon (/api/patches/...) which shells out to ansible-playbook --tags
 * apply-patches. Apply history is mirrored into `patches_applied` via the
 * state_manager role so we can render a unified maintenance timeline alongside
 * upgrades_applied and migrations_applied.
 */
final class PatchRepository
{
	public function __construct(
		private Explorer $db,
		private BoneClient $box,
		private EventRepository $events,
	) {
	}


	/**
	 * List patches, optionally filtered. Filter keys: status, component_id, limit.
	 *
	 * @return array<int,array<string,mixed>>
	 */
	public function list(array $filter = []): array
	{
		$query = $this->db->table('patches')->order('created_at DESC');

		if (!empty($filter['status'])) {
			$query->where('status', $filter['status']);
		}
		if (!empty($filter['component_id'])) {
			$query->where('component_id', $filter['component_id']);
		}
		$limit = isset($filter['limit']) ? (int) $filter['limit'] : 0;
		if ($limit > 0) {
			$query->limit(max(1, min(500, $limit)));
		}

		$rows = [];
		foreach ($query->fetchAll() as $row) {
			$rows[] = $row->toArray();
		}
		return $rows;
	}


	/**
	 * Single patch by id, or null if missing.
	 *
	 * @return array<string,mixed>|null
	 */
	public function getById(string $id): ?array
	{
		$row = $this->db->table('patches')->where('id', $id)->fetch();
		return $row ? $row->toArray() : null;
	}


	/**
	 * Count patches in a given status. Used by dashboard maintenance block.
	 */
	public function statusCount(string $status): int
	{
		return $this->db->table('patches')->where('status', $status)->count('*');
	}


	/**
	 * Create a new patch. Auto-generates PATCH-NNN id if not provided.
	 */
	public function create(array $data): void
	{
		if (empty($data['id'])) {
			$data['id'] = $this->getNextId();
		}

		$this->db->table('patches')->insert($data);
	}


	/**
	 * Update an existing patch.
	 */
	public function update(string $id, array $data): void
	{
		$data['updated_at'] = (new \DateTimeImmutable)->format('Y-m-d H:i:s');

		$this->db->table('patches')
			->where('id', $id)
			->update($data);
	}


	/**
	 * Past patch applications (local mirror from state_manager push).
	 *
	 * @return array<int,array<string,mixed>>
	 */
	public function history(?string $patchId = null, ?string $componentId = null, int $limit = 50): array
	{
		$query = $this->db->table('patches_applied')
			->order('applied_at DESC')
			->limit(max(1, min(500, $limit)));

		if ($patchId !== null) {
			$query->where('patch_id', $patchId);
		}
		if ($componentId !== null) {
			$query->where('component_id', $componentId);
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


	/**
	 * Upsert a patch-applied history row. Called by StatePresenter::actionSync
	 * when state_manager pushes the updated ~/.nos/state.yml patches_applied[].
	 *
	 * Idempotent: if a row with the same (patch_id, applied_at) already exists
	 * we return its id without re-inserting. This lets Glasswing re-sync from
	 * BoxAPI freely without creating duplicate timeline entries.
	 *
	 * Returns the row id (newly inserted or existing).
	 */
	public function recordApplied(array $record): int
	{
		$patchId   = (string) ($record['patch_id']   ?? $record['id'] ?? '');
		$appliedAt = (string) ($record['applied_at'] ?? gmdate('c'));

		if ($patchId !== '') {
			$existing = $this->db->table('patches_applied')
				->where('patch_id', $patchId)
				->where('applied_at', $appliedAt)
				->fetch();
			if ($existing) {
				return (int) $existing['id'];
			}
		}

		$row = [
			'patch_id'        => $patchId,
			'component_id'    => $record['component_id'] ?? null,
			'finding_ref'     => $record['finding_ref']  ?? null,
			'applied_at'      => $appliedAt,
			'success'         => !empty($record['success']) ? 1 : 0,
			'duration_sec'    => isset($record['duration_sec']) ? (int) $record['duration_sec'] : null,
			'rolled_back'     => !empty($record['rolled_back']) ? 1 : 0,
			'event_run_id'    => $record['event_run_id'] ?? null,
			'raw_record_json' => json_encode($record),
		];
		$this->db->table('patches_applied')->insert($row);
		return (int) $this->db->getConnection()->getPdo()->lastInsertId();
	}


	/** Events tied to a patch_id (chronological). */
	public function getEventsFor(string $patchId): array
	{
		return $this->events->listForPatch($patchId);
	}


	/** BoxAPI passthrough — dry-run plan (ansible-playbook --tags apply-patches + check). */
	public function plan(string $id): array
	{
		return $this->box->post('/api/patches/' . rawurlencode($id) . '/plan');
	}


	/** BoxAPI passthrough — real apply. */
	public function apply(string $id): array
	{
		return $this->box->post('/api/patches/' . rawurlencode($id) . '/apply');
	}


	/**
	 * Get the next PATCH-NNN id.
	 */
	private function getNextId(): string
	{
		$maxId = $this->db->table('patches')
			->select('MAX(CAST(SUBSTR(id, 7) AS INTEGER)) AS max_num')
			->fetch();

		$nextNum = ($maxId && $maxId['max_num'] !== null)
			? ((int) $maxId['max_num'] + 1)
			: 1;

		return sprintf('PATCH-%03d', $nextNum);
	}
}
