<?php

declare(strict_types=1);

namespace App\AgentKit;

use App\AgentKit\LLMClient\Factory as LLMFactory;
use App\AgentKit\LLMClient\LLMClientInterface;
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
	) {
	}

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

		$llm = $this->llmFactory->fromUri($agent->modelPrimaryUri);
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
			result: [
				'agent_version' => $agent->version,
				'model_primary' => $agent->modelPrimaryUri,
				'trigger' => $trigger,
			],
			traceId: $traceId,
		);
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
		} catch (LLMPermanentError $exc) {
			$stopReason = 'error';
			$errorMessage = $exc->getMessage();
		} catch (\Throwable $exc) {
			$stopReason = 'error';
			$errorMessage = $exc::class . ': ' . $exc->getMessage();
		}

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
			[
				'tokens_input' => $totalIn,
				'tokens_output' => $totalOut,
				'result_json' => $result,
				'error_json' => $errorMessage !== null ? ['message' => $errorMessage] : null,
				'outcome_result' => $result['outcome_result'] ?? null,
			],
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
	 * @return array{stop_reason: string, tokens_input: int, tokens_output: int, final_text: string}
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

			$response = $this->callWithRetry($agent, $llm, $conversation, $toolSchemas);
			$totalIn += $response->tokensInput;
			$totalOut += $response->tokensOutput;

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
		$grader = new Grader($llm); // grader uses the same LLM family
		$totalIn = 0;
		$totalOut = 0;
		$result = 'failed';
		$finalText = '';
		$outcomeId = 'outcome_' . substr($sessionUuid, 0, 8);

		for ($iteration = 0; $iteration < $agent->maxIterations; $iteration++) {
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

			// Build transcript for grader
			$transcript = $this->summariseConversation($conversation);
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
				);
			} catch (LLMTransientError $exc) {
				$lastTransient = $exc;
				$attempt++;
				if ($attempt < count(self::TRANSIENT_RETRY_DELAYS_S)) {
					sleep($delay);
				}
			} catch (LLMPermanentError $exc) {
				if ($agent->modelFallbackUri !== null) {
					$fallback = $this->llmFactory->fromUri($agent->modelFallbackUri);
					return $fallback->send(
						$agent->systemPrompt ?? '',
						$conversation,
						$toolSchemas,
					);
				}
				throw $exc;
			}
		}
		// Exhausted transient retries
		if ($agent->modelFallbackUri !== null) {
			$fallback = $this->llmFactory->fromUri($agent->modelFallbackUri);
			return $fallback->send(
				$agent->systemPrompt ?? '',
				$conversation,
				$toolSchemas,
			);
		}
		throw $lastTransient ?? new LLMPermanentError('LLM call failed without exception');
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
