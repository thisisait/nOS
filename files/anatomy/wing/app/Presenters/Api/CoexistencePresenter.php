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
