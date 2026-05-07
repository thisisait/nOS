<?php

declare(strict_types=1);

namespace App\Presenters\Api;

use App\AgentKit\AgentLoader;
use App\AgentKit\AgentLoadException;
use App\Model\AgentSessionRepository;

/**
 * Wing /api/v1/agents — REST surface over the agent catalog + session lineage.
 *
 *   GET  /api/v1/agents                         — list on-disk agents
 *   GET  /api/v1/agents/<name>                  — single agent config (parsed YAML view)
 *   GET  /api/v1/agents/<name>/sessions         — session list for one agent
 *
 * Auth: bearer token (api_tokens table). Inherited from BaseApiPresenter
 * via requireTokenAuth() — the canonical Wing pattern. A14.1 (2026-05-07)
 * security review found the original A14 implementation only checked the
 * `Bearer ` prefix without validating against api_tokens; switching to the
 * BaseApiPresenter inheritance closes that bypass.
 *
 * Read-only here. Run-trigger lands in a follow-up. WHEN that endpoint
 * is added, MUST derive `actor_id` from $this->validatedToken['name']
 * (via getActorId()) — never accept a client-supplied actor_id in the
 * request payload, mirroring the X.1.b pattern Pulse already uses.
 */
final class AgentsPresenter extends BaseApiPresenter
{
	public function __construct(
		private AgentLoader $loader,
		private AgentSessionRepository $sessions,
	) {
		parent::__construct();
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
			$this->sendSuccess(['data' => $out, 'total' => count($out)]);
			return;   // belt-and-suspenders — sendSuccess is `: never`, but if a
			          // refactor weakens the contract this prevents fall-through
			          // to the named-agent branch below (A14.2 hardening).
		}

		try {
			$a = $this->loader->load($name);
		} catch (AgentLoadException $exc) {
			$this->sendError($exc->getMessage(), 404);
		}
		$this->sendSuccess([
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
		$this->sendSuccess(['data' => $rows, 'total' => count($rows)]);
	}
}
