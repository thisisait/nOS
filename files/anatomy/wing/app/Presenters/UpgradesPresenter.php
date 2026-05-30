<?php

declare(strict_types=1);

namespace App\Presenters;

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

		// The template iterates $matrix (was a latent var mismatch: the
		// presenter only set $services, so /upgrades always showed the
		// empty-state). Set both; $matrix is the one the template reads.
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
