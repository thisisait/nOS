<?php

declare(strict_types=1);

namespace App\Model;

use Nette\Database\Explorer;

final class PatchRepository
{
	public function __construct(
		private Explorer $db,
	) {
	}


	/**
	 * List all patches.
	 */
	public function list(): array
	{
		$rows = [];
		foreach ($this->db->table('patches')->order('created_at DESC')->fetchAll() as $row) {
			$rows[] = $row->toArray();
		}

		return $rows;
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
