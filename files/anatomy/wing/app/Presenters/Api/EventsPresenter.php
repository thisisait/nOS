<?php

declare(strict_types=1);

namespace App\Presenters\Api;

use App\Model\EventRepository;

/**
 * POST /api/v1/events  — ingestion from the callback plugin. HMAC-protected.
 * GET  /api/v1/events  — paginated query (?run_id, ?type, ?since, ?limit).
 *
 * The POST action is public to Bearer-token auth (the callback plugin does
 * not have a token — it signs with a shared HMAC secret instead). The GET
 * action requires a bearer token like the other read endpoints.
 */
final class EventsPresenter extends BaseApiPresenter
{
	/** POST uses HMAC, not bearer — list still requires bearer. */
	protected array $publicActions = ['default'];

	public function __construct(
		private EventRepository $events,
		private \App\Model\AgentSessionRepository $sessions,
	) {
	}

	/**
	 * Method-dispatched:
	 *   POST → ingestion (HMAC-signed, from Ansible callback plugin)
	 *   GET  → paginated list (requires bearer token, checked inline)
	 */
	public function actionDefault(): void
	{
		$method = $this->getMethod();
		if ($method === 'POST') {
			$this->createEvent();
		}
		if ($method === 'GET') {
			$this->requireBearerToken();
			$this->listEvents();
		}
		$this->sendError('Method not allowed', 405);
	}

	private function createEvent(): void
	{
		$this->checkHmac();

		$payload = $this->getJsonBody();
		$this->validateEventPayload($payload);

		try {
			$id = $this->events->insert($payload);
		} catch (\Throwable $e) {
			$this->sendError('insert failed: ' . $e->getMessage(), 500);
		}

		// Surface pulse / claude-CLI agent runs in /agents: synthesize the
		// agent_sessions row from agent_run_start/end. Best-effort — a sync
		// hiccup must not fail the (already-persisted) event ingest.
		try {
			$this->sessions->syncFromAgentEvent($payload);
		} catch (\Throwable $e) {
			// swallow — event is recorded; session is a derived projection
		}

		$this->sendCreated(['accepted' => true, 'id' => $id]);
	}

	private function listEvents(): void
	{
		$filters = array_filter([
			'run_id'           => $this->getParameter('run_id'),
			'type'             => $this->getParameter('type'),
			'since'            => $this->getParameter('since'),
			'migration_id'     => $this->getParameter('migration_id'),
			'upgrade_id'       => $this->getParameter('upgrade_id'),
			'coexist_svc'      => $this->getParameter('coexist_svc'),
			// Anatomy P1 (2026-05-05): free-text channel label
			// (callback / operator / agent:<name>).
			'source'           => $this->getParameter('source'),
			// A10 (2026-05-08): cryptographic attribution. Filtering by
			// actor_id surfaces all events written by a specific
			// Authentik client (e.g. ?actor_id=conductor for the
			// conductor agent's full audit trail). actor_action_id
			// groups events of one logical action (start + finish).
			'actor_id'         => $this->getParameter('actor_id'),
			'actor_action_id'  => $this->getParameter('actor_action_id'),
		]);
		$limit = (int) ($this->getParameter('limit') ?? 100);
		$this->sendSuccess($this->events->query($filters, $limit));
	}

	/**
	 * Fallback bearer-token check for GET (since we bypassed the startup
	 * check via publicActions to accommodate POST's HMAC path).
	 */
	private function requireBearerToken(): void
	{
		$authHeader = $this->getHttpRequest()->getHeader('Authorization');
		if (!$authHeader || !str_starts_with($authHeader, 'Bearer ')) {
			$this->sendError('Missing or invalid Authorization header', 401);
		}
		$token = substr($authHeader, 7);
		if (!$this->tokenRepo->validate($token)) {
			$this->sendError('Invalid or inactive API token', 401);
		}
	}

	/**
	 * Validate HMAC signature. Callback plugin sends:
	 *   X-Wing-Timestamp: <unix ts>
	 *   X-Wing-Signature: hex(hmac_sha256(secret, "<ts>.<raw_body>"))
	 * The secret is read from WING_EVENTS_HMAC_SECRET (populated by the
	 * nginx fastcgi_param block). Timestamp must be within ±300s of server
	 * time (replay protection).
	 */
	private function checkHmac(): void
	{
		$secret = (string) (getenv('WING_EVENTS_HMAC_SECRET') ?: '');
		if ($secret === '') {
			$this->sendError('HMAC secret not configured', 500);
		}

		$req = $this->getHttpRequest();
		$ts  = (string) $req->getHeader('X-Wing-Timestamp');
		$sig = (string) $req->getHeader('X-Wing-Signature');

		if ($ts === '' || $sig === '') {
			$this->sendError('Missing HMAC headers', 401);
		}
		if (!ctype_digit($ts)) {
			$this->sendError('Invalid timestamp', 401);
		}
		$drift = abs(time() - (int) $ts);
		if ($drift > 300) {
			$this->sendError('Timestamp out of window', 401);
		}

		$raw = (string) $req->getRawBody();
		$expected = hash_hmac('sha256', $ts . '.' . $raw, $secret);

		if (!hash_equals($expected, $sig)) {
			$this->sendError('Invalid HMAC signature', 401);
		}
	}

	/**
	 * Minimal schema check. event.schema.json does the heavy lifting on the
	 * Ansible side; we double-check the required fields to keep the table
	 * clean.
	 */
	private function validateEventPayload(array $payload): void
	{
		// ALL of them, not the first: a caller learning the contract one field
		// per round trip spends a call per field. The librarian spent two
		// (2026-08-28, session df2a5477) discovering ts, then run_id.
		$missing = [];
		foreach (['ts', 'type', 'run_id'] as $req) {
			if (!isset($payload[$req]) || $payload[$req] === '') {
				$missing[] = $req;
			}
		}
		if ($missing) {
			$this->sendError('Missing required field(s): ' . implode(', ', $missing), 400);
		}
		// A REPORT WITH NOWHERE TO PUT ITS BODY IS REFUSED, NOT ACCEPTED.
		//
		// Measured 2026-08-29, session be9d107f: the librarian did the work —
		// four brief proposals POSTed to KEAP — then filed its report twice,
		// got 201 both times, and both rows stored `length(result_json) = 0`.
		// It had put the markdown under `body`; two other calls wrapped the
		// whole thing in `event`. With `result` and `result_json` that is FOUR
		// spellings for one field, and adding a fourth alias only teaches the
		// next model that a fifth would be fine.
		//
		// So the door refuses instead. A 201 that stores nothing is the
		// success marker written by the thing that failed — the defect this
		// estate is named after — and the agent demonstrably acts on a 400: it
		// read "Missing required field(s)" and fixed the fields on its retry.
		if ($payload['type'] === 'conductor_report') {
			$hasBody = false;
			foreach (['result', 'result_json'] as $key) {
				if (isset($payload[$key]) && is_array($payload[$key]) && $payload[$key] !== []) {
					$hasBody = true;
				}
			}
			if (!$hasBody) {
				$this->sendError(
					'a conductor_report must carry its body in `result_json` (or `result`) '
					. 'as an object — e.g. {"result_json": {"report_markdown": "…"}}. '
					. 'Fields outside those two are not stored, so this report would have '
					. 'been recorded empty.',
					400,
				);
			}
		}
		if (!in_array($payload['type'], EventRepository::VALID_TYPES, true)) {
			$this->sendError("Unknown event type: {$payload['type']}", 400);
		}
	}
}
