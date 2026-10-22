<?php

declare(strict_types=1);

namespace App\Presenters\Api;

use App\Model\AgentSessionRepository;
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
	) {
		parent::__construct();
	}

	protected array $bffActions = ['default', 'cancel'];

	protected array $thalamusActions = ['cancel'];

	public function actionDefault(string $uuid): void
	{
		$session = $this->sessions->findByUuid($uuid);
		// Not yours answers like absent, so a uuid's existence does not leak.
		$scope = $this->endUser?->scope();
		if ($session === null || ($scope !== null && $session['actor_id'] !== $scope)) {
			$this->sendError('not_found', 404);
		}
		$this->sendSuccess([
			'session' => $session,
			'threads' => $this->sessions->listThreadsForSession($uuid),
			'iterations' => $this->sessions->listIterations($uuid),
			'children' => $this->sessions->listChildren($uuid, $scope),
		]);
	}

	/**
	 * A person stops their own run (Tier 1: any); the thalamus only a run its Iris session
	 * started, named as `parent` in the body; a bearer with no person needs wing.operator.
	 * Not-yours answers like absent. The row turns `cancelled` here; the Runner reads it.
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
		if ($mine && ($this->validatedToken['name'] ?? null) === EndUser::THALAMUS) {
			$parent = $this->getJsonBody()['parent'] ?? null;
			$mine = is_string($parent) && str_starts_with($parent, 'thalamus:') && $session['parent_ref'] === $parent;
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
}
