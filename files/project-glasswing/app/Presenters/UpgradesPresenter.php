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

		$this->template->services = $services;
		$this->template->countsBySeverity = $counts;
		$this->template->upgradeAvailable = $available;
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
