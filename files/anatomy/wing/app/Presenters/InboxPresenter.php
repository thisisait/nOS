<?php

declare(strict_types=1);

namespace App\Presenters;

use App\Model\EventRepository;
use App\Model\GitleaksRepository;
use App\Model\NotificationRepository;

/**
 * Wing /inbox — operator attention queue.
 *
 * A9 (2026-05-16) promoted this from a read-only gitleaks/conductor snapshot
 * to the **primary notification surface**. Three sections:
 *
 *   1. Notifications — unread rows from wing.db.notifications. POST mark-read.
 *   2. Secret Findings — unresolved gitleaks_findings (legacy A8.c section).
 *   3. Conductor Runs — recent conductor events (legacy A8.c section).
 *
 * The notifications section is severity-filtered + mark-read-clickable; the
 * other two are read-only deep-links retained because they predate the
 * notifications table and continue to surface useful state that hasn't
 * been promoted to notifications yet.
 *
 * No tier gate — any authenticated operator should see their attention queue.
 * Mark-read is POST-only to prevent CSRF-style accidental reads.
 */
final class InboxPresenter extends BasePresenter
{
	protected string $activeTab = 'inbox';

	public function __construct(
		private NotificationRepository $notifications,
		private GitleaksRepository $gitleaks,
		private EventRepository $events,
	) {
	}

	public function renderDefault(?string $severity = null, bool $unreadOnly = true): void
	{
		$filters = ['unread_only' => $unreadOnly];
		if ($severity !== null && $severity !== '') {
			$filters['severity'] = $severity;
		}
		$notificationRows = $this->notifications->query($filters, 200);
		$unreadCount      = $this->notifications->countUnread();

		$findings = $this->gitleaks->listFindings(['open_only' => true], 200);

		$conductorEvents = $this->events->query(
			['source' => 'conductor'],
			20,
		)['items'] ?? [];

		$this->template->notifications     = $notificationRows['items'];
		$this->template->notificationTotal = $notificationRows['total'];
		$this->template->unreadCount       = $unreadCount;
		$this->template->severityFilter    = $severity;
		$this->template->unreadOnly        = $unreadOnly;
		$this->template->findings          = $findings;
		$this->template->conductorEvents   = $conductorEvents;
		$this->template->findingCount      = count($findings);
	}

	public function actionMarkRead(string $uuid): void
	{
		$this->requirePostMethod();
		$this->notifications->markRead($uuid);
		$this->redirect('Inbox:default');
	}
}
