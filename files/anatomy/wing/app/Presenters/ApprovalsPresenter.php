<?php

declare(strict_types=1);

namespace App\Presenters;

use App\Model\EventRepository;

/**
 * Wing /approvals — agent-action approval queue (A11, 2026-05-07).
 *
 * Read path: list pending agent_approval_request events (those without
 * a paired agent_approval_decision row, joined on actor_action_id) +
 * recent decisions for an audit history panel.
 *
 * Write path: actionApprove/actionReject post a new decision event back
 * to /api/v1/events via HMAC. Operator identity comes from the Authentik
 * forward-auth header X-Authentik-Username. Going through /api/v1/events
 * (rather than calling the repository directly) keeps every approval row
 * identical in shape and audit semantics to any other event write —
 * single canonical write path.
 */
final class ApprovalsPresenter extends BasePresenter
{
	protected string $activeTab = 'approvals';

	public function __construct(
		private EventRepository $events,
	) {
	}

	public function renderDefault(): void
	{
		$pending = $this->events->listPendingApprovals(50);
		$recent  = $this->events->listRecentDecisions(20);

		$this->template->pending      = $pending;
		$this->template->pendingCount = count($pending);
		$this->template->recent       = $recent;
	}

	public function actionApprove(string $actionId): void
	{
		$this->postDecision($actionId, 'approve');
		$this->redirect('Approvals:default');
	}

	public function actionReject(string $actionId): void
	{
		$this->postDecision($actionId, 'reject');
		$this->redirect('Approvals:default');
	}

	/**
	 * Server-side POST to /api/v1/events — same HMAC contract as Bone
	 * and the conductor runner use.
	 */
	private function postDecision(string $actionId, string $verdict): void
	{
		$operator = (string) ($this->getHttpRequest()->getHeader('X-Authentik-Username') ?? 'unknown');
		$secret   = (string) (getenv('WING_EVENTS_HMAC_SECRET') ?: '');
		if ($secret === '') {
			return;
		}

		$payload = [
			'ts'              => gmdate('c'),
			'type'            => 'agent_approval_decision',
			'run_id'          => 'approval-decision-' . $actionId,
			'source'          => 'operator',
			'actor_id'        => $operator,
			'actor_action_id' => $actionId,
			'acted_at'        => gmdate('c'),
			'result'          => [
				'verdict'           => $verdict,
				'operator_username' => $operator,
			],
		];
		$body = json_encode($payload);
		$ts   = (string) time();
		$sig  = hash_hmac('sha256', $ts . '.' . $body, $secret);

		$ch = curl_init('http://127.0.0.1:9000/api/v1/events');
		curl_setopt_array($ch, [
			CURLOPT_RETURNTRANSFER => true,
			CURLOPT_POST           => true,
			CURLOPT_POSTFIELDS     => $body,
			CURLOPT_HTTPHEADER     => [
				'Content-Type: application/json',
				'X-Wing-Timestamp: ' . $ts,
				'X-Wing-Signature: ' . $sig,
			],
			CURLOPT_TIMEOUT        => 5,
		]);
		curl_exec($ch);
		// curl_close removed — no-op since PHP 8.0, deprecation in 8.5.
	}
}
