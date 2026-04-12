<?php

declare(strict_types=1);

namespace App\Model;

use Nette\Database\Explorer;

final class AdvisoryRepository
{
	public function __construct(
		private Explorer $db,
	) {
	}


	/**
	 * List advisories with optional filters (date, limit).
	 * Excludes full_text for listing performance.
	 */
	public function list(array $filters): array
	{
		$query = $this->db->table('advisories')
			->select('id, filename, title, date, has_critical, has_pentest, scan_cycle, created_at')
			->order('date DESC, id DESC');

		if (!empty($filters['date'])) {
			$query->where('date', $filters['date']);
		}

		$limit = isset($filters['limit']) ? (int) $filters['limit'] : 20;
		$query->limit($limit);

		$rows = [];
		foreach ($query->fetchAll() as $row) {
			$rows[] = $row->toArray();
		}

		return $rows;
	}


	/**
	 * Get a single advisory by ID (includes full_text).
	 */
	public function get(int $id): ?array
	{
		$row = $this->db->table('advisories')
			->where('id', $id)
			->fetch();

		if (!$row) {
			return null;
		}

		return $row->toArray();
	}


	/**
	 * Create a new advisory.
	 * Auto-extracts date from filename (YYYY-MM-DD pattern) and detects critical/pentest flags.
	 * Returns the inserted id.
	 */
	public function create(array $data): int
	{
		// Auto-extract date from filename if not provided
		if (empty($data['date']) && !empty($data['filename'])) {
			if (preg_match('/(\d{4}-\d{2}-\d{2})/', $data['filename'], $m)) {
				$data['date'] = $m[1];
			} else {
				$data['date'] = (new \DateTimeImmutable)->format('Y-m-d');
			}
		}

		// Auto-detect critical flag from full_text
		if (!isset($data['has_critical']) && !empty($data['full_text'])) {
			$data['has_critical'] = (int) (
				stripos($data['full_text'], 'CRITICAL') !== false
				|| stripos($data['full_text'], 'severity: critical') !== false
			);
		}

		// Auto-detect pentest flag from full_text
		if (!isset($data['has_pentest']) && !empty($data['full_text'])) {
			$data['has_pentest'] = (int) (
				stripos($data['full_text'], 'pentest') !== false
				|| stripos($data['full_text'], 'penetration') !== false
			);
		}

		$row = $this->db->table('advisories')->insert($data);

		return (int) $row['id'];
	}
}
