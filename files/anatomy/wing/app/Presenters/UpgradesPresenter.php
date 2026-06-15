<?php

declare(strict_types=1);

namespace App\Presenters;

use App\Model\EventRepository;
use App\Model\UpgradeRepository;

/**
 * /upgrades — matrix of services with upgrade availability.
 * /upgrades/<service> — recipes + history for a single service.
 */
final class UpgradesPresenter extends BasePresenter
{
	protected string $activeTab = 'upgrades';

	// RBAC: queuing an upgrade (actionQueueUpgrade) mutates upgrades_planned,
	// which the engine auto-applies under `--tags upgrade`. Tier-1 only — gated
	// by default in BasePresenter::startup() via this one property (matches the
	// forward-auth tier-1 boundary on wing.<tld>; defense-in-depth so a future
	// edge-config slip can't expose the queue to a lower tier).
	protected ?int $minAccessTier = 1;

	public function __construct(
		private UpgradeRepository $upgrades,
		private EventRepository $events,
	) {
	}

	/**
	 * Template vars:
	 *   services: list<array{
	 *     id:string, installed:?string, stable:?string, latest:?string,
	 *     severity:?string, recipe_available:bool
	 *   }>
	 *   countsBySeverity: array<string,int>
	 *   upgradeAvailable: int
	 */
	public function renderDefault(): void
	{
		$services = $this->upgrades->matrix();

		$counts = ['patch' => 0, 'minor' => 0, 'breaking' => 0];
		$available = 0;
		foreach ($services as $s) {
			if (!empty($s['recipe_available'])) {
				$available++;
			}
			$sev = $s['severity'] ?? null;
			if ($sev !== null && isset($counts[$sev])) {
				$counts[$sev]++;
			}
		}

		// $matrix is the variable the /upgrades template reads (both are set).
		$this->template->matrix = $services;
		$this->template->services = $services;
		$this->template->countsBySeverity = $counts;
		$this->template->upgradeAvailable = $available;
		$this->template->plannedCount = count($this->upgrades->listPlanned());
	}

	/**
	 * POST /upgrades/<service>/<recipe>/queue — operator queues an upgrade
	 * (W5-B2). Mirrors the bearer API but for the browser: CSRF-gated,
	 * planned_by is the forward-auth operator identity. The upgrade-engine
	 * applies the queue under --tags upgrade.
	 */
	public function actionQueueUpgrade(string $service, string $recipe): void
	{
		$this->requirePostMethod();
		$target = $this->getHttpRequest()->getPost('target_version');
		$force = (bool) $this->getHttpRequest()->getPost('force');
		$plannedBy = (string) ($this->getHttpRequest()->getHeader('X-Authentik-Username') ?? 'operator');
		$result = $this->upgrades->planUpgrade(
			$service,
			$recipe,
			is_string($target) && $target !== '' ? $target : null,
			$plannedBy !== '' ? $plannedBy : 'operator',
			null,
			$force,
		);
		[$msg, $type] = match ($result['status']) {
			'queued'         => ["Queued {$service}/{$recipe} — applies on: ansible-playbook main.yml --tags upgrade", 'success'],
			'already_queued' => ["{$service}/{$recipe} is already queued.", 'info'],
			'mismatch'       => ["Refused — {$result['detail']}", 'error'],
			default          => [$result['detail'], 'info'],
		};
		$this->flashMessage($msg, $type);
		$this->redirect('Upgrades:default');
	}

	/**
	 * POST /upgrades/<service>/<recipe>/plan-choice — the browser commit target
	 * for the plan-choice modal (B4b). The operator picks one of two paths in the
	 * modal, the hidden CSRF form posts here:
	 *   (a) plan_mode='migration' → in-place upgrade, no coexistence track
	 *   (b) plan_mode='coexist'   → coexisting new version with a data copy
	 *
	 * CSRF-gated (requirePostMethod); planned_by is the forward-auth operator
	 * identity (never body-supplied), matching actionQueueUpgrade. Reuses the same
	 * repo method as the bearer API (UpgradeRepository::planUpgradeWithMode) so the
	 * browser + agent paths write identical rows. Emits plan_choice_recorded
	 * (Wing-side EventRepository::insert directly, like UsersPresenter), then
	 * redirects to /coexistence (mode b) or /upgrades (mode a) with a flash —
	 * preserving the redirect+flash UX (no JSON, no fetch).
	 */
	public function actionPlanChoice(string $service, string $recipe): void
	{
		$this->requirePostMethod();
		$req = $this->getHttpRequest();
		$mode = $req->getPost('plan_mode') === 'coexist' ? 'coexist' : 'migration';
		$target = $req->getPost('target_version');
		$portOffsetRaw = $req->getPost('port_offset');
		$portOffset = is_numeric($portOffsetRaw) ? (int) $portOffsetRaw : 100;
		// data_copy defaults TRUE (path (b) means "with a copy of the data"); an
		// explicit '0'/'' unchecks it. Irrelevant for mode 'migration'.
		$dataCopyRaw = $req->getPost('data_copy');
		$dataCopy = $dataCopyRaw === null ? true : (bool) $dataCopyRaw;
		$force = (bool) $req->getPost('force');
		$plannedBy = (string) ($req->getHeader('X-Authentik-Username') ?? 'operator');
		$plannedBy = $plannedBy !== '' ? $plannedBy : 'operator';

		$result = $this->upgrades->planUpgradeWithMode(
			$service,
			$recipe,
			is_string($target) && $target !== '' ? $target : null,
			$plannedBy,
			$mode,
			$portOffset,
			$dataCopy,
			$force,
		);

		if (!empty($result['ok'])) {
			$this->emitPlanChoiceRecorded($service, $recipe, $mode, $result, $dataCopy, $portOffset, $plannedBy);
		}

		[$msg, $type] = match ($result['status']) {
			'queued'         => $mode === 'coexist'
				? ["Planned {$service}/{$recipe} — coexist track queued; provision under: ansible-playbook main.yml --tags coexistence (after the migration MR is merged).", 'success']
				: ["Planned {$service}/{$recipe} — applies on: ansible-playbook main.yml --tags upgrade.", 'success'],
			'already_queued' => ["{$service}/{$recipe} is already queued.", 'info'],
			'mismatch'       => ["Refused — {$result['detail']}", 'error'],
			default          => [$result['detail'] ?? 'No change.', 'info'],
		};
		$this->flashMessage($msg, $type);
		// Mode (b) lands on /coexistence where the queued track + primary/secondary
		// controls live; mode (a) stays on /upgrades.
		$this->redirect($mode === 'coexist' ? 'Coexistence:default' : 'Upgrades:default');
	}

	/**
	 * Best-effort plan_choice_recorded emit (upgrade_id-keyed §2.6 — mirrors the
	 * bearer Api\UpgradesPresenter::emitPlanChoice). Never blocks the plan-choice
	 * write: an audit failure must not abort the operator's action.
	 *
	 * @param array<string,mixed> $result
	 */
	private function emitPlanChoiceRecorded(string $service, string $recipe, string $mode, array $result, bool $dataCopy, int $portOffset, string $plannedBy): void
	{
		try {
			$this->events->insert([
				'type'       => 'plan_choice_recorded',
				'task'       => 'plan-choice ' . $mode . ': ' . $service . '/' . $recipe,
				'source'     => 'wing',
				'actor_id'   => $plannedBy,
				'upgrade_id' => isset($result['upgrade_id']) ? (string) $result['upgrade_id'] : null,
				'result'     => [
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

	/**
	 * Template vars:
	 *   service:  string
	 *   data:     array|null  — { service, docs_url, recipes: [...] } from BoxAPI
	 *   history:  list<array> — past applied upgrades for this service
	 *   notFound: bool
	 */
	public function renderService(string $service): void
	{
		$data = $this->upgrades->forService($service);
		$this->template->service = $service;
		$this->template->data = $data;
		$this->template->notFound = $data === null;
		$this->template->history = $this->upgrades->history($service);
	}
}
