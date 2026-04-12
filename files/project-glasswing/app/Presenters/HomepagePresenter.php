<?php

declare(strict_types=1);

namespace App\Presenters;

use App\Model\ComponentRepository;
use App\Model\RemediationRepository;
use App\Model\PentestRepository;
use App\Model\ScanStateRepository;

/**
 * Public homepage — accessible without authentication.
 * Shows summary stats + login button.
 */
final class HomepagePresenter extends BasePresenter
{
	protected string $activeTab = '';

	public function __construct(
		private ComponentRepository $componentRepo,
		private RemediationRepository $remediationRepo,
		private PentestRepository $pentestRepo,
		private ScanStateRepository $scanRepo,
	) {
	}

	public function renderDefault(): void
	{
		$state = $this->scanRepo->getState();
		$components = $this->componentRepo->list([]);
		$remPending = $this->remediationRepo->list(['status' => 'pending', 'limit' => 1]);
		$remResolved = $this->remediationRepo->list(['status' => 'resolved', 'limit' => 1]);
		$targets = $this->pentestRepo->listTargets();

		$areasTested = 0;
		$areasPlanned = 0;
		foreach ($targets as $t) {
			$areasTested += $t['areas_tested_count'] ?? 0;
			$areasPlanned += $t['areas_planned_count'] ?? 0;
		}
		$areasTotal = $areasTested + $areasPlanned;

		$this->template->scanCycle = $state['latest_cycle'] ?? 0;
		$this->template->schedule = $state['config']['schedule'] ?? '2x daily';
		$this->template->componentCount = count($components);
		$this->template->pendingCount = $remPending['total'];
		$this->template->resolvedCount = $remResolved['total'];
		$this->template->coveragePct = $areasTotal > 0
			? round($areasTested / $areasTotal * 100) : 0;
		$this->template->areasTested = $areasTested;
		$this->template->areasTotal = $areasTotal;
	}
}
