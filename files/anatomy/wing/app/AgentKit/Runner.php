<?php

declare(strict_types=1);

namespace App\AgentKit;

use App\AgentKit\LLMClient\BindingDecision;
use App\AgentKit\LLMClient\BindingResolver;
use App\AgentKit\LLMClient\Factory as LLMFactory;
use App\AgentKit\LLMClient\LLMClientInterface;
use App\AgentKit\LLMClient\LLMCapabilityError;
use App\AgentKit\LLMClient\LLMPermanentError;
use App\AgentKit\LLMClient\LLMTransientError;
use App\AgentKit\LLMClient\Message;
use App\AgentKit\LLMClient\ToolSchema;
use App\AgentKit\Outcome\Grader;
use App\AgentKit\Telemetry\AuditEmitter;
use App\AgentKit\Telemetry\OtelExporter;
use App\AgentKit\Telemetry\Span;
use App\AgentKit\Telemetry\TraceContext;
use App\AgentKit\Tools\ToolContext;
use App\AgentKit\Tools\ToolInterface;
use App\AgentKit\Tools\ToolRegistry;
use App\AgentKit\Vault\CredentialResolver;
use App\AgentKit\Webhook\WebhookDispatcher;
use App\Model\AgentMemoryStoreRepository;
use App\Model\AgentSessionRepository;
use App\Model\AgentVaultRepository;

/**
 * Single-agent runner.
 *
 * One Runner -> one agent_sessions row -> one trace_id -> arbitrary number
 * of LLM calls + tool calls. The runner owns the tool-use loop:
 *   while (response.stop_reason == 'tool_use') {
 *       execute tools
 *       feed results back as a user message
 *       call LLM again
 *   }
 *
 * Outcome iteration loop (when agent has a rubric):
 *   for iteration in 0..max_iterations:
 *       run the conversation to end_turn
 *       call grader on the transcript
 *       if satisfied: end
 *       else: prepend grader feedback to next user message and retry
 *
 * Errors:
 *  - LLMTransientError: retry with backoff up to 3 attempts; then fall
 *    back to model_fallback_uri if defined; else terminate session error.
 *  - LLMPermanentError: fall back immediately if defined; else terminate.
 *  - Tool errors: surfaced to the LLM as is_error=true; never crash.
 */
final class Runner
{
	private const MAX_LLM_CALLS_PER_ITERATION = 30; // hard cap on tool-use loop
	private const TRANSIENT_RETRY_DELAYS_S = [1, 4, 12];

	/**
	 * SESSION CEILINGS — the bound that did not exist (2026-08-16).
	 *
	 * The three caps above are PER ITERATION and multiply: 600s per SDK
	 * request × 30 calls × 10 iterations is roughly fifteen hours for one
	 * stuck agent, and nothing at all counted tokens. `docs/idea/11-agentic-loop.md`
	 * §5 is titled "Bounded, because unbounded is the failure mode"; the
	 * session was the level with no bound.
	 *
	 * Both are BACKSTOPS, not budgets. Measured against a real ceremony (the
	 * conductor run of 2026-08-13: in=97, out=10128), the token ceiling is
	 * ~24× a healthy session — it exists to stop a runaway, not to shape one.
	 * Env-overridable so an operator can tighten for a supervised night
	 * without a code change.
	 *
	 * WHAT EACH ONE COVERS, precisely, because a bound that is believed wider
	 * than it is would be worse than none:
	 *   * the wall clock is checked before every Runner-driven LLM call AND at
	 *     the top of every outcome iteration, so it bounds the grader too;
	 *   * the token ceiling counts only what Runner itself drives. The Grader
	 *     holds its own client (`new Grader($graderLlm)`) and its spend is
	 *     bounded by maxIterations and by the clock, not by this number.
	 */
	private const SESSION_WALL_CLOCK_S = 3600;
	private const SESSION_TOKEN_CEILING = 250000;

	public function __construct(
		private readonly LLMFactory $llmFactory,
		private readonly ToolRegistry $tools,
		private readonly CredentialResolver $credentials,
		private readonly AgentSessionRepository $sessions,
		private readonly AgentVaultRepository $vaults,
		private readonly AuditEmitter $audit,
		private readonly OtelExporter $otel,
		private readonly WebhookDispatcher $webhooks,
		private readonly AgentLoader $loader,
		// Optional, post-A14: Dreams (memory consolidation). When the
		// repository is wired (DI auto-resolves it), loadMemoryContext()
		// can pull recent entries; absent injection means run() never
		// touches memory state and the existing tool-use loop is byte-
		// identical to A14. Optional default keeps Runner direct-
		// construction backwards compatible.
		private readonly ?AgentMemoryStoreRepository $memoryStore = null,
		// Optional, spine increment 1: resolves an agent's `model.backend`
		// declaration into a Binding (or refuses — see BindingRefused). Null
		// keeps every existing construction site byte-identical: no resolver
		// means no agent can route anywhere but the default backend, which is
		// the fail-closed shape the whole binding layer inherits.
		private readonly ?BindingResolver $bindingResolver = null,
	) {
	}

	/**
	 * Who actually answered, when it was not the primary.
	 *
	 * RULING 2 (docs/minimax-groundwork.md) in one property. `model_uri` is
	 * written into agent_sessions at session OPEN, from the primary client,
	 * before a single call has been made — so a fallback's answer was returned
	 * and recorded as the primary's work. That is not a cosmetic mislabel: the
	 * `events` rows are WORM-triggered and hash-chained, the RFL corpus has no
	 * provenance field and no relabelling path, so provenance is either right
	 * at write time or wrong permanently.
	 *
	 * Null means the primary served the whole session, which is the ordinary
	 * case and must stay distinguishable from "a fallback served and we did
	 * not notice".
	 *
	 * Instance state is safe here because a Runner drives one session at a
	 * time — concurrent agents each get their own process, by a mechanism that
	 * deliberately lives outside this class — but it is reset at the top of
	 * every run() so a second sequential session cannot inherit the first
	 * one's attribution.
	 */
	private ?string $servedByUri = null;

	/** Session ceilings, reset per run(). Null deadline = no session open. */
	private ?float $sessionDeadline = null;
	/**
	 * Split in/out, because a TERMINATED session must still report what it
	 * spent. `$totalIn`/`$totalOut` in run() are assigned only on the
	 * success paths; when the ceiling (or any throw) interrupts the loop
	 * they stay 0 and the session reported `tokens: {input: 0, output: 0}`
	 * after genuinely spending 168707 — measured 2026-08-16, on the run
	 * that finally filed seven briefs. A cost record that reads zero for
	 * the runs that overspend is worse than no cost record.
	 */
	private int $sessionTokensIn = 0;
	private int $sessionTokensOut = 0;

	/** Session context callWithRetry needs to attribute a fallback. */
	private ?array $fallbackContext = null;

	/**
	 * Run an agent end to end.
	 *
	 * @param string  $agentName   matches files/anatomy/agents/<name>/
	 * @param ?string $userPrompt  optional initial user message
	 * @param ?string $vaultName   optional vault to resolve credentials from
	 * @param ?string $triggerId   pulse_runs.run_id or webhook event id
	 * @param ?string $sessionUuid optional pre-allocated session UUID. The
	 *                operator-trigger API path generates the UUID before
	 *                spawning this runner so it can return 202 with the
	 *                UUID immediately and the operator can poll
	 *                /api/v1/agent-sessions/<uuid> straight away. NULL =
	 *                self-allocate (Pulse / direct CLI / webhook paths).
	 * @return RunResult
	 */
	public function run(
		string $agentName,
		?string $userPrompt = null,
		?string $vaultName = null,
		string $trigger = 'operator',
		?string $triggerId = null,
		?string $actorId = null,
		?string $sessionUuid = null,
	): RunResult {
		$agent = $this->loader->load($agentName);
		$tools = $this->tools->forAgent($agent);

		// Bind vault for credential resolution
		if ($vaultName !== null) {
			$vault = $this->vaults->findByName($vaultName);
			$this->credentials->bindVault($vault !== null ? (int) $vault['id'] : null);
		}

		$sessionUuid = $sessionUuid ?? self::uuid();
		$traceId = TraceContext::newTraceId();
		$rootSpanId = TraceContext::newSpanId();
		$startNanos = self::now();
		$resolvedActor = $actorId ?? ('agent:' . $agentName);

		// Resolve the backend binding BEFORE any session row exists: a refusal
		// (unknown backend, deferred agent, routing the agent's Article-30
		// record does not declare) must abort at the door, not mid-lineage.
		// No resolver wired → the default decision, byte-identical behaviour.
		$decision = $this->bindingResolver?->resolve($agent) ?? BindingDecision::default();
		$llm = $this->llmFactory->fromUri($agent->modelPrimaryUri, $decision->binding);
		$this->servedByUri = null;
		$this->sessionTokensIn = 0;
		$this->sessionTokensOut = 0;
		$this->sessionDeadline = microtime(true)
			+ (float) self::envInt('NOS_AGENT_SESSION_WALL_CLOCK_S', self::SESSION_WALL_CLOCK_S);
		$this->fallbackContext = [
			'session_uuid' => $sessionUuid,
			'actor_id' => $resolvedActor,
			'trace_id' => $traceId,
			'agent_name' => $agent->name,
			'primary' => $llm->identifier(),
		];
		$this->sessions->startSession([
			'uuid' => $sessionUuid,
			'agent_name' => $agent->name,
			'agent_version' => $agent->version,
			'trigger' => $trigger,
			'trigger_id' => $triggerId,
			'actor_id' => $resolvedActor,
			'trace_id' => $traceId,
			'model_uri' => $llm->identifier(),
			'outcome_id' => $agent->hasOutcome() ? 'outcome_' . substr($sessionUuid, 0, 8) : null,
		]);

		$rootSpan = new Span(
			name: 'agent.session',
			traceId: $traceId,
			spanId: $rootSpanId,
			parentSpanId: null,
			startNanos: $startNanos,
		);
		$rootSpan->setAttributes([
			'agent.name' => $agent->name,
			'agent.version' => $agent->version,
			'agent.model_primary' => $agent->modelPrimaryUri,
			'agent.backend' => $decision->backendName(),
			'agent.multiagent_type' => $agent->multiagentType,
			'agent.has_outcome' => $agent->hasOutcome(),
			'agent.trigger' => $trigger,
			'session.uuid' => $sessionUuid,
		]);

		$this->audit->emit(
			type: 'agent_session_start',
			actorActionId: $sessionUuid,
			actorId: $resolvedActor,
			task: "agent:{$agent->name}",
			result: array_merge(
				[
					'agent_version' => $agent->version,
					'model_primary' => $agent->modelPrimaryUri,
					// Which backend serves this session — write-time
					// attribution, same WORM argument as ruling 2: the events
					// table has no relabelling path, so the backend is
					// recorded when it is decided, not inferred later from
					// cost shapes.
					'backend' => $decision->backendName(),
					'trigger' => $trigger,
				],
				// Under a binding the SERVED model differs from the declared
				// URI (the binding's tier remap chose it). Absent when
				// unbound — the declared model served, and the ordinary
				// event should not grow a field that restates the URI.
				$decision->binding !== null
					? ['model_effective' => $decision->binding->modelId] : [],
			),
			traceId: $traceId,
		);
		if ($decision->declaredDisarmed !== null) {
			// Declared-but-disarmed: the agent.yml asks for a backend the
			// operator has not armed. The run proceeds on the default backend
			// (prepared-not-armed: committing a declaration must never
			// half-arm), and this event makes the dormant ask visible instead
			// of indistinguishable from "never asked".
			$this->audit->emit(
				type: 'agent_binding_disarmed',
				actorActionId: $sessionUuid,
				actorId: $resolvedActor,
				task: "agent:{$agent->name}",
				result: [
					'declared' => $decision->declaredDisarmed,
					'served_by' => $decision->backendName(),
				],
				traceId: $traceId,
			);
		}
		$this->webhooks->fire('agent_session_start', [
			'id' => $sessionUuid,
			'agent_name' => $agent->name,
			'trace_id' => $traceId,
		]);

		$threadUuid = self::uuid();
		$threadSpanId = TraceContext::newSpanId();
		$this->sessions->startThread([
			'uuid' => $threadUuid,
			'session_uuid' => $sessionUuid,
			'parent_thread_uuid' => null,
			'agent_name' => $agent->name,
			'agent_version' => $agent->version,
			'role' => 'primary',
			'trace_id' => $traceId,
			'span_id' => $threadSpanId,
		]);

		$initialPrompt = $userPrompt ?? $this->defaultPrompt($agent);
		$conversation = [Message::userText($initialPrompt)];

		$result = null;
		$totalIn = 0;
		$totalOut = 0;
		$stopReason = 'end_turn';
		$errorMessage = null;
		$spans = [$rootSpan];

		try {
			if ($agent->hasOutcome()) {
				$result = $this->runOutcomeLoop(
					$agent,
					$llm,
					$tools,
					$conversation,
					$sessionUuid,
					$threadUuid,
					$traceId,
					$threadSpanId,
					$resolvedActor,
					$spans,
				);
				$totalIn = $result['tokens_input'];
				$totalOut = $result['tokens_output'];
				$stopReason = 'outcome_' . $result['outcome_result'];
			} else {
				$loop = $this->runToolUseLoop(
					$agent,
					$llm,
					$tools,
					$conversation,
					$sessionUuid,
					$threadUuid,
					$traceId,
					$threadSpanId,
					$resolvedActor,
					$spans,
				);
				$totalIn = $loop['tokens_input'];
				$totalOut = $loop['tokens_output'];
				$stopReason = $loop['stop_reason'];
				$result = ['final_text' => $loop['final_text']];
			}
		} catch (SessionCeilingReached $exc) {
			// A CEILING IS NOT AN ERROR — it is the bound working, and the two
			// must not read alike. MEASURED 2026-08-16: the run that filed the
			// first seven briefs was stopped by a deliberate 150k ceiling and
			// landed in agent_sessions as `terminated / error / 0 tokens`,
			// byte-identical to the run that died on a 404. A reviewer reading
			// the table would call the successful ceremony a crash — and one
			// did, the same evening.
			$stopReason = 'ceiling';
			$errorMessage = $exc->getMessage();
		} catch (LLMPermanentError $exc) {
			$stopReason = 'error';
			$errorMessage = $exc->getMessage();
		} catch (\Throwable $exc) {
			$stopReason = 'error';
			$errorMessage = $exc::class . ': ' . $exc->getMessage();
		}

		// A TERMINATED run still spent. The loop totals are assigned only on the
		// success paths, so a throw leaves them 0 while the session counters
		// know better — take the larger of the two rather than reporting the
		// convenient one.
		$totalIn = max($totalIn, $this->sessionTokensIn);
		$totalOut = max($totalOut, $this->sessionTokensOut);

		$rootSpan->setAttributes([
			'agent.tokens_input' => $totalIn,
			'agent.tokens_output' => $totalOut,
			'agent.stop_reason' => $stopReason,
		]);
		if ($errorMessage !== null) {
			$rootSpan->setError($errorMessage);
		}
		$rootSpan->end();
		$this->otel->export($spans);

		$this->sessions->endThread($threadUuid, $stopReason, $totalIn, $totalOut);
		$this->sessions->endSession(
			$sessionUuid,
			$errorMessage === null ? 'idle' : 'terminated',
			$stopReason,
			array_merge(
				[
					'tokens_input' => $totalIn,
					'tokens_output' => $totalOut,
					'result_json' => $result,
					'error_json' => $errorMessage !== null ? ['message' => $errorMessage] : null,
					'outcome_result' => $result['outcome_result'] ?? null,
				],
				// Correct the attribution to whoever actually answered. Written
				// at session END rather than at open, because at open nobody has
				// answered yet — which is the whole defect this closes. Absent
				// key when the primary served, so the ordinary row is untouched.
				$this->servedByUri !== null ? ['model_uri' => $this->servedByUri] : [],
			),
		);

		$this->audit->emit(
			type: 'agent_session_end',
			actorActionId: $sessionUuid,
			actorId: $resolvedActor,
			task: "agent:{$agent->name}",
			result: [
				'stop_reason' => $stopReason,
				'tokens' => ['input' => $totalIn, 'output' => $totalOut],
				'error' => $errorMessage,
			],
			traceId: $traceId,
		);
		$this->webhooks->fire('agent_session_end', [
			'id' => $sessionUuid,
			'agent_name' => $agent->name,
			'stop_reason' => $stopReason,
			'trace_id' => $traceId,
			'has_error' => $errorMessage !== null,
		]);

		return new RunResult(
			sessionUuid: $sessionUuid,
			traceId: $traceId,
			status: $errorMessage === null ? 'idle' : 'terminated',
			stopReason: $stopReason,
			tokensInput: $totalIn,
			tokensOutput: $totalOut,
			result: $result,
			error: $errorMessage,
		);
	}

	/**
	 * @param array<int, ToolInterface> $tools
	 * @param array<int, Message> $conversation
	 * @param array<int, Span> &$spans
	 * @return array{stop_reason: string, tokens_input: int, tokens_output: int, final_text: string, conversation: array<int, Message>}
	 *
	 * `conversation` is RETURNED, and that is the fix for a defect this method
	 * carried from the start (found 2026-08-04). `$conversation` is taken BY
	 * VALUE — deliberately, so each outcome iteration restarts from prompt +
	 * feedback — which means every assistant reply and every tool result the
	 * agent produced died with the local copy when this returned. The caller
	 * then built the grader's transcript from the OUTER conversation, so on
	 * iteration 0 the grader was handed nothing but the original prompt.
	 *
	 * The Grader's own system prompt promises otherwise: "You CANNOT see the
	 * agent's reasoning, only the artifact + its conversation transcript." The
	 * transcript was the half that never arrived, so the outcome loop was
	 * grading a blank page and its verdicts meant nothing.
	 *
	 * Returned rather than passed by reference on purpose: `&$conversation`
	 * would ALSO carry the inner messages into the next iteration and silently
	 * change the iteration contract (and its cost). That is a separate
	 * decision, not a bug fix — see the note at the call site.
	 */
	private function runToolUseLoop(
		Agent $agent,
		LLMClientInterface $llm,
		array $tools,
		array $conversation,
		string $sessionUuid,
		string $threadUuid,
		string $traceId,
		string $threadSpanId,
		string $actorId,
		array &$spans,
	): array {
		$toolSchemas = array_map(static fn (ToolInterface $t) => $t->schema(), $tools);
		$toolByName = [];
		foreach ($tools as $t) {
			$toolByName[$t->schema()->name] = $t;
		}

		$totalIn = 0;
		$totalOut = 0;
		$stopReason = 'end_turn';
		$finalText = '';

		for ($call = 0; $call < self::MAX_LLM_CALLS_PER_ITERATION; $call++) {
			$callSpanId = TraceContext::newSpanId();
			$callStart = self::now();
			$callSpan = new Span(
				name: 'llm.call',
				traceId: $traceId,
				spanId: $callSpanId,
				parentSpanId: $threadSpanId,
				startNanos: $callStart,
			);
			$callSpan->setAttribute('llm.model_uri', $llm->identifier());
			$callSpan->setAttribute('llm.call_index', $call);

			$this->assertSessionCeiling('llm_call');
			$response = $this->callWithRetry($agent, $llm, $conversation, $toolSchemas);
			$totalIn += $response->tokensInput;
			$totalOut += $response->tokensOutput;
			$this->sessionTokensIn += $response->tokensInput;
			$this->sessionTokensOut += $response->tokensOutput;

			$callSpan->setAttributes([
				'llm.stop_reason' => $response->stopReason,
				'llm.tokens_input' => $response->tokensInput,
				'llm.tokens_output' => $response->tokensOutput,
			]);
			$callSpan->end();
			$spans[] = $callSpan;

			$conversation[] = new Message('assistant', $response->contentBlocks);

			$this->audit->emit(
				type: 'agent_message',
				actorActionId: $sessionUuid,
				actorId: $actorId,
				task: "agent:{$agent->name}/llm.call.{$call}",
				result: [
					'stop_reason' => $response->stopReason,
					'text_preview' => substr($response->textOutput(), 0, 240),
					// Full assistant text — the operator /agents session view
					// renders the verbatim LLM chat history from this field;
					// text_preview is retained for lean digest consumers.
					'text' => $response->textOutput(),
					// Only backends that STATE their own cost fill this (the
					// claude CLI's total_cost_usd); token tallies cannot
					// reconstruct it. Absent, not zero, when unreported.
					'cost_usd' => $response->costUsd,
				],
				traceId: $traceId,
			);

			$toolUses = $response->toolUseBlocks();
			if ($response->stopReason !== 'tool_use' || $toolUses === []) {
				$stopReason = $response->stopReason;
				$finalText = $response->textOutput();
				break;
			}

			// Execute tools, collect results
			$results = [];
			foreach ($toolUses as $use) {
				$tool = $toolByName[$use['name']] ?? null;
				$toolSpanId = TraceContext::newSpanId();
				$toolSpan = new Span(
					name: 'tool.use',
					traceId: $traceId,
					spanId: $toolSpanId,
					parentSpanId: $callSpanId,
					startNanos: self::now(),
				);
				$toolSpan->setAttributes([
					'tool.name' => $use['name'],
					'tool.use_id' => $use['id'],
				]);

				$this->audit->emit(
					type: 'agent_tool_use',
					actorActionId: $sessionUuid,
					actorId: $actorId,
					task: "agent:{$agent->name}/tool:{$use['name']}",
					result: [
						'tool_use_id' => $use['id'],
						'input' => $use['input'],
					],
					traceId: $traceId,
				);

				if ($tool === null) {
					$results[] = [
						'tool_use_id' => $use['id'],
						'content' => "tool '{$use['name']}' not registered",
						'is_error' => true,
					];
					$toolSpan->setError("unknown tool {$use['name']}");
					$toolSpan->end();
					$spans[] = $toolSpan;
					continue;
				}

				$context = new ToolContext(
					sessionUuid: $sessionUuid,
					threadUuid: $threadUuid,
					traceId: $traceId,
					parentSpanId: $callSpanId,
					actorId: $actorId,
					toolUseId: $use['id'],
				);
				try {
					$toolResult = $tool->execute($use['input'], $context);
				} catch (\Throwable $exc) {
					$toolResult = \App\AgentKit\Tools\ToolResult::error(
						'tool exception: ' . $exc->getMessage()
					);
				}
				$toolSpan->setAttributes($toolResult->metadata);
				if ($toolResult->isError) {
					$toolSpan->setError(substr($toolResult->content, 0, 200));
				}
				$toolSpan->end();
				$spans[] = $toolSpan;

				$this->audit->emit(
					type: 'agent_tool_result',
					actorActionId: $sessionUuid,
					actorId: $actorId,
					task: "agent:{$agent->name}/tool:{$use['name']}",
					result: [
						'tool_use_id' => $use['id'],
						'is_error' => $toolResult->isError,
						'content_preview' => substr($toolResult->content, 0, 240),
						// Full tool output — rendered verbatim in the session
						// transcript; content_preview kept for digest consumers.
						'content' => $toolResult->content,
						'metadata' => $toolResult->metadata,
					],
					traceId: $traceId,
				);

				$results[] = [
					'tool_use_id' => $use['id'],
					'content' => $toolResult->content,
					'is_error' => $toolResult->isError,
				];
			}
			$conversation[] = Message::userToolResults($results);
		}

		return [
			'stop_reason' => $stopReason,
			'tokens_input' => $totalIn,
			'tokens_output' => $totalOut,
			'final_text' => $finalText,
			// The work itself. Without this the grader sees only the prompt.
			'conversation' => $conversation,
		];
	}

	/**
	 * Outcome-driven iteration. Run the tool-use loop, grade, repeat.
	 *
	 * @param array<int, ToolInterface> $tools
	 * @param array<int, Message> $conversation
	 * @param array<int, Span> &$spans
	 * @return array{outcome_result: string, iterations: int, tokens_input: int, tokens_output: int, final_text: string}
	 */
	private function runOutcomeLoop(
		Agent $agent,
		LLMClientInterface $llm,
		array $tools,
		array $conversation,
		string $sessionUuid,
		string $threadUuid,
		string $traceId,
		string $threadSpanId,
		string $actorId,
		array &$spans,
	): array {
		// The judge and the proposer must not share an identity. Bone's loop
		// engine states it outright ("The judge is code. The proposer is a
		// model."); this layer said the opposite in a trailing comment — "grader
		// uses the same LLM family" — and meant it literally: the same client
		// instance graded the work it had just produced.
		//
		// `model.grader` in agent.yml splits them. When it is absent the old
		// behaviour stands, because forcing a second model on every agent would
		// change cost for agents whose grade gates nothing; but the sharing is now
		// a declared choice per agent instead of a property of the code.
		$graderLlm = $agent->modelGraderUri !== null
			? $this->llmFactory->fromUri($agent->modelGraderUri)
			: $llm;
		$grader = new Grader($graderLlm);
		$totalIn = 0;
		$totalOut = 0;
		$result = 'failed';
		$finalText = '';
		$outcomeId = 'outcome_' . substr($sessionUuid, 0, 8);

		for ($iteration = 0; $iteration < $agent->maxIterations; $iteration++) {
			// Checked here too, so the clock bounds the GRADER — which holds
			// its own client and whose spend the token ceiling cannot see.
			$this->assertSessionCeiling('iteration');
			$iterStart = (int) (microtime(true) * 1000);
			$loopOut = $this->runToolUseLoop(
				$agent,
				$llm,
				$tools,
				$conversation,
				$sessionUuid,
				$threadUuid,
				$traceId,
				$threadSpanId,
				$actorId,
				$spans,
			);
			$totalIn += $loopOut['tokens_input'];
			$totalOut += $loopOut['tokens_output'];
			$finalText = $loopOut['final_text'];

			// Build transcript for grader — from the conversation the tool-use
			// loop ACTUALLY had, not the outer one it was handed. Passing
			// `$conversation` here was the defect: the outer array never
			// receives the inner assistant/tool messages, so on iteration 0 it
			// is literally just the prompt.
			//
			// NOT CHANGED, and it is a live question rather than an oversight:
			// the next iteration still restarts from prompt + feedback, so the
			// agent does not see its own previous attempt. That is arguably
			// wrong too, but changing it alters what an iteration costs and
			// means, so it belongs to whoever decides what this loop is FOR.
			$transcript = $this->summariseConversation($loopOut['conversation'] ?? $conversation);
			$gradeStart = self::now();
			$gradeSpanId = TraceContext::newSpanId();
			$gradeSpan = new Span(
				name: 'grader.iteration',
				traceId: $traceId,
				spanId: $gradeSpanId,
				parentSpanId: $threadSpanId,
				startNanos: $gradeStart,
			);
			$gradeSpan->setAttributes([
				'grader.iteration' => $iteration,
				'grader.rubric_path' => $agent->rubric->sourcePath,
			]);

			$grade = $grader->grade($agent->description, $agent->rubric, $transcript);
			$totalIn += $grade['tokens_input'];
			$totalOut += $grade['tokens_output'];

			$gradeSpan->setAttributes([
				'grader.result' => $grade['result'],
				'grader.tokens_input' => $grade['tokens_input'],
				'grader.tokens_output' => $grade['tokens_output'],
			]);
			$gradeSpan->end();
			$spans[] = $gradeSpan;

			$durationMs = (int) (microtime(true) * 1000) - $iterStart;
			$this->sessions->recordIteration(
				$sessionUuid,
				$iteration,
				$grade['result'],
				$grade['feedback'],
				$llm->identifier(),
				$durationMs,
				$grade['tokens_input'],
				$grade['tokens_output'],
			);
			$this->audit->emit(
				type: 'agent_grader_decision',
				actorActionId: $sessionUuid,
				actorId: $actorId,
				task: "agent:{$agent->name}/grader.{$iteration}",
				result: [
					'iteration' => $iteration,
					'grader_result' => $grade['result'],
					'feedback_preview' => substr($grade['feedback'], 0, 240),
				],
				traceId: $traceId,
			);
			$this->webhooks->fire('agent_outcome_iteration', [
				'session_id' => $sessionUuid,
				'outcome_id' => $outcomeId,
				'iteration' => $iteration,
				'result' => $grade['result'],
			]);

			$result = $grade['result'];
			if ($result === 'satisfied' || $result === 'failed') {
				return [
					'outcome_result' => $result,
					'iterations' => $iteration + 1,
					'tokens_input' => $totalIn,
					'tokens_output' => $totalOut,
					'final_text' => $finalText,
				];
			}
			// needs_revision -> append grader feedback as a user message and loop
			$conversation[] = Message::userText(
				"GRADER FEEDBACK (iteration {$iteration}, result=needs_revision):\n\n" .
				$grade['feedback'] . "\n\nPlease revise."
			);
		}

		return [
			'outcome_result' => 'max_iterations_reached',
			'iterations' => $agent->maxIterations,
			'tokens_input' => $totalIn,
			'tokens_output' => $totalOut,
			'final_text' => $finalText,
		];
	}

	private function callWithRetry(
		Agent $agent,
		LLMClientInterface $llm,
		array $conversation,
		array $toolSchemas,
	): \App\AgentKit\LLMClient\LLMResponse {
		$attempt = 0;
		$lastTransient = null;
		foreach (self::TRANSIENT_RETRY_DELAYS_S as $delay) {
			try {
				return $llm->send(
					$agent->systemPrompt ?? '',
					$conversation,
					$toolSchemas,
					$agent->maxOutputTokens,
				);
			} catch (LLMTransientError $exc) {
				$lastTransient = $exc;
				$attempt++;
				if ($attempt < count(self::TRANSIENT_RETRY_DELAYS_S)) {
					sleep($delay);
				}
			} catch (LLMCapabilityError $exc) {
				// NO FALLBACK for a capability refusal, and the ordering of
				// this catch above LLMPermanentError is the entire fix. The
				// refusal says the REQUEST's shape cannot be honoured (e.g. the
				// claude CLI cannot be handed tool schemas); re-sending the
				// identical request to `modelFallbackUri` would either hit the
				// same wall or — worse — reach a backend that "accepts" tools
				// as an unenforced hint, converting a loud refusal into the
				// silent drop it exists to prevent. The caller must change the
				// request (drop the tools, rewrite the ceremony) or change the
				// PRIMARY to a backend that speaks the missing protocol; a
				// fallback cannot decide either of those on its behalf.
				throw $exc;
			} catch (LLMPermanentError $exc) {
				if ($agent->modelFallbackUri !== null) {
					return $this->serveFallback($agent, $conversation, $toolSchemas, 'permanent_error', $exc);
				}
				throw $exc;
			}
		}
		// Exhausted transient retries
		if ($agent->modelFallbackUri !== null) {
			return $this->serveFallback($agent, $conversation, $toolSchemas, 'transient_exhausted', $lastTransient);
		}
		throw $lastTransient ?? new LLMPermanentError('LLM call failed without exception');
	}

	/**
	 * An env override, where ZERO is a value and not an absence.
	 *
	 * `getenv($k) ?: $default` reads "0" as empty and silently restores the
	 * default — so the tightest setting an operator can ask for was the one
	 * setting that could not be applied. Measured 2026-08-16 by trying to
	 * prove the wall-clock brake with `NOS_AGENT_SESSION_WALL_CLOCK_S=0`: the
	 * session ran to completion on 2335 tokens, because the 0 became 3600.
	 * The same shape as `getenv()` returning `false` for unset, one operator
	 * two hours earlier — falsiness standing in for absence.
	 */
	private static function envInt(string $name, int $default): int
	{
		$raw = getenv($name);
		if ($raw === false || trim($raw) === '') {
			return $default;
		}
		return (int) $raw;
	}

	/**
	 * Refuse to spend past a session ceiling — BEFORE the spend, not after.
	 *
	 * Throws `SessionCeilingReached`, which `run()` catches like any other
	 * terminal error: the session ends `terminated` with the reason recorded,
	 * so a run that hit a wall is distinguishable from one that finished. A
	 * ceiling discovered by reading the bill afterwards is not a ceiling.
	 *
	 * @param string $at where the check fired — 'llm_call' or 'iteration'.
	 */
	private function assertSessionCeiling(string $at): void
	{
		if ($this->sessionDeadline === null) {
			return; // no session open (direct unit-level use of the loop)
		}
		$tokenCeiling = self::envInt(
			'NOS_AGENT_SESSION_TOKEN_CEILING', self::SESSION_TOKEN_CEILING
		);
		if (microtime(true) >= $this->sessionDeadline) {
			throw new SessionCeilingReached(
				"session wall clock exhausted at {$at}: the run passed its "
				. 'deadline before this call. Per-call and per-iteration caps '
				. 'multiply; this is the session-level bound that stops them.'
			);
		}
		$spent = $this->sessionTokensIn + $this->sessionTokensOut;
		if ($spent >= $tokenCeiling) {
			throw new SessionCeilingReached(
				"session token ceiling reached at {$at}: {$spent} "
				. ">= {$tokenCeiling}. Counts what Runner drives; the grader's "
				. 'own client is bounded by the clock and by maxIterations.'
			);
		}
	}

	/**
	 * Hand the call to the fallback, and say so — in that order of importance.
	 *
	 * Both fallback sites route through here so they cannot drift: one used to
	 * be reached by an unrecognised error phrase and the other by exhausted
	 * retries, and NEITHER left any trace that a different model answered.
	 *
	 * THE MESSAGE IS THE POINT, not just the switch. Ruling 2 chose fail-closed
	 * classification — an unrecognised phrase stays permanent and is not
	 * retried — on the condition that the unmatched message be logged, so a
	 * foreign backend's actual phrasings can be learned from one outage instead
	 * of guessed. `ClaudeCliAdapter` matches three Anthropic strings
	 * ('rate limit', 'overloaded', 'usage limit'); everything else lands here,
	 * and until now landed silently.
	 */
	private function serveFallback(
		Agent $agent,
		array $conversation,
		array $toolSchemas,
		string $reason,
		?\Throwable $cause,
	): \App\AgentKit\LLMClient\LLMResponse {
		$fallback = $this->llmFactory->fromUri($agent->modelFallbackUri);
		$this->servedByUri = $fallback->identifier();
		$ctx = $this->fallbackContext ?? [];

		$this->audit->emit(
			type: 'agent_model_fallback',
			actorActionId: $ctx['session_uuid'] ?? null,
			actorId: $ctx['actor_id'] ?? ('agent:' . $agent->name),
			task: "agent:{$agent->name}",
			result: [
				'reason' => $reason,
				'primary' => $ctx['primary'] ?? $agent->modelPrimaryUri,
				'fallback' => $this->servedByUri,
				// Verbatim, and unmatched by the classifier — this is the
				// string a future rule would be written against.
				'unmatched_message' => $cause?->getMessage(),
				'cause_class' => $cause !== null ? get_class($cause) : null,
			],
			traceId: $ctx['trace_id'] ?? null,
		);

		return $fallback->send(
			$agent->systemPrompt ?? '',
			$conversation,
			$toolSchemas,
			// The SAME cap as the primary. A fallback that silently writes
			// less would make a truncated answer look like a shorter one.
			$agent->maxOutputTokens,
		);
	}

	private function defaultPrompt(Agent $agent): string
	{
		if ($agent->hasOutcome()) {
			return "Begin work on the outcome described in your system prompt. " .
				"You have access to the declared tools. The grader will score your " .
				"final state against rubric: {$agent->rubric->sourcePath}.";
		}
		return "Begin work as defined in your system prompt. Use the declared tools as needed.";
	}

	/**
	 * @param array<int, Message> $conversation
	 */
	private function summariseConversation(array $conversation): string
	{
		$lines = [];
		foreach ($conversation as $i => $msg) {
			$role = $msg->role;
			$texts = [];
			$toolUses = [];
			$toolResults = [];
			foreach ($msg->content as $block) {
				$type = $block['type'] ?? '';
				if ($type === 'text') {
					$texts[] = (string) ($block['text'] ?? '');
				} elseif ($type === 'tool_use') {
					$toolUses[] = ($block['name'] ?? '?') . '(' . json_encode($block['input'] ?? []) . ')';
				} elseif ($type === 'tool_result') {
					$content = $block['content'] ?? '';
					if (!is_string($content)) {
						$content = json_encode($content) ?: '';
					}
					$toolResults[] = substr($content, 0, 400);
				}
			}
			$body = trim(implode("\n", array_filter([
				implode("\n", $texts),
				$toolUses === [] ? '' : 'TOOL_USE: ' . implode('; ', $toolUses),
				$toolResults === [] ? '' : 'TOOL_RESULT: ' . implode("\n---\n", $toolResults),
			])));
			$lines[] = "[{$i}] {$role}:\n{$body}";
		}
		return implode("\n\n", $lines);
	}

	private static function uuid(): string
	{
		$d = random_bytes(16);
		$d[6] = chr((ord($d[6]) & 0x0f) | 0x40);
		$d[8] = chr((ord($d[8]) & 0x3f) | 0x80);
		return vsprintf('%s%s-%s-%s-%s-%s%s%s', str_split(bin2hex($d), 4));
	}

	private static function now(): int
	{
		return (int) (microtime(true) * 1_000_000_000);
	}

	/**
	 * Load recent memory entries for an agent (Dreams, post-A14).
	 *
	 * APPENDED AT END OF CLASS by design — the multi-worker batch contract
	 * (U-B-Dreams ↔ U-B-MA scope partition) keeps Runner.php diff-orthogonal
	 * to anything U-B-MA might add to run() / runOutcomeLoop / runToolUseLoop
	 * higher up in the file. Caller (Runner::run() consumers, OR
	 * bin/dream-agent.php) decides whether to inject the entries into the
	 * system prompt; this method is read-only and side-effect-free.
	 *
	 * Telemetry: NEVER log full content — memory entries are not secrets,
	 * but they DO carry task context that may include operator notes (same
	 * sensitivity profile as event text). Callers that surface entries in
	 * spans / events should redact to (uuid, title, length).
	 *
	 * Returns an empty array when no AgentMemoryStoreRepository is wired
	 * (older bootstraps, tests that construct Runner without the optional
	 * dep) — graceful degradation, not an error.
	 *
	 * @return array<int, array<string, mixed>>  recent entries, most-recent first
	 */
	public function loadMemoryContext(?string $agentName, int $limit = 5): array
	{
		if ($this->memoryStore === null) {
			return [];
		}
		if ($agentName === null || $agentName === '') {
			return [];
		}
		if ($limit < 1) {
			return [];
		}
		return $this->memoryStore->listRecent($agentName, $limit);
	}
}

/**
 * Returned to the CLI / Pulse runner. Lightweight value object summarising
 * the run; the full lineage lives in agent_sessions / agent_threads /
 * agent_iterations / events / Tempo traces.
 */
final class RunResult
{
	public function __construct(
		public readonly string $sessionUuid,
		public readonly string $traceId,
		public readonly string $status,
		public readonly string $stopReason,
		public readonly int $tokensInput,
		public readonly int $tokensOutput,
		public readonly mixed $result,
		public readonly ?string $error,
	) {
	}

	public function isSuccessful(): bool
	{
		return $this->error === null && in_array($this->stopReason, ['end_turn', 'outcome_satisfied'], true);
	}
}
