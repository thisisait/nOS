<?php

declare(strict_types=1);

namespace App\Presenters\Api;

use App\Model\AgentSessionRepository;

/**
 * Wing /api/v1/agent-sessions/<uuid> — single-session lineage as JSON.
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

	public function actionDefault(string $uuid): void
	{
		$session = $this->sessions->findByUuid($uuid);
		if ($session === null) {
			$this->sendError('not_found', 404);
		}
		$this->sendSuccess([
			'session' => $session,
			'threads' => $this->sessions->listThreadsForSession($uuid),
			'iterations' => $this->sessions->listIterations($uuid),
		]);
	}
}
