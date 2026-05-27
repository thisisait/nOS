<?php

declare(strict_types=1);

namespace App\Presenters\Api;

use App\Model\CoexistenceRepository;

/**
 * Dual-version coexistence orchestrator — provision / cutover / cleanup tracks.
 *
 * GET  /api/v1/coexistence                              — list tracks per service
 * POST /api/v1/coexistence/<service>/provision          — spin up a second track on shifted port
 * POST /api/v1/coexistence/<service>/cutover            — atomic switch to target_tag
 * POST /api/v1/coexistence/<service>/cleanup/<tag>      — tear down stale track (force flag)
 */
final class CoexistencePresenter extends BaseApiPresenter
{
	public function __construct(
		private CoexistenceRepository $coexistence,
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

	public function actionCleanup(string $service, string $tag): void
	{
		$this->requireMethod('POST');
		$body = $this->getJsonBody();
		$force = !empty($body['force']);
		$this->proxyBoxApi($this->coexistence->cleanup($service, $tag, $force));
	}

	private function proxyBoxApi(array $resp): never
	{
		$status = (int) ($resp['status'] ?? 502);
		$body = $resp['body'] ?? ['error' => 'empty response from BoxAPI'];
		$this->getHttpResponse()->setCode($status);
		$this->sendJson(is_array($body) ? $body : ['body' => $body]);
	}
}
