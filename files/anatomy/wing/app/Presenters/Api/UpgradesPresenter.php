<?php

declare(strict_types=1);

namespace App\Presenters\Api;

use App\Model\EventRepository;
use App\Model\MigrationAuthoredRepository;
use App\Model\UpgradeRepository;

/**
 * GET  /api/v1/upgrades                          — matrix of services with available upgrade recipes
 * GET  /api/v1/upgrades/{service}                — list recipes for a single service
 * GET  /api/v1/upgrades/{service}/{recipe}       — single recipe detail (steps + breaking_boundaries)
 * POST /api/v1/upgrades/{service}/{recipe}/plan  — dry-run a recipe; returns the plan + diff
 * POST /api/v1/upgrades/{service}/{recipe}/plan-choice — plan-choice branch: migration vs coexist  [B3]
 * POST /api/v1/upgrades/{service}/{recipe}/apply — execute a recipe; returns run_id + tail
 * GET  /api/v1/upgrades/history                  — local history mirror (filterable by service)
 */
final class UpgradesPresenter extends BaseApiPresenter
{
	public function __construct(
		private UpgradeRepository $upgrades,
		private MigrationAuthoredRepository $authored,
		private EventRepository $events,
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
	 * POST /api/v1/upgrades/{service}/{recipe}/apply-detached — Phase-4
	 * plan->detached. The operator chose run_mode=detached (or a session_risk
	 * recipe was routed here). Bone launches nos-upgrade-detached.sh so the run
	 * survives the operator's session dying mid-upgrade.
	 */
	public function actionApplyDetached(string $service, string $recipe): void
	{
		$this->requireMethod('POST');
		$this->proxyBoxApi($this->upgrades->applyDetached($service, $recipe));
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

	/**
	 * POST /api/v1/upgrades/{service}/{recipe}/plan-choice — the plan-choice
	 * branch point (B3 §3.1/§5). The operator (or a Tier-1 browser form) picks:
	 *   (a) plan_mode='migration' → in-place, no track
	 *   (b) plan_mode='coexist'   → coexisting new version with a data copy
	 *
	 * dry_run defaults TRUE: the first POST returns the would-create rows + the
	 * migration-prereq status (is there a merged migrations_authored?) WITHOUT
	 * inserting. The operator confirms with dry_run=false to commit.
	 *
	 * planned_by is ALWAYS the validated bearer identity (never body-supplied),
	 * the same anti-spoof gate as actionQueue. Emits plan_choice_recorded on a
	 * real (non-dry-run) write.
	 */
	public function actionPlanChoice(string $service, string $recipe): void
	{
		$this->requireMethod('POST');
		$body = $this->getJsonBody();
		if (isset($body['planned_by'])) {
			$this->sendError('planned_by is derived from the bearer token identity, not the request body', 400);
		}
		$plannedBy = $this->getActorId() ?: 'api';
		$mode = (isset($body['plan_mode']) && $body['plan_mode'] === 'coexist') ? 'coexist' : 'migration';
		$target = (isset($body['target_version']) && is_string($body['target_version'])) ? $body['target_version'] : null;
		$portOffset = isset($body['port_offset']) && is_numeric($body['port_offset']) ? (int) $body['port_offset'] : 100;
		// data_source 'clone_from:<live>' or a bare flag both mean "with a copy".
		$dataCopy = array_key_exists('data_copy', $body)
			? (bool) $body['data_copy']
			: (array_key_exists('data_source', $body) ? $body['data_source'] !== null && $body['data_source'] !== '' : true);
		$force = !empty($body['force']);
		// dry_run DEFAULTS TRUE — must be explicitly false to commit.
		$dryRun = array_key_exists('dry_run', $body) ? (bool) $body['dry_run'] : true;

		// Migration-prereq: a coexist track can't provision until its linked
		// migration is merged (G-PROVISION-MIGRATED). Surface the status so the
		// operator sees the gate before committing.
		$migrationReady = $this->authored->hasMerged($service, $recipe);

		if ($dryRun) {
			$this->sendSuccess([
				'dry_run'          => true,
				'service'          => $service,
				'recipe'           => $recipe,
				'plan_mode'        => $mode,
				'would_create'     => $mode === 'coexist'
					? ['upgrades_planned (plan_mode=coexist)', 'coexistence_planned (data_copy=' . ($dataCopy ? 1 : 0) . ', port_offset=' . $portOffset . ')']
					: ['upgrades_planned (plan_mode=migration)'],
				'data_copy'        => $dataCopy,
				'port_offset'      => $portOffset,
				'migration_merged' => $migrationReady,
				'migration_note'   => $mode === 'coexist' && !$migrationReady
					? 'no merged migrations_authored yet — the coexistence track is blocked from provisioning until the migration MR is merged (GATE 2)'
					: null,
				'planned_by'       => $plannedBy,
				'note'             => 'dry-run — POST again with dry_run=false to commit',
			]);
		}

		$result = $this->upgrades->planUpgradeWithMode(
			$service, $recipe, $target, $plannedBy, $mode, $portOffset, $dataCopy, $force,
		);
		if ($result['status'] === 'mismatch') {
			$this->sendError($result['detail'], 409);
		}
		if ($result['ok']) {
			$this->emitPlanChoice($service, $recipe, $mode, $result, $dataCopy, $portOffset, $plannedBy);
		}
		$this->sendSuccess([
			'queued'                 => $result['ok'],
			'status'                 => $result['status'],
			'service'                => $service,
			'recipe'                 => $recipe,
			'plan_mode'              => $mode,
			'upgrade_id'             => $result['upgrade_id'] ?? null,
			'coexistence_planned_id' => $result['coexistence_planned_id'] ?? null,
			'data_copy'              => $dataCopy,
			'planned_by'             => $plannedBy,
			'note'                   => $result['ok']
				? ($mode === 'coexist'
					? 'queued — provision under: ansible-playbook main.yml --tags coexistence (after the migration MR is merged)'
					: 'queued — applied under: ansible-playbook main.yml --tags upgrade')
				: $result['detail'],
		]);
	}

	/**
	 * Best-effort plan_choice_recorded emit (upgrade_id-keyed §2.6). Never blocks.
	 *
	 * @param array<string,mixed> $result
	 */
	private function emitPlanChoice(string $service, string $recipe, string $mode, array $result, bool $dataCopy, int $portOffset, string $plannedBy): void
	{
		try {
			$this->events->insert([
				'type'            => 'plan_choice_recorded',
				'task'            => 'plan-choice ' . $mode . ': ' . $service . '/' . $recipe,
				'source'          => 'wing',
				'actor_id'        => $plannedBy,
				'upgrade_id'      => isset($result['upgrade_id']) ? (string) $result['upgrade_id'] : null,
				'result'          => [
					'service'                => $service,
					'recipe_id'              => $recipe,
					'plan_mode'              => $mode,
					'coexistence_planned_id' => $result['coexistence_planned_id'] ?? null,
					'data_copy'              => $dataCopy,
					'port_offset'            => $portOffset,
				],
			]);
		} catch (\Throwable) {
			// audit failure must not block the plan-choice write.
		}
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
