<?php

declare(strict_types=1);

namespace App\Presenters\Api;

use App\AgentKit\AgentLoader;
use App\AgentKit\AgentLoadException;
use App\AgentKit\OperatorTrigger;
use App\AgentKit\OperatorTriggerException;
use App\Model\AgentSessionRepository;
use Nette\Http\IResponse;

/**
 * Wing /api/v1/agents — REST surface over the agent catalog + session lineage.
 *
 *   GET  /api/v1/agents                         — list on-disk agents
 *   GET  /api/v1/agents/<name>                  — single agent config (parsed YAML view)
 *   GET  /api/v1/agents/<name>/sessions         — session list for one agent
 *   POST /api/v1/agents/<name>/sessions         — operator-trigger: spawn a runner
 *
 * Auth: bearer token (api_tokens table). Inherited from BaseApiPresenter
 * via requireTokenAuth() — the canonical Wing pattern. A14.1 (2026-05-07)
 * security review found the original A14 implementation only checked the
 * `Bearer ` prefix without validating against api_tokens; switching to the
 * BaseApiPresenter inheritance closes that bypass.
 *
 * Operator-trigger contract (A14 follow-up, 2026-05-07):
 *   - actor_id is ALWAYS derived from $this->validatedToken['name'] via
 *     BaseApiPresenter::getActorId(). NEVER accept a client-supplied
 *     actor_id in the request body — that is a privilege-escalation
 *     vector and would let any token holder masquerade as 'conductor'
 *     or 'openclaw'. Same X.1.b pattern Pulse uses.
 *   - The runner is spawned as a non-blocking child via proc_open ARRAY
 *     form (NOT exec / shell_exec / proc_open string form). Array form
 *     calls execve() directly so /bin/sh is never invoked — no shell
 *     metacharacter parsing path exists. Same pattern A14.1 forced on
 *     BashReadOnlyTool after the initial string-form CVE.
 *   - The session UUID is generated server-side BEFORE spawn and passed
 *     to the child via --session-uuid argv flag. The 202 response hands
 *     the UUID back to the operator immediately so the UI can poll
 *     /api/v1/agent-sessions/<uuid> straight away. The polling endpoint
 *     returns 404 for the brief window before the child boots and writes
 *     its row; UI tolerates that as 'starting'.
 */
final class AgentsPresenter extends BaseApiPresenter
{
	public function __construct(
		private AgentLoader $loader,
		private AgentSessionRepository $sessions,
		// A3.1 (2026-06-16): the spawn body (PHP-bin resolution, argv array,
		// proc_open execve, UUID) moved into the shared OperatorTrigger so the
		// Tier-1 "Promote to migration" button (UpgradesPresenter) and this
		// bearer API spawn the runner through ONE audited path. The
		// actor-from-bearer anti-spoof guard stays here (presenter-local).
		private OperatorTrigger $operatorTrigger,
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
				// The gate set is what decides satisfaction; the rubric is
				// optional feedback material and may be absent.
				'gateset' => $a->gateset,
				'rubric_path' => $a->rubric?->sourcePath,
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
		// POST = operator-trigger spawn. GET = list recent sessions.
		if ($this->getMethod() === 'POST') {
			$this->startSession($name);
			return;
		}
		$this->requireMethod('GET');
		$rows = $this->sessions->listRecent(100, $name);
		$this->sendSuccess(['data' => $rows, 'total' => count($rows)]);
	}

	/**
	 * POST /api/v1/agents/<name>/sessions
	 *
	 * Body (all optional):
	 *   prompt?: string   — initial user message; defaults to agent's built-in
	 *   vault?:  string   — vault name for credential resolution
	 *
	 * actor_id is NEVER read from the body. It is always
	 * $this->validatedToken['name'] via getActorId(). Any 'actor_id' key in
	 * the body is silently ignored — see class docblock for rationale.
	 *
	 * Returns 202 immediately with {session_uuid, status: 'starting'}. The
	 * runner is spawned as a non-blocking child and writes its agent_sessions
	 * row when it boots; the UI polls /api/v1/agent-sessions/<uuid> for
	 * status transitions (starting -> running -> idle/terminated).
	 */
	private function startSession(string $name): void
	{
		// Validate the agent name resolves on disk before we spawn anything.
		// AgentLoader::load applies the same regex the schema enforces, so
		// this also catches malformed names (which would otherwise reach
		// argv as the value of --agent and get rejected by the child only
		// after Nette container boot — wasting ~500ms).
		try {
			$this->loader->load($name);
		} catch (AgentLoadException $exc) {
			$this->sendError($exc->getMessage(), 404);
		}

		$body = $this->getJsonBody();
		$prompt = isset($body['prompt']) && is_string($body['prompt']) ? $body['prompt'] : null;
		$vault  = isset($body['vault'])  && is_string($body['vault'])  ? $body['vault']  : null;

		// Defence in depth: refuse client-supplied actor_id even though we
		// don't read it. A future refactor that flips this to ?? $body['actor_id']
		// would silently introduce the privilege-escalation path; making the
		// rejection explicit + tested keeps that door shut.
		if (isset($body['actor_id'])) {
			$this->sendError(
				'actor_id is not accepted in the request body — it is derived ' .
					'server-side from the bearer token. See AgentsPresenter docblock.',
				400,
			);
		}

		$actorId = $this->getActorId();
		if ($actorId === null) {
			// Should never trigger: BaseApiPresenter::startup() rejects
			// missing/invalid tokens before we get here. Defence in depth.
			$this->sendError('actor_id unavailable — token validation drift', 500);
		}

		// A3.1: spawn through the shared OperatorTrigger (execve array form, UUID
		// generated server-side). On a structural failure it throws
		// OperatorTriggerException whose code is HTTP-shaped — map straight to
		// sendError, preserving the prior inline-spawn error contract (500 no
		// PHP binary / proc_open false; 404 unknown agent — though we already
		// load()'d above).
		try {
			$res = $this->operatorTrigger->spawn(
				agent: $name,
				actorId: $actorId,
				prompt: $prompt,
				vault: $vault,
			);
		} catch (OperatorTriggerException $exc) {
			$code = $exc->getCode();
			$this->sendError($exc->getMessage(), $code >= 400 && $code < 600 ? $code : 500);
		}

		// 202 Accepted (not 201 Created): the runner is still starting, the
		// agent_sessions row has not been written yet, and the resource will
		// only exist when the child boots. The poll_url returns 404 for ~200ms
		// then 200 once the row lands; the UI tolerates that as 'starting'.
		$this->sendSuccess([
			'session_uuid' => $res['session_uuid'],
			'status' => 'starting',
			'agent_name' => $name,
			'actor_id' => $actorId,
			'pid' => $res['pid'],
			'poll_url' => "/api/v1/agent-sessions/{$res['session_uuid']}",
		], IResponse::S202_Accepted);
	}
}
