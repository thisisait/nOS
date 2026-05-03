<?php

declare(strict_types=1);

namespace App\Model;

use Nette\Database\Explorer;

final class ScanStateRepository
{
	public function __construct(
		private Explorer $db,
	) {
	}


	/**
	 * Get the current scan state: config + next_batch + attack_probes summary.
	 */
	public function getState(): array
	{
		$config = $this->db->table('scan_config')
			->where('id', 1)
			->fetch();

		$configArr = $config ? $config->toArray() : [];

		// Decode JSON column
		if (isset($configArr['next_batch'])) {
			$configArr['next_batch'] = json_decode($configArr['next_batch'], true) ?? [];
		}

		// Extract next_batch to top level for callers
		$nextBatch = $configArr['next_batch'] ?? [];

		$probes = [];
		foreach ($this->db->table('attack_probes')->order('cycle_mod ASC')->fetchAll() as $row) {
			$probes[] = $row->toArray();
		}

		// Latest cycle number from scan_cycles table
		$latestCycle = $this->db->table('scan_cycles')
			->select('MAX(cycle_number) AS max_cycle')
			->fetch();
		$latestCycleNum = ($latestCycle && $latestCycle['max_cycle'] !== null)
			? (int) $latestCycle['max_cycle'] : 0;

		return [
			'config' => $configArr,
			'next_batch' => $nextBatch,
			'latest_cycle' => $latestCycleNum,
			'attack_probes' => $probes,
		];
	}


	/**
	 * List scan cycles in descending order.
	 */
	public function getCycles(int $limit = 10): array
	{
		$rows = [];
		foreach ($this->db->table('scan_cycles')->order('cycle_number DESC')->limit($limit)->fetchAll() as $row) {
			$item = $row->toArray();

			// Decode JSON column
			if (isset($item['batch_components'])) {
				$item['batch_components'] = json_decode($item['batch_components'], true) ?? [];
			}

			$rows[] = $item;
		}

		return $rows;
	}


	/**
	 * Create a new scan cycle. Returns the cycle_number.
	 */
	public function createCycle(array $data): int
	{
		if (isset($data['batch_components']) && is_array($data['batch_components'])) {
			$data['batch_components'] = json_encode($data['batch_components']);
		}

		// Auto-generate cycle_number if not provided
		if (empty($data['cycle_number'])) {
			$max = $this->db->table('scan_cycles')
				->select('MAX(cycle_number) AS max_num')
				->fetch();
			$data['cycle_number'] = ($max && $max['max_num'] !== null)
				? ((int) $max['max_num'] + 1) : 1;
		}

		$this->db->table('scan_cycles')->insert($data);

		return (int) $data['cycle_number'];
	}


	/**
	 * Update a component's scan state.
	 */
	public function updateComponent(string $id, array $data): void
	{
		$existing = $this->db->table('component_scan_state')
			->where('component_id', $id)
			->fetch();

		if ($existing) {
			$this->db->table('component_scan_state')
				->where('component_id', $id)
				->update($data);
		} else {
			$data['component_id'] = $id;
			$this->db->table('component_scan_state')->insert($data);
		}
	}


	/**
	 * Update scan_config singleton.
	 */
	public function updateConfig(array $data): void
	{
		if (isset($data['next_batch']) && is_array($data['next_batch'])) {
			$data['next_batch'] = json_encode($data['next_batch']);
		}

		$this->db->table('scan_config')
			->where('id', 1)
			->update($data);
	}


	/**
	 * Set the next_batch rotation in scan_config.
	 */
	public function setRotation(array $nextBatch): void
	{
		$this->db->table('scan_config')
			->where('id', 1)
			->update(['next_batch' => json_encode($nextBatch)]);
	}


	/**
	 * Mark an attack probe as completed.
	 */
	public function completeProbe(string $name): void
	{
		$this->db->table('attack_probes')
			->where('name', $name)
			->update([
				'completed' => 1,
				'last_run' => (new \DateTimeImmutable)->format('Y-m-d H:i:s'),
			]);
	}
}
