<?php

declare(strict_types=1);

namespace App\Model;

use Nette\Database\Explorer;

final class ComponentRepository
{
	public function __construct(
		private Explorer $db,
	) {
	}


	/**
	 * List components with optional filters (category, stack, priority).
	 * Joins component_scan_state for scan status.
	 */
	public function list(array $filters): array
	{
		$query = $this->db->table('components')
			->order('priority DESC, name ASC');

		if (!empty($filters['category'])) {
			$query->where('category', $filters['category']);
		}
		if (!empty($filters['stack'])) {
			$query->where('stack', $filters['stack']);
		}
		if (!empty($filters['priority'])) {
			$query->where('priority', $filters['priority']);
		}

		$rows = [];
		foreach ($query->fetchAll() as $row) {
			$item = $row->toArray();

			$scanState = $this->db->table('component_scan_state')
				->where('component_id', $item['id'])
				->fetch();

			$item['scan_state'] = $scanState ? $scanState->toArray() : null;
			$rows[] = $item;
		}

		return $rows;
	}


	/**
	 * Get a single component by ID with its scan_state.
	 */
	public function get(string $id): ?array
	{
		$row = $this->db->table('components')
			->where('id', $id)
			->fetch();

		if (!$row) {
			return null;
		}

		$item = $row->toArray();

		$scanState = $this->db->table('component_scan_state')
			->where('component_id', $id)
			->fetch();

		$item['scan_state'] = $scanState ? $scanState->toArray() : null;

		return $item;
	}


	/**
	 * Create a new component.
	 */
	public function create(array $data): void
	{
		$this->db->table('components')->insert($data);
	}


	/**
	 * Update an existing component.
	 */
	public function update(string $id, array $data): void
	{
		$data['updated_at'] = (new \DateTimeImmutable)->format('Y-m-d H:i:s');

		$this->db->table('components')
			->where('id', $id)
			->update($data);
	}
}
