<?php

declare(strict_types=1);

namespace App\Presenters\Api;

use App\Model\UpgradeRepository;

/**
 * GET  /api/v1/upgrades                          — matrix of services with available upgrade recipes
 * GET  /api/v1/upgrades/{service}                — list recipes for a single service
 * GET  /api/v1/upgrades/{service}/{recipe}       — single recipe detail (steps + breaking_boundaries)
 * POST /api/v1/upgrades/{service}/{recipe}/plan  — dry-run a recipe; returns the plan + diff
 * POST /api/v1/upgrades/{service}/{recipe}/apply — execute a recipe; returns run_id + tail
 * GET  /api/v1/upgrades/history                  — local history mirror (filterable by service)
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

	/**
	 * POST /api/v1/upgrades/{service}/{recipe}/queue — queue an upgrade as
	 * planned (W5-B2). The upgrade-engine applies the queue under --tags
	 * upgrade. planned_by is ALWAYS the validated bearer-token identity
	 * (never body-supplied) to prevent attribution spoofing — same gate
	 * pattern as Gitleaks:resolve.
	 */
	public function actionQueue(string $service, string $recipe): void
	{
		$this->requireMethod('POST');
		$body = $this->getJsonBody();
		if (isset($body['planned_by'])) {
			$this->sendError('planned_by is derived from the bearer token identity, not the request body', 400);
		}
		$plannedBy = $this->getActorId() ?: 'api';
		$target = (isset($body['target_version']) && is_string($body['target_version'])) ? $body['target_version'] : null;
		$notes  = (isset($body['notes']) && is_string($body['notes'])) ? $body['notes'] : null;
		$force  = !empty($body['force']);
		$result = $this->upgrades->planUpgrade($service, $recipe, $target, $plannedBy, $notes, $force);
		// Mismatch guard: a recipe whose from_pattern doesn't match the
		// installed version is refused (409) unless force=true.
		if ($result['status'] === 'mismatch') {
			$this->sendError($result['detail'], 409);
		}
		$this->sendSuccess([
			'queued'     => $result['ok'],
			'status'     => $result['status'],
			'service'    => $service,
			'recipe'     => $recipe,
			'planned_by' => $plannedBy,
			'note'       => $result['ok'] ? 'queued — applied under: ansible-playbook main.yml --tags upgrade' : $result['detail'],
		]);
	}

	/** GET /api/v1/upgrades/planned — the planned-upgrade queue. */
	public function actionPlanned(): void
	{
		$this->requireMethod('GET');
		$this->sendSuccess(['planned' => $this->upgrades->listPlanned()]);
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
