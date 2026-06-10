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

		// W6.2 data honesty (2026-06-10): the dashboard used to echo
		// scan_config.schedule ("hourly") although scans are operator-fired
		// on-demand (the 4 agent pulse jobs are paused by doctrine), and
		// every advisory carried a hardcoded recency-fresh dot — an April
		// advisory rendered as green-fresh in June. Compute real ages here.
		$scanAgeDays = null;
		if (!empty($state['latest_cycle_at'])) {
			$ts = strtotime((string) $state['latest_cycle_at']);
			if ($ts !== false) {
				$scanAgeDays = (int) floor((time() - $ts) / 86400);
			}
		}
		foreach ($advisories as &$adv) {
			$adv['recency'] = self::recencyClass($adv['date'] ?? null);
		}
		unset($adv);

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
		$this->template->scanAgeDays = $scanAgeDays;
		// 14d mirrors the drift-hook threshold (20-cve-drift-check.sh) —
		// one stale definition across hook + dashboard.
		$this->template->scanStale = $scanAgeDays === null || $scanAgeDays > 14;
	}

	/** Recency dot class from an ISO-ish date string: <7d fresh, <30d recent,
	 * <90d stale, else old. Unparseable dates render as old (honest default). */
	private static function recencyClass(?string $date): string
	{
		$ts = $date !== null ? strtotime($date) : false;
		if ($ts === false) {
			return 'recency-old';
		}
		$days = (time() - $ts) / 86400;
		if ($days < 7) {
			return 'recency-fresh';
		}
		if ($days < 30) {
			return 'recency-recent';
		}
		if ($days < 90) {
			return 'recency-stale';
		}
		return 'recency-old';
	}
}
