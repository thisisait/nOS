<?php

declare(strict_types=1);

namespace App\Presenters;

use App\Model\EventRepository;
use App\Model\PulseRepository;

/**
 * Wing /admin — Tier-1 platform control panel (A12, 2026-05-07).
 *
 * Today: a single concern — the "big red button" that halts every
 * Pulse cron job in one click + a paired Resume that lifts ONLY
 * emergency halts (preserving operator-set manual pauses).
 *
 * Authorization: super-admin only. The X-Authentik-Groups header
 * (forward-auth) must contain 'nos-providers' (Tier-1 RBAC group per
 * default.config.yml authentik_rbac_tiers). Anything else -> 403.
 *
 * Audit: every halt + resume writes a paired admin_emergency_halt /
 * admin_emergency_resume event with actor_id = operator and a shared
 * actor_action_id (one halt-resume cycle = one UUID).
 */
final class AdminPresenter extends BasePresenter
{
	protected string $activeTab = 'admin';

	public function __construct(
		private PulseRepository $pulse,
		private EventRepository $events,
	) {
	}

	public function startup(): void
	{
		parent::startup();
		// Tier-1 RBAC gate (BasePresenter::requireSuperAdmin) — server-side
		// authorization boundary. The @layout.latte hides the Admin tab for
		// non-Tier-1 users, but UI-hiding is cosmetic only.
		$this->requireSuperAdmin();
	}

	public function renderDefault(): void
	{
		$this->template->haltActive  = $this->pulse->isEmergencyHaltActive();
		$this->template->jobCounts   = $this->pulse->jobStateCounts();
		$this->template->recentHalts = $this->events->query(
			['type' => 'admin_emergency_halt'],
			10,
		)['items'] ?? [];
		$this->template->recentResumes = $this->events->query(
			['type' => 'admin_emergency_resume'],
			10,
		)['items'] ?? [];
	}

	public function actionHalt(): void
	{
		// A13.7 (2026-05-07): POST-only — closes the GET-CSRF / phishing-link
		// vector raised in the security review. Template uses a <form method="post">.
		$this->requirePostMethod();
		$operator = $this->operatorId();
		$affected = $this->pulse->emergencyHaltAll($operator);
		$this->postAuditEvent(
			'admin_emergency_halt',
			['jobs_affected' => $affected, 'operator_username' => $operator],
		);
		$this->redirect('Admin:default');
	}

	public function actionResume(): void
	{
		$this->requirePostMethod();   // A13.7 — see actionHalt comment.
		$operator = $this->operatorId();
		$affected = $this->pulse->emergencyResumeAll();
		$this->postAuditEvent(
			'admin_emergency_resume',
			['jobs_unhalted' => $affected, 'operator_username' => $operator],
		);
		$this->redirect('Admin:default');
	}

	// -- Helpers --------------------------------------------------------

	private function operatorId(): string
	{
		return (string) ($this->getHttpRequest()->getHeader('X-Authentik-Username') ?? 'unknown');
	}

	/**
	 * Audit-write the halt / resume event via the canonical /api/v1/events
	 * HMAC path -- same shape as ApprovalsPresenter::postDecision (A11).
	 * One write path keeps every audit row identical regardless of caller.
	 */
	private function postAuditEvent(string $type, array $result): void
	{
		$secret = (string) (getenv('WING_EVENTS_HMAC_SECRET') ?: '');
		if ($secret === '') {
			return;
		}
		$operator = $this->operatorId();
		$actionId = bin2hex(random_bytes(8));
		$payload = [
			'ts'              => gmdate('c'),
			'type'            => $type,
			'run_id'          => $type . '-' . $actionId,
			'source'          => 'operator',
			'actor_id'        => $operator,
			'actor_action_id' => $actionId,
			'acted_at'        => gmdate('c'),
			'result'          => $result,
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
		// curl_close removed -- no-op since PHP 8.0, deprecation in 8.5.
	}
}
