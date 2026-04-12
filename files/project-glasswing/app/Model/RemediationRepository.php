<?php

declare(strict_types=1);

namespace App\Model;

use Nette\Database\Explorer;

final class RemediationRepository
{
	public function __construct(
		private Explorer $db,
	) {
	}


	/**
	 * List remediation items with optional filters (status, severity, component, limit).
	 * Returns ['items' => [...], 'total' => int].
	 */
	public function list(array $filters): array
	{
		$query = $this->db->table('remediation_items')
			->order('CASE severity
				WHEN "CRITICAL" THEN 1
				WHEN "HIGH" THEN 2
				WHEN "MEDIUM" THEN 3
				WHEN "LOW" THEN 4
				END, created_at DESC');

		if (!empty($filters['status'])) {
			$query->where('status', $filters['status']);
		}
		if (!empty($filters['severity'])) {
			$query->where('severity', $filters['severity']);
		}
		if (!empty($filters['component'])) {
			$query->where('component_id', $filters['component']);
		}

		$total = (clone $query)->count('*');

		$limit = isset($filters['limit']) ? (int) $filters['limit'] : 100;
		$query->limit($limit);

		$items = [];
		foreach ($query->fetchAll() as $row) {
			$items[] = $row->toArray();
		}

		return [
			'items' => $items,
			'total' => $total,
		];
	}


	/**
	 * Get a single remediation item by ID.
	 */
	public function get(string $id): ?array
	{
		$row = $this->db->table('remediation_items')
			->where('id', $id)
			->fetch();

		if (!$row) {
			return null;
		}

		return $row->toArray();
	}


	/**
	 * Create a new remediation item with auto-generated REM-NNN id.
	 * Throws on duplicate finding_ref.
	 */
	public function create(array $data): string
	{
		// Map 'component' alias to DB column 'component_id'
		if (isset($data['component']) && !isset($data['component_id'])) {
			$data['component_id'] = $data['component'];
			unset($data['component']);
		}

		// Use transaction to prevent race condition on ID generation
		$this->db->beginTransaction();
		try {
			if (!empty($data['finding_ref'])) {
				$existing = $this->db->table('remediation_items')
					->where('finding_ref', $data['finding_ref'])
					->fetch();

				if ($existing) {
					$this->db->rollBack();
					throw new \RuntimeException("Duplicate finding_ref: '{$data['finding_ref']}'.");
				}
			}

			if (empty($data['id'])) {
				$data['id'] = $this->getNextId();
			}

		// Whitelist allowed columns
		$allowed = ['id', 'finding_ref', 'component_id', 'severity', 'current_version',
			'fix_version', 'remediation_type', 'remediation_detail', 'status',
			'auto_fixable', 'source', 'confidence', 'found_at', 'scan_cycle'];
		$insert = array_intersect_key($data, array_flip($allowed));

		$this->db->table('remediation_items')->insert($insert);
			$this->db->commit();

			return $data['id'];
		} catch (\Throwable $e) {
			$this->db->rollBack();
			throw $e;
		}
	}


	/**
	 * Update a remediation item.
	 */
	public function update(string $id, array $data): void
	{
		$data['updated_at'] = (new \DateTimeImmutable)->format('Y-m-d H:i:s');

		$this->db->table('remediation_items')
			->where('id', $id)
			->update($data);
	}


	/**
	 * Bulk-update status for multiple remediation items.
	 * Returns number of items updated.
	 */
	public function bulkUpdateStatus(array $ids, string $status, ?string $resolvedBy = null): int
	{
		$updateData = [
			'status' => $status,
			'updated_at' => (new \DateTimeImmutable)->format('Y-m-d H:i:s'),
		];

		if ($status === 'resolved') {
			$updateData['resolved_at'] = (new \DateTimeImmutable)->format('Y-m-d H:i:s');
			if ($resolvedBy !== null) {
				$updateData['resolved_by'] = $resolvedBy;
			}
		}

		return $this->db->table('remediation_items')
			->where('id', $ids)
			->update($updateData);
	}


	/**
	 * Get the next REM-NNN id (highest existing + 1).
	 */
	public function getNextId(): string
	{
		$maxId = $this->db->table('remediation_items')
			->select('MAX(CAST(SUBSTR(id, 5) AS INTEGER)) AS max_num')
			->fetch();

		$nextNum = ($maxId && $maxId['max_num'] !== null)
			? ((int) $maxId['max_num'] + 1)
			: 1;

		return sprintf('REM-%03d', $nextNum);
	}
}
