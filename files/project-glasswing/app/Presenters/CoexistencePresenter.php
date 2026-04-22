<?php

declare(strict_types=1);

namespace App\Presenters;

use App\Model\CoexistenceRepository;

/**
 * /coexistence — per-service dual-version tracks with status + cutover action.
 */
final class CoexistencePresenter extends BasePresenter
{
	protected string $activeTab = 'coexistence';

	public function __construct(
		private CoexistenceRepository $coexistence,
	) {
	}

	/**
	 * Template vars:
	 *   services:    array<string, list<array>>  — tracks grouped by service
	 *   totalTracks: int
	 *   serviceCount:int
	 *   now:         string  — ISO-8601 for TTL countdown rendering
	 */
	public function renderDefault(): void
	{
		$services = $this->coexistence->allTracks();

		$total = 0;
		foreach ($services as $tracks) {
			$total += count($tracks);
		}

		$this->template->services     = $services;
		$this->template->totalTracks  = $total;
		$this->template->serviceCount = count($services);
		$this->template->now          = gmdate('c');
	}
}
