<?php

declare(strict_types=1);

namespace App\Presenters\Api;

use App\Model\CoexistenceRepository;
use App\Model\EventRepository;

/**
 * Dual-version coexistence orchestrator — provision / cutover / cleanup tracks.
 *
 * GET  /api/v1/coexistence                              — list tracks per service
 * POST /api/v1/coexistence/<service>/provision          — spin up a second track on shifted port
 * POST /api/v1/coexistence/<service>/cutover            — atomic switch to target_tag
 * POST /api/v1/coexistence/<service>/promote            — toggle-as-primary (reversible)  [B3]
 * POST /api/v1/coexistence/<service>/deactivate         — stop a non-primary track        [B3]
 * POST /api/v1/coexistence/<service>/cancel             — dequeue a planned provision      [B3]
 * POST /api/v1/coexistence/<service>/cleanup/<tag>      — tear down stale track (force flag)
 */
final class CoexistencePresenter extends BaseApiPresenter
{
	public function __construct(
		private CoexistenceRepository $coexistence,
		private EventRepository $events,
	) {
	}

	public function actionDefault(): void
	{
		$this->requireMethod('GET');
		$this->sendSuccess(['services' => $this->coexistence->allTracks()]);
	}

	public function actionProvision(string $service): void
	{
		$this->requireMethod('POST');
		$body = $this->getJsonBody();
		if (empty($body['tag']) || empty($body['version'])) {
			$this->sendError('tag and version are required');
		}
		$this->proxyBoxApi($this->coexistence->provision($service, $body));
	}

	/**
	 * POST /api/v1/coexistence/<service>/queue — queue a coexistence provision
	 * (W5-B5). The --tags coexistence consumer applies it. planned_by is the
	 * validated bearer identity (never body-supplied) to prevent spoofing.
	 */
	public function actionQueue(string $service): void
	{
		$this->requireMethod('POST');
		$body = $this->getJsonBody();
		if (isset($body['planned_by'])) {
			$this->sendError('planned_by is derived from the bearer token identity, not the body', 400);
		}
		$plannedBy = $this->getActorId() ?: 'api';
		$tag = (isset($body['tag']) && is_string($body['tag']) && $body['tag'] !== '') ? $body['tag'] : 'new';
		$portOffset = (int) ($body['port_offset'] ?? 10);
		$version = (isset($body['target_version']) && is_string($body['target_version'])) ? $body['target_version'] : null;
		$reason = (isset($body['reason']) && is_string($body['reason'])) ? $body['reason'] : null;
		$result = $this->coexistence->planCoexistence($service, $tag, $portOffset, $plannedBy, $version, $reason);
		$this->sendSuccess([
			'queued'     => $result['ok'],
			'status'     => $result['status'],
			'service'    => $service,
			'tag'        => $tag,
			'planned_by' => $plannedBy,
			'note'       => $result['ok'] ? 'queued — applied under: ansible-playbook main.yml --tags coexistence' : $result['detail'],
		]);
	}

	/** GET /api/v1/coexistence/planned — the planned-coexistence queue. */
	public function actionPlanned(): void
	{
		$this->requireMethod('GET');
		$this->sendSuccess(['planned' => $this->coexistence->listPlanned()]);
	}

	public function actionCutover(string $service): void
	{
		$this->requireMethod('POST');
		$body = $this->getJsonBody();
		if (empty($body['target_tag'])) {
			$this->sendError('target_tag is required');
		}
		$this->proxyBoxApi($this->coexistence->cutover($service, (string) $body['target_tag']));
	}

	/**
	 * POST /api/v1/coexistence/<service>/promote — toggle-as-primary (B3 §5).
	 * Reversible cutover: flips active_track + role atomically (the prior primary
	 * is demoted in the same Bone txn). dry_run defaults TRUE (mutating verb).
	 * Identity is NEVER body-supplied (anti-spoof, same gate as actionQueue).
	 */
	public function actionPromote(string $service): void
	{
		$this->requireMethod('POST');
		$body = $this->getJsonBody();
		if (isset($body['actor_id'])) {
			$this->sendError('actor_id is derived from the bearer token identity, not the body', 400);
		}
		if (empty($body['tag'])) {
			$this->sendError('tag is required');
		}
		$tag = (string) $body['tag'];
		$dryRun = array_key_exists('dry_run', $body) ? (bool) $body['dry_run'] : true;
		$ttlSeconds = (isset($body['ttl_seconds']) && is_int($body['ttl_seconds'])) ? $body['ttl_seconds'] : null;
		$resp = $this->coexistence->promote($service, $tag, $dryRun, $ttlSeconds);
		if (!$dryRun && (int) ($resp['status'] ?? 502) < 400) {
			$this->emit('coexistence_promote', $service, $tag, [
				'coexistence_service' => $service,
				'to_tag'              => $tag,
				'dry_run'             => false,
			]);
		}
		$this->proxyBoxApi($resp);
	}

	/**
	 * POST /api/v1/coexistence/<service>/deactivate — stop a non-primary track
	 * (B3 §5). docker compose stop (data + override kept). Bone refuses the
	 * active primary unless force AND a failover target exists. dry_run TRUE
	 * default. Identity never body-supplied.
	 */
	public function actionDeactivate(string $service): void
	{
		$this->requireMethod('POST');
		$body = $this->getJsonBody();
		if (isset($body['actor_id'])) {
			$this->sendError('actor_id is derived from the bearer token identity, not the body', 400);
		}
		if (empty($body['tag'])) {
			$this->sendError('tag is required');
		}
		$tag = (string) $body['tag'];
		$force = !empty($body['force']);
		$dryRun = array_key_exists('dry_run', $body) ? (bool) $body['dry_run'] : true;
		$resp = $this->coexistence->deactivate($service, $tag, $force, $dryRun);
		if (!$dryRun && (int) ($resp['status'] ?? 502) < 400) {
			$this->emit('coexistence_demote', $service, $tag, [
				'coexistence_service' => $service,
				'tag'                 => $tag,
				'from_role'           => 'secondary',
				'to_role'             => 'deactivated',
			]);
		}
		$this->proxyBoxApi($resp);
	}

	/**
	 * POST /api/v1/coexistence/<service>/cancel — dequeue a planned provision
	 * (B3 §5). Wing-DB only: NO Bone route, NO host mutation (a queued row was
	 * never provisioned). Refuses when there is no planned row. Identity (the
	 * cancelled_by attribution) is the bearer token, never body-supplied.
	 */
	public function actionCancel(string $service): void
	{
		$this->requireMethod('POST');
		$body = $this->getJsonBody();
		if (isset($body['cancelled_by'])) {
			$this->sendError('cancelled_by is derived from the bearer token identity, not the body', 400);
		}
		if (empty($body['tag'])) {
			$this->sendError('tag is required');
		}
		$tag = (string) $body['tag'];
		$cancelledBy = $this->getActorId() ?: 'api';
		$result = $this->coexistence->cancelPlanned($service, $tag, $cancelledBy);
		if (!$result['ok']) {
			$this->sendError($result['detail'], 409);
		}
		$this->emit('coexistence_cancel', $service, $tag, [
			'coexistence_service' => $service,
			'tag'                 => $tag,
			'reason'              => (isset($body['reason']) && is_string($body['reason'])) ? $body['reason'] : 'operator cancel',
		]);
		$this->sendSuccess([
			'cancelled'    => true,
			'service'      => $service,
			'tag'          => $tag,
			'cancelled_by' => $cancelledBy,
		]);
	}

	public function actionCleanup(string $service, string $tag): void
	{
		$this->requireMethod('POST');
		$body = $this->getJsonBody();
		$force = !empty($body['force']);
		$this->proxyBoxApi($this->coexistence->cleanup($service, $tag, $force));
	}

	/**
	 * Best-effort audit emit (coexist_svc-keyed). Never blocks the action —
	 * EventRepository maps payload['coexistence_service'] → coexist_svc.
	 *
	 * @param array<string,mixed> $result
	 */
	private function emit(string $type, string $service, string $tag, array $result): void
	{
		try {
			$this->events->insert([
				'type'            => $type,
				'task'            => $type . ': ' . $service . '/' . $tag,
				'source'          => 'wing',
				'actor_id'        => $this->getActorId(),
				'result'          => $result,
			]);
		} catch (\Throwable) {
			// audit failure must not block the lifecycle action.
		}
	}

	private function proxyBoxApi(array $resp): never
	{
		$status = (int) ($resp['status'] ?? 502);
		$body = $resp['body'] ?? ['error' => 'empty response from BoxAPI'];
		$this->getHttpResponse()->setCode($status);
		$this->sendJson(is_array($body) ? $body : ['body' => $body]);
	}
}
