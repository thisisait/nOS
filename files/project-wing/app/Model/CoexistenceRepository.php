<?php

declare(strict_types=1);

namespace App\Model;

use Nette\Database\Explorer;

/**
 * Dual-version (coexistence) track read model.
 *
 * Source of truth: ~/.nos/state.yml coexistence block, fetched via BoxAPI.
 * Local SQLite mirror (`coexistence_tracks`) is used when BoxAPI is down and
 * is kept in sync by state-push events.
 */
final class CoexistenceRepository
{
	public function __construct(
		private Explorer $db,
		private BoneClient $box,
	) {
	}

	/**
	 * Tracks grouped by service.
	 *
	 * @return array<string,array<int,array<string,mixed>>>
	 */
	public function allTracks(): array
	{
		$resp = $this->box->get('/api/coexistence');
		if ($resp['status'] < 400 && is_array($resp['body']) && isset($resp['body']['services'])) {
			return $resp['body']['services'];
		}

		// Fallback to local mirror.
		$out = [];
		foreach ($this->db->table('coexistence_tracks')->order('service ASC, tag ASC')->fetchAll() as $row) {
			$item = $row->toArray();
			$out[$item['service']][] = $item;
		}
		return $out;
	}

	/** Single service's tracks. */
	public function forService(string $service): array
	{
		$all = $this->allTracks();
		return $all[$service] ?? [];
	}

	/**
	 * Upsert a track row into the local mirror. Called when BoxAPI pushes a
	 * state snapshot.
	 */
	public function upsertTrack(string $service, array $track): void
	{
		$tag = (string) ($track['tag'] ?? '');
		if ($tag === '') {
			throw new \InvalidArgumentException('coexistence track missing tag');
		}

		$row = [
			'service'    => $service,
			'tag'        => $tag,
			'version'    => $track['version']   ?? null,
			'port'       => isset($track['port']) ? (int) $track['port'] : null,
			'data_path'  => $track['data_path'] ?? null,
			'active'     => !empty($track['active']) ? 1 : 0,
			'read_only'  => !empty($track['read_only']) ? 1 : 0,
			'started_at' => $track['started_at'] ?? null,
			'cutover_at' => $track['cutover_at'] ?? null,
			'ttl_until'  => $track['ttl_until']  ?? null,
			'updated_at' => gmdate('Y-m-d H:i:s'),
		];

		$existing = $this->db->table('coexistence_tracks')
			->where('service', $service)
			->where('tag', $tag)
			->fetch();

		if ($existing) {
			$this->db->table('coexistence_tracks')
				->where('service', $service)
				->where('tag', $tag)
				->update($row);
		} else {
			$this->db->table('coexistence_tracks')->insert($row);
		}
	}

	/** Drop a track from the local mirror. */
	public function removeTrack(string $service, string $tag): void
	{
		$this->db->table('coexistence_tracks')
			->where('service', $service)
			->where('tag', $tag)
			->delete();
	}

	/**
	 * Count services that have a coexistence scenario mid-flight: more than
	 * one track and at least one inactive (i.e. waiting for a cutover or a
	 * post-cutover cleanup). Reads the local mirror only, so cheap enough
	 * for the dashboard summary.
	 */
	public function pendingCutoverCount(): int
	{
		$rows = $this->db->query(
			'SELECT service, COUNT(*) AS n, SUM(active) AS active_count
			 FROM coexistence_tracks
			 GROUP BY service
			 HAVING n > 1 AND active_count < n',
		)->fetchAll();
		return count($rows);
	}

	// BoxAPI passthroughs.

	public function provision(string $service, array $body): array
	{
		return $this->box->post('/api/coexistence/' . rawurlencode($service) . '/provision', $body);
	}

	public function cutover(string $service, string $targetTag): array
	{
		return $this->box->post(
			'/api/coexistence/' . rawurlencode($service) . '/cutover',
			['target_tag' => $targetTag],
		);
	}

	public function cleanup(string $service, string $tag, bool $force = false): array
	{
		return $this->box->post(
			'/api/coexistence/' . rawurlencode($service) . '/cleanup/' . rawurlencode($tag),
			['force' => $force],
		);
	}
}
