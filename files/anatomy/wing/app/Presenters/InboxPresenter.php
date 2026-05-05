<?php

declare(strict_types=1);

namespace App\Presenters;

use App\Model\EventRepository;
use App\Model\GitleaksRepository;

/**
 * Wing /inbox — operator attention queue (Anatomy A8.c, 2026-05-07).
 *
 * Shows two surfaces:
 *   1. Unresolved gitleaks secret findings (resolved_at IS NULL).
 *   2. Recent conductor agent runs (agent_run_start / agent_run_end events).
 *
 * Both datasets use existing repositories — no new SQL needed for A8.c.
 * The /resolve action lives on the API presenter (GitleaksPresenter); the
 * inbox only provides the read-only view.
 */
final class InboxPresenter extends BasePresenter
{
	protected string $activeTab = 'inbox';

	public function __construct(
		private GitleaksRepository $gitleaks,
		private EventRepository $events,
	) {
	}

	public function renderDefault(): void
	{
		$findings = $this->gitleaks->listFindings(['open_only' => true], 200);

		$conductorEvents = $this->events->query(
			['source' => 'conductor'],
			20,
		)['items'] ?? [];

		$this->template->findings        = $findings;
		$this->template->conductorEvents = $conductorEvents;
		$this->template->findingCount    = count($findings);
	}
}
