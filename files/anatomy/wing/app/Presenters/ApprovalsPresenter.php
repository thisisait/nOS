<?php

declare(strict_types=1);

namespace App\Presenters;

/**
 * Wing /approvals — conductor approval queue stub (Anatomy A8.c, 2026-05-07).
 *
 * Placeholder for Phase 5: once A10 (actor audit migration) lands the
 * `actor_id` + `actor_action_id` columns, the conductor will push pending
 * approvals here for operator review before acting. The route is wired now
 * so the nav tab is live and the pattern is established.
 */
final class ApprovalsPresenter extends BasePresenter
{
	protected string $activeTab = 'approvals';

	public function renderDefault(): void
	{
		$this->template->pendingCount = 0;
	}
}
