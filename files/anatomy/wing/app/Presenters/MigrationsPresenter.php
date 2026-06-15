<?php

declare(strict_types=1);

namespace App\Presenters;

use App\Model\EventRepository;
use App\Model\MigrationAuthoredRepository;
use App\Model\MigrationRepository;

/**
 * /migrations — pending + applied + a third "Proposed (agent drafts)" column
 * (B4c) surfacing migrations_authored rows the migration-author agent wrote.
 * /migrations/<id> — single migration detail with events timeline.
 *
 * RBAC (B4c): this view exposes the agent-authored proposals + the operator
 * review controls (mark-reviewed / mark-rejected), so the whole presenter is
 * Tier-1 — parity with /upgrades + /coexistence. Enforced by the declarative
 * `$minAccessTier = 1` (BasePresenter::startup() routes it through requireTier),
 * not an easy-to-forget startup() override. Was UNGATED (the maps flagged it).
 *
 * GATE 2 boundary: the operator NEVER merges in Wing — the proposal card's
 * "Review MR" link sends them to the local GitLab forge to review + merge. Wing
 * only records in_review / rejected (MigrationAuthoredRepository::setReviewStatus
 * hard-refuses `merged`, which is the forge webhook's exclusive write).
 */
final class MigrationsPresenter extends BasePresenter
{
	protected string $activeTab = 'migrations';

	// RBAC: Tier-1 only. Pinned by tests/anatomy/test_coexistence_presenter_tier1.py.
	protected ?int $minAccessTier = 1;

	public function __construct(
		private MigrationRepository $migrations,
		private MigrationAuthoredRepository $authored,
		private EventRepository $events,
	) {
	}

	/**
	 * Template vars:
	 *   pending:  list<array>  — pending migration records (from BoxAPI)
	 *   applied:  list<array>  — applied migration records (live or mirror)
	 *   proposed: list<array>  — agent-authored drafts awaiting review (B4c)
	 *   pendingBreakingCount: int
	 *   pendingTotalCount:    int
	 *   appliedSuccessCount:  int
	 *   proposedCount:        int
	 */
	public function renderDefault(): void
	{
		$pending = $this->migrations->listPending();
		$applied = $this->migrations->listApplied();
		// Proposed = the agent-authored drafts (review_status in draft/in_review)
		// — the recipe→migration promotion records, NEVER read before B4c (the
		// lossy "draft into a conductor_report event" path replaced it).
		$proposed = $this->authored->listReviewable();

		$this->template->pending  = $pending;
		$this->template->applied  = $applied;
		$this->template->proposed = $proposed;
		$this->template->pendingTotalCount    = count($pending);
		$this->template->proposedCount        = count($proposed);
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
	 * POST /migrations/<id>/mark-reviewed — operator acknowledges a draft is
	 * under review on the forge (B4c). Flips review_status draft → in_review.
	 * This is NOT a merge: `merged` stays the forge webhook's exclusive write
	 * (GATE 2). CSRF-gated; <id> is the migrations_authored row id (route param
	 * arrives as a string — cast once, matching the GitleaksPresenter idiom).
	 */
	public function actionMarkReviewed(string $id): void
	{
		$this->requirePostMethod();
		$rowId = (int) $id;
		$result = $this->authored->setReviewStatus($rowId, 'in_review');
		$this->flashMessage(
			$result['ok'] ? 'Marked in_review — merge the MR on the local forge to promote (GATE 2).' : "Refused — {$result['detail']}.",
			$result['ok'] ? 'success' : 'error',
		);
		$this->redirect('Migrations:default');
	}

	/**
	 * POST /migrations/<id>/mark-rejected — operator rejects an agent draft
	 * (B4c). Flips review_status → rejected (terminal) with the operator's reason,
	 * and emits migration_rejected (§2.6). The agent can re-author later (the
	 * insert delete-prior trick supersedes a stale draft). CSRF-gated.
	 */
	public function actionMarkRejected(string $id): void
	{
		$this->requirePostMethod();
		$rowId = (int) $id;
		$reason = (string) ($this->getHttpRequest()->getPost('reason') ?? '');
		$reason = $reason !== '' ? $reason : 'rejected by operator';
		// Capture the row uuid BEFORE the flip — setReviewStatus moves it to the
		// terminal 'rejected' status, after which listReviewable() no longer
		// returns it (the lineage migration_uuid would be lost).
		$uuid = (string) $rowId;
		foreach ($this->authored->listReviewable() as $p) {
			if ((int) $p['id'] === $rowId) {
				$uuid = (string) ($p['uuid'] ?? $rowId);
				break;
			}
		}
		$row = $this->authored->setReviewStatus($rowId, 'rejected', $reason);
		if ($row['ok']) {
			$this->emitRejected($uuid, $reason);
		}
		$this->flashMessage(
			$row['ok'] ? 'Proposal rejected.' : "Refused — {$row['detail']}.",
			$row['ok'] ? 'success' : 'error',
		);
		$this->redirect('Migrations:default');
	}

	/**
	 * Best-effort migration_rejected emit (migration_id col holds the row uuid,
	 * §2.6). Never blocks the reject — an audit failure mustn't abort the action.
	 */
	private function emitRejected(string $uuid, string $reason): void
	{
		try {
			$actor = (string) ($this->getHttpRequest()->getHeader('X-Authentik-Username') ?? 'operator');
			$this->events->insert([
				'type'            => 'migration_rejected',
				'task'            => 'migration_rejected: ' . $uuid,
				'source'          => 'wing',
				'migration_id'    => $uuid,
				'actor_id'        => $actor !== '' ? $actor : 'operator',
				'actor_action_id' => $uuid,
				'result'          => [
					'migration_uuid'  => $uuid,
					'rejected_reason' => $reason,
				],
			]);
		} catch (\Throwable) {
			// audit failure must not block the reject.
		}
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
