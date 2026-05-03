<?php

declare(strict_types=1);

namespace App\Presenters;

use App\Model\EventRepository;
use App\Model\MigrationRepository;
use App\Model\UpgradeRepository;

/**
 * /timeline — merged event stream (callback events + migration + upgrade history).
 * Filter chips via ?type=..., ?run_id=..., ?since=...
 */
final class TimelinePresenter extends BasePresenter
{
	protected string $activeTab = 'timeline';

	public function __construct(
		private EventRepository $events,
		private MigrationRepository $migrations,
		private UpgradeRepository $upgrades,
	) {
	}

	/**
	 * Template vars:
	 *   events:      list<array>         — recent events (newest first), up to limit
	 *   total:       int                  — total matching events
	 *   countsByType:array<string,int>    — 30-day rollup for filter badges
	 *   migrations:  list<array>          — applied migrations mirror
	 *   upgrades:    list<array>          — upgrade history
	 *   filters:     array{type?:string,run_id?:string,since?:string}
	 *   limit:       int
	 */
	public function renderDefault(): void
	{
		$req = $this->getHttpRequest();
		$filters = array_filter([
			'type'   => $req->getQuery('type'),
			'run_id' => $req->getQuery('run_id'),
			'since'  => $req->getQuery('since'),
		]);
		$limit = max(1, min(500, (int) ($req->getQuery('limit') ?? 100)));

		$result = $this->events->query($filters, $limit);

		$this->template->events       = $result['items'];
		$this->template->total        = $result['total'];
		$this->template->countsByType = $this->events->countsByType(30);
		$this->template->migrations   = $this->migrations->listApplied();
		$this->template->upgrades     = $this->upgrades->history(null, 50);
		$this->template->filters      = $filters;
		$this->template->limit        = $limit;
	}
}
