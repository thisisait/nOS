<?php

declare(strict_types=1);

namespace App\Presenters;

use App\Model\MigrationRepository;

/**
 * /migrations — pending + applied migrations overview.
 * /migrations/<id> — single migration detail with events timeline.
 */
final class MigrationsPresenter extends BasePresenter
{
	protected string $activeTab = 'migrations';

	public function __construct(
		private MigrationRepository $migrations,
	) {
	}

	/**
	 * Template vars:
	 *   pending: list<array>  — pending migration records (from BoxAPI)
	 *   applied: list<array>  — applied migration records (live or mirror)
	 *   pendingBreakingCount: int
	 *   pendingTotalCount:    int
	 *   appliedSuccessCount:  int
	 */
	public function renderDefault(): void
	{
		$pending = $this->migrations->listPending();
		$applied = $this->migrations->listApplied();

		$this->template->pending = $pending;
		$this->template->applied = $applied;
		$this->template->pendingTotalCount    = count($pending);
		$this->template->pendingBreakingCount = count(array_filter(
			$pending,
			static fn(array $m) => ($m['severity'] ?? '') === 'breaking',
		));
		$this->template->appliedSuccessCount = count(array_filter(
			$applied,
			static fn(array $m) => !empty($m['success']),
		));
	}

	/**
	 * Template vars:
	 *   migration: array|null  — full record, or null if not found
	 *   events:    list<array> — callback events tied to this migration_id
	 *   notFound:  bool
	 *   id:        string
	 */
	public function renderDetail(string $id): void
	{
		$migration = $this->migrations->get($id);
		$this->template->id = $id;
		$this->template->migration = $migration;
		$this->template->notFound = $migration === null;
		$this->template->events = $migration !== null
			? $this->migrations->getEventsFor($id)
			: [];
	}
}
