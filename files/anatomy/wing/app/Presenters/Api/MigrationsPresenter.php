<?php

declare(strict_types=1);

namespace App\Presenters\Api;

use App\Model\EventRepository;
use App\Model\MigrationAuthoredRepository;
use App\Model\MigrationRepository;

/**
 * Migration catalog + lifecycle proxy — list / preview / apply / rollback.
 *
 * GET  /api/v1/migrations             — list { applied, pending } (via BoxAPI)
 * GET  /api/v1/migrations/<id>        — full record for one migration
 * POST /api/v1/migrations/authored    — migration-author producer: INSERT a
 *                                       draft migrations_authored row  [B3]
 * POST /api/v1/migrations/<id>/preview  — BoxAPI dry-run, returns plan diff
 * POST /api/v1/migrations/<id>/apply    — BoxAPI apply (honors body.dry_run)
 * POST /api/v1/migrations/<id>/rollback — BoxAPI rollback to previous state
 *
 * All proxy to BoxAPI. Bearer token required.
 */
final class MigrationsPresenter extends BaseApiPresenter
{
	public function __construct(
		private MigrationRepository $migrations,
		private MigrationAuthoredRepository $authored,
		private EventRepository $events,
	) {
	}

	public function actionDefault(?string $id = null): void
	{
		if ($id === null) {
			$this->requireMethod('GET');
			$this->sendSuccess([
				'pending' => $this->migrations->listPending(),
				'applied' => $this->migrations->listApplied(),
			]);
		}

		$this->requireMethod('GET');
		$rec = $this->migrations->get($id);
		if ($rec === null) {
			$this->sendError('Migration not found', 404);
		}
		$this->sendSuccess($rec);
	}

	/**
	 * POST /api/v1/migrations/authored — the migration-author producer (B3 §3.3,
	 * §5). INSERTs a draft migrations_authored row, replacing the lossy
	 * "draft into a conductor_report event" path.
	 *
	 * Anti-spoof: author_agent + actor_id are ALWAYS the validated bearer-token
	 * identity (never body-supplied) — same gate as Upgrades:queue. The forge MR
	 * is the real authority for the merge; this records the draft + emits the
	 * lineage events. Emits migration_authored, plus migration_pr_opened when the
	 * producer carried the mr_url (the MR is already open by the time the agent
	 * posts).
	 */
	public function actionAuthored(): void
	{
		$this->requireMethod('POST');
		$body = $this->getJsonBody();
		if (isset($body['author_agent']) || isset($body['actor_id'])) {
			$this->sendError('author_agent / actor_id are derived from the bearer token identity, not the body', 400);
		}
		$actorId = $this->getActorId() ?: 'api';
		// author_agent == actor_id minus the "agent:" prefix (schema §2.1).
		$authorAgent = str_starts_with($actorId, 'agent:') ? substr($actorId, 6) : $actorId;

		$result = $this->authored->insertAuthored($body, $authorAgent, $actorId);
		if (!$result['ok']) {
			$this->sendError($result['detail'], $result['status'] === 'invalid' ? 400 : 409);
		}

		$migrationUuid = $result['uuid'];
		$migrationId = (isset($body['migration_id']) && is_string($body['migration_id'])) ? $body['migration_id'] : $migrationUuid;
		$this->emitAuthored('migration_authored', $migrationId, $migrationUuid, $actorId, [
			'service'       => (string) ($body['service'] ?? ''),
			'recipe_id'     => (string) ($body['recipe_id'] ?? ''),
			'migration_uuid' => $migrationUuid,
			'artifact_kind' => (string) ($body['artifact_kind'] ?? 'migration_yaml'),
			'artifact_path' => $body['artifact_path'] ?? null,
			'from_version'  => $body['from_version'] ?? null,
			'to_version'    => $body['to_version'] ?? null,
		]);
		if (isset($body['mr_url']) && is_string($body['mr_url']) && $body['mr_url'] !== '') {
			$this->emitAuthored('migration_pr_opened', $migrationId, $migrationUuid, $actorId, [
				'migration_uuid' => $migrationUuid,
				'forge'        => $body['forge'] ?? 'gitlab',
				'mr_url'       => $body['mr_url'],
				'forge_branch' => $body['forge_branch'] ?? null,
			]);
		}

		$this->sendCreated([
			'authored'       => true,
			'uuid'           => $migrationUuid,
			'id'             => $result['id'],
			'review_status'  => 'draft',
			'author_agent'   => $authorAgent,
			'note'           => 'draft recorded — review + merge the MR on the local forge to reach merged (GATE 2)',
		]);
	}

	/**
	 * Best-effort migration_id-keyed audit emit. The migration_id col holds the
	 * uuid for these authoring events (§2.6). Never blocks the producer.
	 *
	 * @param array<string,mixed> $result
	 */
	private function emitAuthored(string $type, string $migrationId, string $actorActionId, string $actorId, array $result): void
	{
		try {
			$this->events->insert([
				'type'            => $type,
				'task'            => $type . ': ' . $migrationId,
				'source'          => 'wing',
				'migration_id'    => $migrationId,
				'actor_id'        => $actorId,
				'actor_action_id' => $actorActionId,
				'result'          => $result,
			]);
		} catch (\Throwable) {
			// audit failure must not block the authoring record.
		}
	}

	public function actionPreview(string $id): void
	{
		$this->requireMethod('POST');
		$resp = $this->migrations->preview($id);
		$this->proxyBoxApi($resp);
	}

	public function actionApply(string $id): void
	{
		$this->requireMethod('POST');
		$body = $this->getJsonBody();
		$dryRun = !empty($body['dry_run']);
		$resp = $this->migrations->apply($id, $dryRun);
		$this->proxyBoxApi($resp);
	}

	public function actionRollback(string $id): void
	{
		$this->requireMethod('POST');
		$resp = $this->migrations->rollback($id);
		$this->proxyBoxApi($resp);
	}

	/** Pass through BoxAPI status + body to the client. */
	private function proxyBoxApi(array $resp): never
	{
		$status = (int) ($resp['status'] ?? 502);
		$body = $resp['body'] ?? ['error' => 'empty response from BoxAPI'];
		$this->getHttpResponse()->setCode($status);
		$this->sendJson(is_array($body) ? $body : ['body' => $body]);
	}
}
