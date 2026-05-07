<?php

declare(strict_types=1);

namespace App\Presenters\Api;

use App\AgentKit\AgentLoader;
use App\AgentKit\AgentLoadException;
use App\Model\AgentSessionRepository;
use Nette\Application\UI\Presenter;

/**
 * Wing /api/v1/agents — REST surface over the agent catalog + session lineage.
 *
 *   GET  /api/v1/agents                         — list on-disk agents
 *   GET  /api/v1/agents/<name>                  — single agent config (parsed YAML view)
 *   GET  /api/v1/agents/<name>/sessions         — session list for one agent
 *   GET  /api/v1/agent-sessions/<uuid>          — single session lineage (threads + iterations)
 *
 * Read-only here. Run-trigger lands in a follow-up (POST /api/v1/agents/<name>/sessions)
 * once the launchd-spawned-runner-from-Wing path is wired without blocking the
 * presenter.
 *
 * Auth: bearer token (api_tokens table). Anonymous access denied.
 */
final class AgentsPresenter extends Presenter
{
	public function __construct(
		private AgentLoader $loader,
		private AgentSessionRepository $sessions,
	) {
	}

	public function startup(): void
	{
		parent::startup();
		// Bearer-token auth — same gate as other api/v1 read endpoints.
		// Public-action exception surfaces only on /metrics.
		$header = $this->getHttpRequest()->getHeader('Authorization');
		if (!is_string($header) || !str_starts_with($header, 'Bearer ')) {
			$this->sendJson(['error' => 'unauthorized'], 401);
		}
	}

	public function actionDefault(?string $name = null): void
	{
		if ($name === null) {
			// list all
			$out = [];
			foreach ($this->loader->listAvailable() as $n) {
				try {
					$a = $this->loader->load($n);
					$out[] = [
						'name' => $a->name,
						'version' => $a->version,
						'description' => $a->description,
						'model_primary' => $a->modelPrimaryUri,
						'model_fallback' => $a->modelFallbackUri,
						'multiagent_type' => $a->multiagentType,
						'has_outcome' => $a->hasOutcome(),
						'capability_scopes' => $a->capabilityScopes,
						'pii_classification' => $a->piiClassification,
					];
				} catch (AgentLoadException $exc) {
					$out[] = ['name' => $n, 'error' => $exc->getMessage()];
				}
			}
			$this->sendJson(['data' => $out, 'total' => count($out)]);
			return;
		}
		try {
			$a = $this->loader->load($name);
		} catch (AgentLoadException $exc) {
			$this->sendJson(['error' => $exc->getMessage()], 404);
		}
		$this->sendJson([
			'name' => $a->name,
			'version' => $a->version,
			'description' => $a->description,
			'model' => [
				'primary' => $a->modelPrimaryUri,
				'fallback' => $a->modelFallbackUri,
			],
			'tools' => array_map(static fn ($t) => $t->id, $a->tools),
			'multiagent' => [
				'type' => $a->multiagentType,
				'roster' => array_map(static fn ($r) => ['name' => $r->name, 'version' => $r->version], $a->roster),
				'max_concurrent_threads' => $a->maxConcurrentThreads,
			],
			'outcomes' => $a->hasOutcome() ? [
				'rubric_path' => $a->rubric->sourcePath,
				'max_iterations' => $a->maxIterations,
			] : null,
			'audit' => [
				'capability_scopes' => $a->capabilityScopes,
				'pii_classification' => $a->piiClassification,
			],
			'metadata' => $a->metadata,
		]);
	}

	public function actionSessions(string $name): void
	{
		$rows = $this->sessions->listRecent(100, $name);
		$this->sendJson(['data' => $rows, 'total' => count($rows)]);
	}

	private function sendJson(array $payload, int $status = 200): never
	{
		$this->getHttpResponse()->setCode($status);
		$this->sendResponse(new \Nette\Application\Responses\JsonResponse($payload));
	}
}
