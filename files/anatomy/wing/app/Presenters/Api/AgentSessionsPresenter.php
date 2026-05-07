<?php

declare(strict_types=1);

namespace App\Presenters\Api;

use App\Model\AgentSessionRepository;
use Nette\Application\UI\Presenter;

/**
 * Wing /api/v1/agent-sessions/<uuid> — single-session lineage as JSON.
 * Used by external monitors and the future operator-side trigger UI.
 */
final class AgentSessionsPresenter extends Presenter
{
	public function __construct(
		private AgentSessionRepository $sessions,
	) {
	}

	public function startup(): void
	{
		parent::startup();
		$header = $this->getHttpRequest()->getHeader('Authorization');
		if (!is_string($header) || !str_starts_with($header, 'Bearer ')) {
			$this->sendJson(['error' => 'unauthorized'], 401);
		}
	}

	public function actionDefault(string $uuid): void
	{
		$session = $this->sessions->findByUuid($uuid);
		if ($session === null) {
			$this->sendJson(['error' => 'not_found'], 404);
		}
		$this->sendJson([
			'session' => $session,
			'threads' => $this->sessions->listThreadsForSession($uuid),
			'iterations' => $this->sessions->listIterations($uuid),
		]);
	}

	private function sendJson(array $payload, int $status = 200): never
	{
		$this->getHttpResponse()->setCode($status);
		$this->sendResponse(new \Nette\Application\Responses\JsonResponse($payload));
	}
}
