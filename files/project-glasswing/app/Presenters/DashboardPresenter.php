<?php

declare(strict_types=1);

namespace App\Presenters;

use App\Model\ComponentRepository;
use App\Model\RemediationRepository;
use App\Model\PentestRepository;
use App\Model\AdvisoryRepository;
use App\Model\ScanStateRepository;

final class DashboardPresenter extends BasePresenter
{
	protected string $activeTab = 'overview';

	public function __construct(
		private ComponentRepository $componentRepo,
		private RemediationRepository $remediationRepo,
		private PentestRepository $pentestRepo,
		private AdvisoryRepository $advisoryRepo,
		private ScanStateRepository $scanRepo,
	) {
	}

	public function renderDefault(): void
	{
		$state = $this->scanRepo->getState();
		$components = $this->componentRepo->list([]);
		$remPending = $this->remediationRepo->list(['status' => 'pending', 'limit' => 1000]);
		$remResolved = $this->remediationRepo->list(['status' => 'resolved', 'limit' => 1000]);
		$targets = $this->pentestRepo->listTargets();
		$advisories = $this->advisoryRepo->list(['limit' => 30]);

		$areasTested = 0;
		$areasPlanned = 0;
		foreach ($targets as $t) {
			$areasTested += $t['areas_tested_count'] ?? 0;
			$areasPlanned += $t['areas_planned_count'] ?? 0;
		}

		$this->template->state = $state;
		$this->template->components = $components;
		$this->template->pendingCount = $remPending['total'];
		$this->template->resolvedCount = $remResolved['total'];
		$this->template->targets = $targets;
		$this->template->advisories = $advisories;
		$this->template->areasTested = $areasTested;
		$this->template->areasTotal = $areasTested + $areasPlanned;
		$this->template->coveragePct = ($areasTested + $areasPlanned) > 0
			? round($areasTested / ($areasTested + $areasPlanned) * 100) : 0;
	}
}
