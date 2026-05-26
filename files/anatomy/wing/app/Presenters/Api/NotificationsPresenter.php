<?php

declare(strict_types=1);

namespace App\Presenters\Api;

use App\Model\NotificationRepository;

/**
 * GET /api/v1/notifications — list operator notifications (Bearer auth).
 *   query: ?since=<ISO>, ?severity, ?unread_only=1, ?actor_action_id,
 *          ?target_actor_id (default "operator"), ?limit (default 100, max 500)
 *
 * Added W5-A2 (2026-05-26). The route never existed, so the scout agent's
 * severity-spike signal (`GET /api/v1/notifications?since=…`) 404'd and was
 * permanently un-evaluable (surfaced by the scout's own drift report). This is
 * a read-only projection of the notifications table; creation stays on the
 * Bone HMAC path (POST is not exposed here).
 */
final class NotificationsPresenter extends BaseApiPresenter
{
	public function __construct(
		private NotificationRepository $notifications,
	) {
	}

	public function actionDefault(): void
	{
		$this->requireMethod('GET');

		$filters = [];
		foreach (['severity', 'since', 'actor_action_id', 'target_actor_id'] as $k) {
			$v = $this->getParameter($k);
			if ($v !== null && $v !== '') {
				$filters[$k] = $v;
			}
		}
		if ($this->getParameter('unread_only')) {
			$filters['unread_only'] = true;
		}
		$limit = min(500, max(1, (int) ($this->getParameter('limit') ?? 100)));

		$result = $this->notifications->query($filters, $limit);
		$this->sendSuccess([
			'generated_at'  => gmdate('c'),
			'notifications' => $result['items'],
			'total'         => $result['total'],
		]);
	}
}
