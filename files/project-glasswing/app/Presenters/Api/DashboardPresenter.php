<?php

declare(strict_types=1);

namespace App\Presenters\Api;

use App\Model\ComponentRepository;
use App\Model\RemediationRepository;
use App\Model\PentestRepository;
use App\Model\AdvisoryRepository;
use App\Model\ScanStateRepository;

final class DashboardPresenter extends BaseApiPresenter
{
	protected array $publicActions = ['summary'];

	public function __construct(
		private ComponentRepository $componentRepo,
		private RemediationRepository $remediationRepo,
		private PentestRepository $pentestRepo,
		private AdvisoryRepository $advisoryRepo,
		private ScanStateRepository $scanRepo,
	) {
	}

	public function actionSummary(): void
	{
		$this->requireMethod('GET');

		$state = $this->scanRepo->getState();
		$components = $this->componentRepo->list([]);
		$remPending = $this->remediationRepo->list(['status' => 'pending', 'limit' => 1000]);
		$remResolved = $this->remediationRepo->list(['status' => 'resolved', 'limit' => 1000]);
		$targets = $this->pentestRepo->listTargets();

		$criticalPending = 0;
		$highPending = 0;
		foreach ($remPending['items'] as $item) {
			if ($item['severity'] === 'CRITICAL') $criticalPending++;
			if ($item['severity'] === 'HIGH') $highPending++;
		}

		$areasTested = 0;
		$areasPlanned = 0;
		$findingsTotal = 0;
		$patchesTotal = 0;
		foreach ($targets as $t) {
			$areasTested += $t['areas_tested_count'] ?? 0;
			$areasPlanned += $t['areas_planned_count'] ?? 0;
			$findingsTotal += $t['findings_count'] ?? 0;
		}

		$areasTotal = $areasTested + $areasPlanned;

		$this->sendSuccess([
			'scan_cycle' => $state['config']['scan_cycle'] ?? $state['latest_cycle'] ?? 0,
			'last_scan' => $state['config']['last_advisory_check'] ?? null,
			'components_total' => count($components),
			'remediation' => [
				'pending' => $remPending['total'],
				'resolved' => $remResolved['total'],
				'critical_pending' => $criticalPending,
				'high_pending' => $highPending,
			],
			'pentest' => [
				'targets' => count($targets),
				'areas_tested' => $areasTested,
				'areas_planned' => $areasPlanned,
				'areas_total' => $areasTotal,
				'coverage_pct' => $areasTotal > 0 ? round($areasTested / $areasTotal * 100) : 0,
				'findings' => $findingsTotal,
			],
			'schedule' => $state['config']['schedule'] ?? '2x daily',
			'next_batch' => $state['next_batch'] ?? [],
		]);
	}

	public function actionTimeline(): void
	{
		$this->requireMethod('GET');
		$limit = (int) ($this->getParameter('limit') ?? 30);
		$advisories = $this->advisoryRepo->list(['limit' => $limit]);

		// Group by date
		$grouped = [];
		foreach ($advisories as $adv) {
			$date = $adv['date'];
			$grouped[$date][] = $adv;
		}

		$this->sendSuccess(['timeline' => $grouped]);
	}
}
