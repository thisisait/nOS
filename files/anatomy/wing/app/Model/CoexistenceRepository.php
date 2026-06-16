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

	// ── Planned-coexistence queue (W5-B5) ────────────────────────────────────
	// The upgrade-architect agent queues a parallel-track provision for a
	// breaking upgrade; the --tags coexistence consumer applies it.

	/** @return array<int,array<string,mixed>> */
	public function listPlanned(string $status = 'planned'): array
	{
		$out = [];
		foreach ($this->db->table('coexistence_planned')->where('status', $status)->order('planned_at DESC') as $r) {
			$out[] = $r->toArray();
		}
		return $out;
	}

	/**
	 * Queue a coexistence provision (idempotent on service+tag+status).
	 * planned_by is the validated caller identity (attribution).
	 *
	 * B3 (Phase B): the trailing $parentUpgradeId / $dataCopy / $sourceMigrationUuid
	 * args wire the plan-choice link. They default to "no link" so every existing
	 * caller (Api\CoexistencePresenter::actionQueue, the architect path) keeps its
	 * five-arg signature unchanged; UpgradeRepository::planUpgradeWithMode passes
	 * them when the operator picks path-(b) "coexisting with data copy".
	 *
	 * @return array{ok:bool, status:string, detail:string, id:int|null}
	 */
	public function planCoexistence(
		string $service,
		string $tag,
		int $portOffset,
		string $plannedBy,
		?string $targetVersion = null,
		?string $reason = null,
		?int $parentUpgradeId = null,
		bool $dataCopy = true,
		?string $sourceMigrationUuid = null
	): array {
		$exists = $this->db->table('coexistence_planned')
			->where('service', $service)->where('tag', $tag)->where('status', 'planned')->fetch();
		if ($exists) {
			return ['ok' => false, 'status' => 'already_queued', 'detail' => 'already queued', 'id' => (int) $exists->id];
		}
		$this->db->table('coexistence_planned')->insert([
			'service'               => $service,
			'tag'                   => $tag,
			'target_version'        => $targetVersion,
			'port_offset'           => $portOffset,
			'reason'                => $reason,
			'planned_by'            => $plannedBy,
			'status'                => 'planned',
			'parent_upgrade_id'     => $parentUpgradeId,
			'source_migration_uuid' => $sourceMigrationUuid,
			'data_copy'             => $dataCopy ? 1 : 0,
		]);
		$id = (int) $this->db->getConnection()->getPdo()->lastInsertId();
		return ['ok' => true, 'status' => 'queued', 'detail' => 'queued', 'id' => $id];
	}

	/**
	 * Cancel a queued (status='planned') coexistence provision — the missing
	 * dequeue (the 'cancelled' enum value was documented but never written).
	 *
	 * Pure Wing-DB op, NO host mutation: a queued row was never provisioned, so
	 * there is no container/override/vhost to tear down (that is the destructive
	 * cleanup path with its own guards). Refuses (ok=false) when there is no
	 * matching 'planned' row. Uses the same delete-prior trick as
	 * markPlannedApplied so a prior 'cancelled' marker can't trip the
	 * UNIQUE(service,tag,status) constraint.
	 *
	 * @return array{ok:bool, status:string, detail:string}
	 */
	public function cancelPlanned(string $service, string $tag, string $cancelledBy): array
	{
		$planned = $this->db->table('coexistence_planned')
			->where('service', $service)->where('tag', $tag)->where('status', 'planned')->fetch();
		if ($planned === null) {
			return ['ok' => false, 'status' => 'not_queued', 'detail' => 'no planned coexistence row to cancel'];
		}
		// Drop any prior terminal 'cancelled' marker first — UNIQUE(service,tag,status).
		$this->db->table('coexistence_planned')
			->where('service', $service)->where('tag', $tag)->where('status', 'cancelled')->delete();
		$this->db->table('coexistence_planned')
			->where('service', $service)->where('tag', $tag)->where('status', 'planned')
			->update([
				'status'       => 'cancelled',
				'cancelled_at' => gmdate('c'),
				'cancelled_by' => $cancelledBy,
			]);
		return ['ok' => true, 'status' => 'cancelled', 'detail' => 'cancelled'];
	}

	/** Mark a queued coexistence provision applied (delete-prior avoids the UNIQUE collision). */
	public function markPlannedApplied(string $service, string $tag): void
	{
		$this->db->table('coexistence_planned')
			->where('service', $service)->where('tag', $tag)->where('status', 'applied')->delete();
		$this->db->table('coexistence_planned')
			->where('service', $service)->where('tag', $tag)->where('status', 'planned')
			->update(['status' => 'applied', 'applied_at' => gmdate('c')]);
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

	/**
	 * Toggle-as-primary — the reversible operator cutover (B3 → Bone B2 route).
	 * dry_run defaults TRUE (mutating verb): the first call plans, dry_run=false
	 * commits. Bone's promote_track flips active_track + role atomically (demotes
	 * the prior primary in the same txn → the single-primary index never trips).
	 */
	public function promote(string $service, string $tag, bool $dryRun = true, ?int $ttlSeconds = null): array
	{
		$body = ['dry_run' => $dryRun];
		if ($ttlSeconds !== null) {
			$body['ttl_seconds'] = $ttlSeconds;
		}
		return $this->box->post(
			'/api/coexistence/' . rawurlencode($service) . '/promote/' . rawurlencode($tag),
			$body,
		);
	}

	/**
	 * Deactivate a non-primary track (B3 → Bone B2 route): docker compose stop
	 * (NOT down — keeps the container, data, and override). dry_run defaults
	 * TRUE. Bone's deactivate_track refuses the active primary unless force AND a
	 * failover target exists (G-DEACTIVATE-NOT-PRIMARY).
	 */
	public function deactivate(string $service, string $tag, bool $force = false, bool $dryRun = true): array
	{
		return $this->box->post(
			'/api/coexistence/' . rawurlencode($service) . '/deactivate/' . rawurlencode($tag),
			['dry_run' => $dryRun, 'force' => $force],
		);
	}

	/**
	 * Manual, re-runnable "Copy data" into a secondary track (A4 / Q3 → Bone
	 * copy-data route). Runs the track's recorded migration data move
	 * (pg_dumpall → restore) into the SECONDARY's empty cluster, idempotently,
	 * then stamps data_copied_at. NO pointer flip — the operator re-runs it right
	 * before a promote to capture the latest data. dry_run defaults TRUE (the
	 * mutating verb); the committed move passes dry_run=false. Bone's copy_data
	 * refuses a track with no source_migration_id (G-COPY-HAS-MIGRATION) and
	 * refuses copying INTO the active primary (G-COPY-NOT-PRIMARY).
	 */
	public function copyData(string $service, string $tag, bool $dryRun = true): array
	{
		return $this->box->post(
			'/api/coexistence/' . rawurlencode($service) . '/copy-data/' . rawurlencode($tag),
			['dry_run' => $dryRun],
		);
	}
}
