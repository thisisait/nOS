<?php

declare(strict_types=1);

namespace App\Model;

use Nette\Database\Explorer;

/**
 * migrations_authored read+write model (Phase B / B3, §2.1 + §3.3).
 *
 * The recipe→migration promotion record — the hub joining the three islands
 * (recipe, migration, coexistence). Distinct from `migrations_applied` (the
 * runtime execution mirror): this is the AUTHORING / review artifact the
 * migration-author agent produces and the operator reviews on the local forge.
 *
 * GATE 2 boundary: `merged` / `committed_sha` are reachable ONLY via the forge
 * merge (webhook or migration-pr.sh --mark-merged). Wing only ever writes
 * `in_review` / `rejected` through setReviewStatus(); no Wing API can flip a row
 * to `merged`. The producer (POST /api/v1/migrations/authored) inserts at
 * `draft`.
 */
final class MigrationAuthoredRepository
{
	public function __construct(
		private Explorer $db,
	) {
	}

	/**
	 * All authored-migration proposals for a service, newest first.
	 *
	 * @return array<int,array<string,mixed>>
	 */
	public function forService(string $service): array
	{
		$out = [];
		foreach ($this->db->table('migrations_authored')
			->where('service', $service)->order('created_at DESC') as $r) {
			$out[] = $r->toArray();
		}
		return $out;
	}

	/**
	 * Open proposals awaiting operator review (the /migrations "Proposed" column
	 * + the per-service Proposals strip). Excludes terminal states (merged /
	 * rejected / superseded).
	 *
	 * @return array<int,array<string,mixed>>
	 */
	public function listReviewable(): array
	{
		$out = [];
		foreach ($this->db->table('migrations_authored')
			->where('review_status', ['draft', 'in_review'])->order('created_at DESC') as $r) {
			$out[] = $r->toArray();
		}
		return $out;
	}

	/** Single proposal by uuid (lineage deep-link target). */
	public function getByUuid(string $uuid): ?array
	{
		$row = $this->db->table('migrations_authored')->where('uuid', $uuid)->fetch();
		return $row !== null ? $row->toArray() : null;
	}

	/**
	 * True when a merged migration exists for (service,recipe) — the
	 * G-PROVISION-MIGRATED prerequisite the plan-choice surfaces and the
	 * coexistence consumer enforces (a coexist track cannot provision until the
	 * migration MR is operator-merged on the local forge, GATE 2).
	 */
	public function hasMerged(string $service, string $recipeId): bool
	{
		return $this->db->table('migrations_authored')
			->where('service', $service)->where('recipe_id', $recipeId)
			->where('review_status', 'merged')->count('*') > 0;
	}

	/**
	 * Insert a draft proposal (the producer path — POST /api/v1/migrations/authored).
	 *
	 * $authorAgent / $actorId are the anti-spoof identity the PRESENTER derives
	 * from the bearer token (never body-supplied), mirroring actionQueue. The row
	 * lands at review_status='draft'; the delete-prior trick keeps the
	 * UNIQUE(service,recipe_id,review_status) constraint from tripping when a
	 * stale draft for the same (service,recipe) already exists (re-author flips
	 * it the same way markPlannedApplied() does for the planned queues).
	 *
	 * @param array<string,mixed> $fields service/recipe_id/title required;
	 *        migration_id/plan_mode/from_version/to_version/severity/artifact_kind/
	 *        artifact_path/forge/mr_url/forge_branch/session_uuid optional.
	 * @return array{ok:bool, status:string, detail:string, id:int|null, uuid:string}
	 */
	public function insertAuthored(array $fields, string $authorAgent, string $actorId): array
	{
		$service = (string) ($fields['service'] ?? '');
		$recipeId = (string) ($fields['recipe_id'] ?? '');
		$title = (string) ($fields['title'] ?? '');
		if ($service === '' || $recipeId === '' || $title === '') {
			return ['ok' => false, 'status' => 'invalid', 'detail' => 'service, recipe_id and title are required', 'id' => null, 'uuid' => ''];
		}

		// session_uuid doubles as the row uuid + actor_action_id (A14 lineage:
		// SELECT WHERE actor_action_id=? reconstructs the authoring run). Fall
		// back to a fresh UUID4 if the producer didn't pass a session.
		$sessionUuid = (isset($fields['session_uuid']) && is_string($fields['session_uuid']) && $fields['session_uuid'] !== '')
			? $fields['session_uuid']
			: $this->uuid4();

		// Drop any prior draft/in_review for the same (service,recipe) — the
		// delete-prior flip so the new authoring supersedes the stale one without
		// a UNIQUE(service,recipe_id,review_status) collision.
		$this->db->table('migrations_authored')
			->where('service', $service)->where('recipe_id', $recipeId)
			->where('review_status', ['draft', 'in_review'])->delete();

		$this->db->table('migrations_authored')->insert([
			'uuid'            => $sessionUuid,
			'service'         => $service,
			'recipe_id'       => $recipeId,
			'migration_id'    => $fields['migration_id']  ?? null,
			'plan_mode'       => (isset($fields['plan_mode']) && $fields['plan_mode'] === 'coexist') ? 'coexist' : 'migration',
			'from_version'    => $fields['from_version']   ?? null,
			'to_version'      => $fields['to_version']     ?? null,
			'severity'        => $fields['severity']       ?? null,
			'title'           => $title,
			'artifact_kind'   => (isset($fields['artifact_kind']) && is_string($fields['artifact_kind']) && $fields['artifact_kind'] !== '')
				? $fields['artifact_kind'] : 'migration_yaml',
			'artifact_path'   => $fields['artifact_path']  ?? null,
			'forge'           => $fields['forge']          ?? null,
			'mr_url'          => $fields['mr_url']          ?? null,
			'forge_branch'    => $fields['forge_branch']    ?? null,
			'review_status'   => 'draft',
			'author_agent'    => $authorAgent,
			'session_uuid'    => $sessionUuid,
			'actor_id'        => $actorId,
			'actor_action_id' => $sessionUuid,
		]);
		$id = (int) $this->db->getConnection()->getPdo()->lastInsertId();
		return ['ok' => true, 'status' => 'authored', 'detail' => 'draft authored', 'id' => $id, 'uuid' => $sessionUuid];
	}

	/**
	 * Operator review transition — Wing may ONLY set in_review or rejected.
	 * `merged` is the forge-merge's (GATE 2) exclusive write, never Wing's, so
	 * this method hard-refuses any other target.
	 *
	 * @return array{ok:bool, status:string, detail:string}
	 */
	public function setReviewStatus(int $id, string $status, ?string $rejectedReason = null): array
	{
		if (!in_array($status, ['in_review', 'rejected'], true)) {
			return ['ok' => false, 'status' => 'forbidden', 'detail' => "Wing may only set in_review / rejected; '{$status}' is the forge's write"];
		}
		$row = $this->db->table('migrations_authored')->where('id', $id)->fetch();
		if ($row === null) {
			return ['ok' => false, 'status' => 'not_found', 'detail' => 'no such authored migration'];
		}
		$update = ['review_status' => $status, 'updated_at' => gmdate('c')];
		if ($status === 'rejected') {
			$update['rejected_reason'] = $rejectedReason;
		}
		$this->db->table('migrations_authored')->where('id', $id)->update($update);
		return ['ok' => true, 'status' => $status, 'detail' => 'review status updated'];
	}

	/**
	 * The forge-merge write (GATE 2) — the ONLY path to review_status='merged'.
	 *
	 * Deliberately SEPARATE from setReviewStatus() (which hard-refuses 'merged'):
	 * `merged` + `committed_sha` are reachable only after the operator merges the
	 * local-forge MR. No Wing UI / API can reach this — it is driven exclusively
	 * by the PULL path (tools/migration-pr.sh --mark-merged → bin/promote-migration.php,
	 * or the next-deploy ingest pass). §7-Q1: PULL model (no inbound forge webhook).
	 *
	 * Idempotent + UNIQUE-safe: the UNIQUE(service, recipe_id, review_status) index
	 * means a second merged row for the same (service,recipe) would collide, so we
	 * delete-prior any stale 'merged' row for that pair first (the same trick
	 * insertAuthored() uses for draft/in_review). A re-run on an already-merged row
	 * is a no-op that simply re-stamps committed_sha/updated_at.
	 *
	 * @return array{ok:bool, status:string, detail:string, id:int|null,
	 *         uuid:string, service:string, recipe_id:string, migration_id:string|null,
	 *         migration_uuid:string, committed_sha:string,
	 *         applied_migration_id:string|null, already_merged:bool}
	 */
	public function markMerged(int $id, string $committedSha, ?string $appliedMigrationId = null): array
	{
		$row = $this->db->table('migrations_authored')->where('id', $id)->fetch();
		if ($row === null) {
			return [
				'ok' => false, 'status' => 'not_found', 'detail' => 'no such authored migration',
				'id' => null, 'uuid' => '', 'service' => '', 'recipe_id' => '',
				'migration_id' => null, 'migration_uuid' => '', 'committed_sha' => '',
				'applied_migration_id' => null, 'already_merged' => false,
			];
		}
		$service = (string) $row->service;
		$recipeId = (string) $row->recipe_id;
		$alreadyMerged = ((string) $row->review_status === 'merged');

		// Drop any OTHER stale 'merged' row for the same (service,recipe) so the
		// flip doesn't trip UNIQUE(service,recipe_id,review_status). Never delete
		// the row we are about to update (id != this).
		if (!$alreadyMerged) {
			$this->db->table('migrations_authored')
				->where('service', $service)->where('recipe_id', $recipeId)
				->where('review_status', 'merged')->where('id != ?', $id)->delete();
		}

		$update = [
			'review_status' => 'merged',
			'committed_sha' => $committedSha,
			'updated_at'    => gmdate('c'),
		];
		if ($appliedMigrationId !== null && $appliedMigrationId !== '') {
			$update['applied_migration_id'] = $appliedMigrationId;
		}
		$this->db->table('migrations_authored')->where('id', $id)->update($update);

		return [
			'ok' => true,
			'status' => 'merged',
			'detail' => $alreadyMerged ? 'already merged — committed_sha re-stamped' : 'review status flipped to merged',
			'id' => $id,
			'uuid' => (string) $row->uuid,
			'service' => $service,
			'recipe_id' => $recipeId,
			'migration_id' => $row->migration_id !== null ? (string) $row->migration_id : null,
			'migration_uuid' => (string) $row->uuid,
			'committed_sha' => $committedSha,
			'applied_migration_id' => $appliedMigrationId !== null && $appliedMigrationId !== '' ? $appliedMigrationId : null,
			'already_merged' => $alreadyMerged,
		];
	}

	/** RFC-4122 v4 UUID (matches the AgentKit / invitations uuid idiom). */
	private function uuid4(): string
	{
		$data = random_bytes(16);
		$data[6] = chr((ord($data[6]) & 0x0f) | 0x40);
		$data[8] = chr((ord($data[8]) & 0x3f) | 0x80);
		return vsprintf('%s%s-%s-%s-%s-%s%s%s', str_split(bin2hex($data), 4));
	}
}
