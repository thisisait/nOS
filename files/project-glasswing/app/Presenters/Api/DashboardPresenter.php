<?php

declare(strict_types=1);

namespace App\Presenters\Api;

use App\Model\ComponentRepository;
use App\Model\RemediationRepository;
use App\Model\PentestRepository;
use App\Model\AdvisoryRepository;
use App\Model\ScanStateRepository;
use App\Model\PatchRepository;
use App\Model\UpgradeRepository;
use App\Model\CoexistenceRepository;

final class DashboardPresenter extends BaseApiPresenter
{
	protected array $publicActions = ['summary'];

	public function __construct(
		private ComponentRepository $componentRepo,
		private RemediationRepository $remediationRepo,
		private PentestRepository $pentestRepo,
		private AdvisoryRepository $advisoryRepo,
		private ScanStateRepository $scanRepo,
		private PatchRepository $patchRepo,
		private UpgradeRepository $upgradeRepo,
		private CoexistenceRepository $coexistRepo,
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

		// ---- Maintenance block -------------------------------------------------
		// Consolidated "what's waiting for me to act on" aggregate for the UI
		// front page. Each counter is cheap (local SQLite or one BoxAPI call)
		// and non-fatal: if the source is unreachable, we return 0.
		$upgradesPending = 0;
		try {
			foreach ($this->upgradeRepo->matrix() as $row) {
				if (!empty($row['recipe_available'])) {
					$upgradesPending++;
				}
			}
		} catch (\Throwable) {
			// BoxAPI down — keep 0, dashboard still renders.
		}

		$patchesDraft    = $this->patchRepo->statusCount('draft');
		$patchesPending  = $this->patchRepo->statusCount('pending');
		$coexistPending  = $this->coexistRepo->pendingCutoverCount();

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
			// New: unified actionable counters across the patch/update/upgrade/
			// migrate suite. Consumers (front page badges, CLI, ntfy alerts) can
			// read a single endpoint instead of fanning out to each subsystem.
			'maintenance' => [
				'upgrades_pending'           => $upgradesPending,
				'patches_draft'              => $patchesDraft,
				'patches_pending'            => $patchesPending,
				'advisories_critical'        => $criticalPending,
				'coexistence_pending_cutover' => $coexistPending,
				'total'                      => $upgradesPending + $patchesDraft + $patchesPending + $criticalPending + $coexistPending,
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
