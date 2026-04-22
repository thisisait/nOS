<?php

declare(strict_types=1);

namespace App\Presenters\Api;

use App\Model\UpgradeRepository;

/**
 * GET  /api/v1/upgrades                              — matrix
 * GET  /api/v1/upgrades/<service>                    — recipes for service
 * GET  /api/v1/upgrades/<service>/<recipe>           — single recipe detail
 * POST /api/v1/upgrades/<service>/<recipe>/plan
 * POST /api/v1/upgrades/<service>/<recipe>/apply
 * GET  /api/v1/upgrades/history[?service=X]          — local history mirror
 */
final class UpgradesPresenter extends BaseApiPresenter
{
	public function __construct(
		private UpgradeRepository $upgrades,
	) {
	}

	public function actionDefault(): void
	{
		$this->requireMethod('GET');
		$this->sendSuccess(['services' => $this->upgrades->matrix()]);
	}

	public function actionService(string $service): void
	{
		$this->requireMethod('GET');
		$data = $this->upgrades->forService($service);
		if ($data === null) {
			$this->sendError('Service recipes not found', 404);
		}
		$this->sendSuccess($data);
	}

	public function actionRecipe(string $service, string $recipe): void
	{
		$method = $this->getMethod();
		if ($method === 'GET') {
			$data = $this->upgrades->getRecipe($service, $recipe);
			if ($data === null) {
				$this->sendError('Recipe not found', 404);
			}
			$this->sendSuccess($data);
		}
		$this->sendError('Method not allowed', 405);
	}

	public function actionPlan(string $service, string $recipe): void
	{
		$this->requireMethod('POST');
		$this->proxyBoxApi($this->upgrades->plan($service, $recipe));
	}

	public function actionApply(string $service, string $recipe): void
	{
		$this->requireMethod('POST');
		$this->proxyBoxApi($this->upgrades->apply($service, $recipe));
	}

	public function actionHistory(): void
	{
		$this->requireMethod('GET');
		$service = $this->getParameter('service');
		$limit   = (int) ($this->getParameter('limit') ?? 50);
		$this->sendSuccess([
			'items' => $this->upgrades->history(
				is_string($service) && $service !== '' ? $service : null,
				max(1, min(500, $limit)),
			),
		]);
	}

	private function proxyBoxApi(array $resp): never
	{
		$status = (int) ($resp['status'] ?? 502);
		$body = $resp['body'] ?? ['error' => 'empty response from BoxAPI'];
		$this->getHttpResponse()->setCode($status);
		$this->sendJson(is_array($body) ? $body : ['body' => $body]);
	}
}
