<?php

declare(strict_types=1);

namespace App\Presenters\Api;

use App\Model\AgentSessionRepository;
use App\Model\EventRepository;
use App\Security\EndUser;

/**
 * Wing /api/v1/agent-sessions/<uuid> — single-session lineage as JSON.
 *
 * POST /api/v1/agent-sessions/<uuid>/cancel — stop a running session before its next model call
 *
 * Auth: bearer token via BaseApiPresenter::requireTokenAuth(). The original
 * A14 implementation skipped DB validation (security review finding A14.1);
 * inheriting BaseApiPresenter aligns this presenter with all other Wing
 * API presenters.
 */
final class AgentSessionsPresenter extends BaseApiPresenter
{
	public function __construct(
		private AgentSessionRepository $sessions,
		// Autowired like EventsPresenter's; null only where a harness builds the presenter without it.
		private ?EventRepository $events = null,
	) {
		parent::__construct();
	}

	/** The newest *_report body a read carries, in bytes: what Iris hears of a run it started. */
	public const REPORT_CAP = 4096;

	protected array $bffActions = ['default'];

	protected array $thalamusActions = ['cancel'];

	protected array $thalamusReads = ['default'];

	public function actionDefault(string $uuid): void
	{
		$session = $this->sessions->findByUuid($uuid);
		// Not yours answers like absent, so a uuid's existence does not leak.
		$scope = $this->endUser?->scope();
		$mine = $session !== null && ($scope === null || $session['actor_id'] === $scope);
		if ($mine && $this->isThalamus()) {
			// The thalamus reads only the run its Iris session started (`?parent=thalamus:<session>`),
			// for its person — Tier 1 included: the model hears this, so a group never widens it.
			$scope = $this->endUser->actorId();
			$mine = $this->thalamusOwns($session, $this->getParameter('parent'));
		}
		if (!$mine) {
			$this->sendError('not_found', 404);
		}
		$this->sendSuccess([
			'session' => $session,
			'threads' => $this->sessions->listThreadsForSession($uuid),
			'iterations' => $this->sessions->listIterations($uuid),
			'children' => $this->sessions->listChildren($uuid, $scope),
			'report' => $this->report($uuid),
		]);
	}

	/**
	 * The thalamus stops, for its person, only a run its Iris session started (named as
	 * `parent` in the body); a bearer with no person needs wing.operator; face-bff never
	 * reaches this. Not-yours answers like absent. The row turns `cancelled`; the Runner reads it.
	 */
	public function actionCancel(string $uuid): void
	{
		if ($this->getMethod() !== 'POST') {
			$this->sendError('POST only', 405);
		}
		if ($this->endUser === null) {
			$this->requireOperator();
		}
		$session = $this->sessions->findByUuid($uuid);
		$scope = $this->endUser?->scope();
		$mine = $session !== null && ($scope === null || $session['actor_id'] === $scope);
		if ($mine && $this->isThalamus()) {
			$mine = $this->thalamusOwns($session, $this->getJsonBody()['parent'] ?? null);
		}
		if (!$mine) {
			$this->sendError('not_found', 404);
		}
		if ($session['status'] !== 'running') {
			$this->sendError("the session is {$session['status']}, not running", 409);
		}
		// ponytail: read then write; a run that closes between the two reads cancelled.
		// A `WHERE status = 'running'` update in AgentSessionRepository closes the gap.
		$by = 'cancelled by ' . $this->requireActorId();
		$this->sessions->endSession($uuid, 'cancelled', $by);
		$this->sendSuccess(['session_uuid' => $uuid, 'status' => 'cancelled', 'stop_reason' => $by], 202);
	}

	private function isThalamus(): bool
	{
		return $this->endUser !== null && ($this->validatedToken['name'] ?? null) === EndUser::THALAMUS;
	}

	/**
	 * A run is the thalamus's to read or stop when its person started it from THIS Iris session
	 * (`parent` = thalamus:<session> = the row's parent_ref). actorId, never scope(): a Tier 1
	 * person's thalamus is narrowed like anyone's (review 2026-10-22, defect 1).
	 */
	private function thalamusOwns(array $session, mixed $parent): bool
	{
		return $session['actor_id'] === $this->endUser->actorId()
			&& is_string($parent) && str_starts_with($parent, 'thalamus:') && $session['parent_ref'] === $parent;
	}

	/**
	 * The run's newest *_report event: {event_id, type, body (<= REPORT_CAP bytes), chars}, or null.
	 * body is result.report when it is a string, else the whole result_json.
	 *
	 * @return array<string, mixed>|null
	 */
	private function report(string $uuid): ?array
	{
		// ponytail: the newest 500 events of the run; a report buried under more is null (a type filter in SQL lifts it).
		foreach ($this->events?->query(['actor_action_id' => $uuid], 500)['items'] ?? [] as $e) {
			if (!str_ends_with((string) $e['type'], '_report')) {
				continue;
			}
			$body = is_string($e['result']['report'] ?? null) ? $e['result']['report'] : (string) ($e['result_json'] ?? '');
			return ['event_id' => (int) $e['id'], 'type' => $e['type'],
				'body' => mb_strcut($body, 0, self::REPORT_CAP, 'UTF-8'), 'chars' => mb_strlen($body, 'UTF-8')];
		}
		return null;
	}
}
