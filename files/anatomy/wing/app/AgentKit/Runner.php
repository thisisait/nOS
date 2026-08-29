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
use App\AgentKit\Outcome\GateOracle;
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
 * Outcome iteration loop (when agent declares outcomes.gateset):
 *   for iteration in 0..max_iterations:
 *       run the conversation to end_turn
 *       run the named gate set; its EXIT is the verdict
 *       if it passed: end
 *       else: feed the gate's own output back (plus a declared grader's
 *             feedback, when the agent has one) and retry
 *       stop one iteration after a peak that was not beaten
 *   report the BEST-scored iteration, not the last one
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
	 * Calls held back from the working budget so the iteration can END rather
	 * than merely STOP. One is enough: the turn carries the whole conversation,
	 * so the model has everything it gathered in front of it.
	 */
	private const SYNTHESIS_CALLS_RESERVED = 1;

	/**
	 * Tokens held back from the session ceiling for the compacted wrap-up.
	 *
	 * MEASURED, not chosen: the surveyor's ceiling run spent 260 745 INPUT
	 * tokens producing 2 558 of output, because every turn resends the whole
	 * conversation and the conversation is mostly tool results — file bodies,
	 * directory listings, API payloads. A wrap-up that replayed all of that
	 * would cost another quarter-million and could not fit under any reserve
	 * worth the name.
	 *
	 * `compactForSynthesis()` therefore drops the tool traffic and keeps what
	 * the model itself wrote, which for that run was those same 2 558 tokens.
	 * 20 000 is roughly 8× the largest such transcript observed, leaving room
	 * for the report itself.
	 */
	private const SYNTHESIS_TOKEN_RESERVE = 20000;

	/**
	 * Floor for the headroom, and the whole of it before any call has been
	 * measured. Sized for the COMPACTED wrap-up (2 558 tokens was the largest
	 * such transcript observed, and the report itself is a few thousand more),
	 * not for a full replay — that is what `compactForSynthesis()` is for.
	 */
	private const SYNTHESIS_MIN_RESERVE = 8000;

	/**
	 * Deliberately not "summarise". The agents that reach this point have been
	 * reading for twenty-nine turns and a summary invites a table of contents;
	 * what the grader needs is the ceremony's actual output, in the shape the
	 * agent's own system prompt asked for. It also says what is true — the
	 * budget is spent — because an agent told it may still look will look.
	 */
	private const SYNTHESIS_PROMPT = <<<'TXT'
		This is your FINAL turn. The tool budget for this run is spent, no
		further tools are available to you, and nothing you ask for now will
		arrive. Do not plan more investigation and do not describe what you
		would do next.

		Write your report now, in the format your instructions specified, from
		what you have already gathered. Partial findings clearly labelled as
		partial are worth far more than an apology or an outline: state what you
		established, what you could not reach, and what you would look at first
		with more budget.
		TXT;

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
	 *   * the token ceiling counts only what Runner itself drives. A declared
	 *     grader (`Grader::forUri`) holds its own client and its spend is
	 *     bounded by maxIterations and by the clock, not by this number. The
	 *     gate-set subprocess spends no tokens at all — it is code.
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

	/** The binding serving THIS session, so the fallback can be held to it. */
	private ?\App\AgentKit\LLMClient\Binding $activeBinding = null;

	/** Providers a binding can steer — Factory refuses every other. */
	private function isBindableUri(?string $uri): bool
	{
		return $uri !== null && (bool) preg_match('#^(anthropic|claude)-#', $uri);
	}

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

	/**
	 * The most expensive single call this session has made, in+out.
	 *
	 * Sizes the ceiling headroom (see assertSessionCeiling). The conversation
	 * only grows, so the largest call so far is the honest lower bound on what
	 * the next one will cost — and a reserve smaller than that is spent by the
	 * very call it was meant to leave room after, which is how the first two
	 * versions of the headroom failed.
	 */
	private int $sessionLargestCall = 0;

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
		$this->activeBinding = $decision->binding;
		$this->servedByUri = null;
		$this->sessionTokensIn = 0;
		$this->sessionTokensOut = 0;
		$this->sessionLargestCall = 0;
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

		// A THROW HERE USED TO ORPHAN THE ROW (found 2026-08-18, by causing it).
		//
		// The session row is already inserted and `running`; the main try/catch
		// that would mark it `terminated` does not begin for another seventy
		// lines. Until this morning nothing could throw here — `AuditEmitter`
		// swallowed everything — so the gap was unreachable. Making the chain
		// refusal fatal (rightly: an agent that cannot be audited cannot do its
		// job) made it reachable, and the first shell invocation that lacked
		// the daemon's environment left exactly one row `running` forever.
		//
		// That row is not cosmetic. `agent_sessions` is the table this estate
		// reads to answer "has the bound loop ever completed a ceremony", and a
		// row that will never finish is indistinguishable from one in progress.
		// A run that cannot start must fail CLOSED and CLEAN.
		try {
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
		} catch (\Throwable $exc) {
			// The row is already inserted and `running`, and the main try/catch
			// that would mark it `terminated` does not begin for another forty
			// lines — so a throw in here orphans it.
			$this->sessions->endSession(
				$sessionUuid,
				'terminated',
				'error',
				['error_json' => json_encode([
					'class' => $exc::class,
					'message' => $exc->getMessage(),
					'at' => 'session_start_audit',
				], JSON_UNESCAPED_SLASHES)],
			);
			throw $exc;
		}

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
			if ($agent->isOneShot()) {
				// ONE call, no retry: a retried send is a second call, and the
				// number of calls is the measurement. A transient failure is
				// not a measurement — it falls through to `terminated`.
				$result = OneShot::run($llm, $agent, $initialPrompt);
				$totalIn = $result['tokens_input'];
				$totalOut = $result['tokens_output'];
				$this->sessionTokensIn += $totalIn;
				$this->sessionTokensOut += $totalOut;
				$stopReason = 'one_shot_' . $result['verdict'];
			} elseif ($agent->hasOutcome()) {
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
		// NOT 'end_turn'. That value is a CLAIM — the model said it was done —
		// and until 2026-08-18 it was also what this method returned when the
		// call cap cut the loop off mid-work, because the initialiser was never
		// overwritten on the exhaustion path. A loop that gave up reported the
		// stop reason meaning "the model finished", with `final_text: ''`
		// attached, and the grader downstream duly failed an outcome nobody had
		// written. The estate's own rule, from `docs/hidden_fees/`: a success
		// marker must not be written by the code that attempted the work.
		// Start pessimistic; only a real reply may improve it.
		$stopReason = 'call_cap';
		$finalText = '';
		$synthesisAnnounced = false;

		for ($call = 0; $call < self::MAX_LLM_CALLS_PER_ITERATION; $call++) {
			// THE SYNTHESIS TURN (2026-08-18). Measured across all 14 bound
			// sessions: zero reached `run_end`, and the shape was identical
			// every time — the model walks the estate, calls a tool, reads the
			// result, calls another, and is still doing exactly that when the
			// budget ends. It never wrote the report because nothing ever told
			// it to stop gathering, and the CLI path only looked better because
			// its own harness does this for us.
			//
			// So the last call of every iteration is reserved: the tool
			// schemas are withheld, and the model is told plainly that this is
			// the final turn. With no tools on offer, the only move left is
			// prose. This costs one call out of thirty and converts a run that
			// produced nothing into one that produces its best answer so far.
			//
			// THAT WAS HALF THE FIX (corrected the same day, by running it). The
			// call cap is not the bound that binds: the first bound run under
			// this code died on the SESSION TOKEN CEILING at call 23 of 30, so
			// this reservation was never reached. The other half is the catch
			// below, which turns that ceiling into the same wrap-up turn.
			$isSynthesis = $call >= self::MAX_LLM_CALLS_PER_ITERATION - self::SYNTHESIS_CALLS_RESERVED;
			if ($isSynthesis && !$synthesisAnnounced) {
				$conversation[] = Message::userText(self::SYNTHESIS_PROMPT);
				$synthesisAnnounced = true;
			}
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

			try {
				$this->assertSessionCeiling('llm_call');
			} catch (SessionCeilingReached $exc) {
				// THE BOUND THAT ACTUALLY BINDS. Rather than leaving the run with
				// nothing, spend the reserved headroom on one compacted wrap-up
				// and return it. The ceiling still holds — `compactForSynthesis()`
				// throws the tool traffic away, so the call costs thousands rather
				// than the quarter-million a full replay would.
				//
				// If the wrap-up ITSELF cannot fit, the throw stands: a bound that
				// can be talked past on the second attempt is not a bound. That is
				// what the `false` argument tests — the hard ceiling, no reserve.
				$this->assertSessionCeiling('synthesis', false);
				$finalText = $this->synthesiseUnderCeiling(
					$agent, $llm, $conversation, $sessionUuid, $actorId, $traceId, $totalIn, $totalOut,
				);
				return [
					'stop_reason' => $finalText === '' ? 'ceiling' : 'ceiling_synthesis',
					'tokens_input' => $totalIn,
					'tokens_output' => $totalOut,
					'final_text' => $finalText,
					'conversation' => $conversation,
					'ceiling_note' => $exc->getMessage(),
				];
			}
			// Withholding the schemas is what makes the synthesis turn binding.
			// Asking politely for a summary while still offering tools reliably
			// produces one more tool call — the instruction competes with the
			// affordance, and the affordance wins.
			$response = $this->callWithRetry(
				$agent,
				$llm,
				$conversation,
				$isSynthesis ? [] : $toolSchemas,
			);
			$totalIn += $response->tokensInput;
			$totalOut += $response->tokensOutput;
			$this->sessionTokensIn += $response->tokensInput;
			$this->sessionTokensOut += $response->tokensOutput;
			// What the NEXT call might cost, from what calls have cost. The
			// conversation only grows, so the largest so far is the honest
			// lower bound on the next one.
			$this->sessionLargestCall = max(
				$this->sessionLargestCall,
				$response->tokensInput + $response->tokensOutput,
			);

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
					'text_preview' => mb_strcut($response->textOutput(), 0, 240, 'UTF-8'),
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
				// A report written on the forced turn is still a report, but it
				// is NOT the same event as an agent that finished because it was
				// done, and a session table that spells both `end_turn` cannot
				// tell you which ceremonies had enough budget. Keep them apart:
				// a run of `call_cap_synthesis` rows is the signal to raise the
				// cap, and it is invisible if this collapses to `end_turn`.
				$stopReason = $isSynthesis ? 'call_cap_synthesis' : $response->stopReason;
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
					$toolSpan->setError(mb_strcut($toolResult->content, 0, 200, 'UTF-8'));
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
						'content_preview' => mb_strcut($toolResult->content, 0, 240, 'UTF-8'),
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
		// THE JUDGE IS CODE. The proposer is a model. Satisfaction is the exit
		// code of the agent's declared gate set, read by this loop — never a
		// model's opinion of the work it just produced.
		//
		// The fallback that used to sit here handed the Grader the PROPOSER'S
		// OWN CLIENT whenever `model.grader` was absent, which was always. A
		// model asked to judge its own output agrees with itself
		// (arXiv:2510.16657), so every `satisfied` written before 2026-08-29
		// was the agent's own signature. `Grader::forUri` returns null on the
		// absent path: no grader declared means no grader call.
		$grader = Grader::forUri(
			$agent->modelGraderUri,
			fn (string $uri) => $this->llmFactory->fromUri($uri),
		);
		$oracle = new GateOracle((string) getenv('NOS_REPO_ROOT'));
		$totalIn = 0;
		$totalOut = 0;
		$result = 'failed';
		$finalText = '';
		$stoppedAtPeak = false;
		$outcomeId = 'outcome_' . substr($sessionUuid, 0, 8);

		for ($iteration = 0; $iteration < $agent->maxIterations; $iteration++) {
			// Checked here too, so the clock bounds the GRADER — which holds
			// its own client and whose spend the token ceiling cannot see.
			//
			// STOP ITERATING, DO NOT DISCARD (2026-08-18). This check used to
			// throw, and the throw travelled past everything iteration 1 had
			// produced. Measured on the cheap ceiling test — `stop_reason:
			// ceiling` at `iteration`, 13 502 in / 1 708 out — with a completed
			// first iteration sitting in `$finalText`, thrown away because the
			// SECOND one could not be afforded. A budget that will not fund more
			// work is not a reason to bin the work already done.
			//
			// The hard ceiling, not the working one: this decides whether to
			// START an iteration, and the reserved headroom belongs to the
			// wrap-up inside `runToolUseLoop`, which has its own check.
			try {
				$this->assertSessionCeiling('iteration', false);
			} catch (SessionCeilingReached $exc) {
				if ($iteration === 0) {
					throw $exc;   // nothing produced yet; the ceiling IS the outcome
				}
				break;   // reported as max_iterations_reached, on the best iteration so far
			}
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
				'grader.gateset' => (string) $agent->gateset,
				'grader.rubric_path' => $agent->rubric?->sourcePath ?? '',
			]);

			// The verdict. Everything below only records or explains it.
			$verdict = $oracle->judge($iteration, (string) $agent->gateset, $finalText);
			$result = $verdict['satisfied'] ? 'satisfied' : 'needs_revision';
			$feedback = $verdict['detail'];

			// A declared grader writes the REVISION NOTES against the rubric.
			// It cannot make a failing gate set pass, and its absence costs
			// nothing but prose: the gate's own output is the feedback.
			if ($grader !== null && $agent->rubric !== null && !$verdict['satisfied']) {
				$grade = $grader->grade($agent->description, $agent->rubric, $transcript);
				$totalIn += $grade['tokens_input'];
				$totalOut += $grade['tokens_output'];
				$feedback .= "\n\nGRADER NOTES:\n" . $grade['feedback'];
				// A repair is recorded by whoever READ it, not by the code that
				// performed it — otherwise the failing thing marks its own
				// recovery and the session looks clean.
				if ($grade['repaired']) {
					$this->sessions->markOutputRepaired($sessionUuid);
				}
				$gradeSpan->setAttributes([
					'grader.tokens_input' => $grade['tokens_input'],
					'grader.tokens_output' => $grade['tokens_output'],
				]);
			}

			$gradeSpan->setAttributes([
				'grader.result' => $result,
				'grader.gate_run_id' => $verdict['gate_run_id'] ?? '',
				'grader.gate_score' => $verdict['score'],
			]);
			$gradeSpan->end();
			$spans[] = $gradeSpan;

			$durationMs = (int) (microtime(true) * 1000) - $iterStart;
			$this->sessions->recordIteration(
				$sessionUuid,
				$iteration,
				$result,
				$feedback,
				$llm->identifier(),
				$durationMs,
				$loopOut['tokens_input'],
				$loopOut['tokens_output'],
				$verdict['gate_run_id'],
			);
			$this->audit->emit(
				type: 'agent_grader_decision',
				actorActionId: $sessionUuid,
				actorId: $actorId,
				task: "agent:{$agent->name}/grader.{$iteration}",
				result: [
					'iteration' => $iteration,
					'grader_result' => $result,
					'gate_set' => $agent->gateset,
					'gate_run_id' => $verdict['gate_run_id'],
					'feedback_preview' => mb_strcut($feedback, 0, 240, 'UTF-8'),
				],
				traceId: $traceId,
			);
			$this->webhooks->fire('agent_outcome_iteration', [
				'session_id' => $sessionUuid,
				'outcome_id' => $outcomeId,
				'iteration' => $iteration,
				'result' => $result,
			]);

			if ($verdict['satisfied']) {
				return [
					'outcome_result' => 'satisfied',
					'iterations' => $iteration + 1,
					'tokens_input' => $totalIn,
					'tokens_output' => $totalOut,
					'final_text' => $finalText,
				];
			}
			// Score 0 on the FIRST attempt means the environment could not
			// judge at all (requirement absent, no sealed verdict) — revising
			// blind burns tokens on work nobody measured. Stop now; the
			// oracle's outcome() will say `indeterminate`, not failed work.
			if ($iteration === 0 && $verdict['score'] === 0) {
				break;
			}
			// One iteration past a peak that was not beaten, then stop: 78.26%
			// of self-continued searches end below their own peak
			// (arXiv:2607.25886), and the peak is what gets reported anyway.
			if (!$oracle->shouldContinue()) {
				$stoppedAtPeak = true;
				break;
			}
			// "Please revise" with nothing to revise made the surveyor
			// re-explore from zero three times and never write (2026-08-27).
			$conversation[] = Message::userText(
				"YOUR PREVIOUS ATTEMPT (iteration {$iteration}):\n\n" .
				($finalText !== '' ? $finalText
					: '(you produced no final text — you spent the iteration on tool calls '
					. 'and never wrote the deliverable; write it this time)') .
				"\n\nWHY IT IS NOT DONE:\n\n" .
				$feedback . "\n\nRevise the attempt above."
			);
		}

		// BEST, NOT LAST. The final attempt is the one the model stopped on,
		// which is the best one only by accident.
		$best = $oracle->best();
		return [
			// Three different endings, kept distinguishable: the budget ran
			// out, the search stopped one step past its own peak, or NO judge
			// ever reached a verdict — `indeterminate`, because a judge that
			// cannot run is not work that failed (GateOracle::outcome).
			'outcome_result' => $oracle->outcome($stoppedAtPeak),
			'iterations' => $best !== null ? $best['iteration'] + 1 : $agent->maxIterations,
			'tokens_input' => $totalIn,
			'tokens_output' => $totalOut,
			'final_text' => $best !== null ? $best['final_text'] : $finalText,
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
	 * One wrap-up call against a COMPACTED transcript, when the ceiling hit.
	 *
	 * WHY COMPACTED AND NOT JUST "ONE MORE CALL". The conversation that reaches
	 * a ceiling is mostly tool RESULTS — file bodies, directory listings, API
	 * payloads — resent in full on every turn. That is why the surveyor's run
	 * spent 260 745 input tokens to produce 2 558 of output. Replaying it costs
	 * as much again, so a reserve large enough to hold it would not be a reserve,
	 * it would be a second ceiling.
	 *
	 * What a report actually needs is what the model itself concluded, and that
	 * is the cheap half of the transcript. So the tool traffic goes and the
	 * assistant's own prose stays, in order, with the wrap-up instruction after
	 * it. The model is summarising its own notes rather than re-reading the
	 * estate.
	 *
	 * A FAILURE HERE IS NOT AN ERROR. If the compacted call also fails, the run
	 * still ends at the ceiling with no report — exactly where it was before this
	 * existed. Returning '' says so; it must not turn a bounded run into a
	 * crashed one, and it must never be retried, because the whole point is that
	 * the budget is gone.
	 *
	 * @param array<int, Message> $conversation
	 */
	private function synthesiseUnderCeiling(
		Agent $agent,
		LLMClientInterface $llm,
		array $conversation,
		string $sessionUuid,
		string $actorId,
		string $traceId,
		int &$totalIn,
		int &$totalOut,
	): string {
		try {
			$compacted = $this->compactForSynthesis($conversation);
			$compacted[] = Message::userText(self::SYNTHESIS_PROMPT);
			// No tools, for the same reason as the call-cap turn: an affordance
			// beats an instruction.
			$response = $llm->send($agent->systemPrompt ?? '', $compacted, [], $agent->maxOutputTokens);
			$totalIn += $response->tokensInput;
			$totalOut += $response->tokensOutput;
			$this->sessionTokensIn += $response->tokensInput;
			$this->sessionTokensOut += $response->tokensOutput;

			$this->audit->emit(
				type: 'agent_message',
				actorActionId: $sessionUuid,
				actorId: $actorId,
				task: "agent:{$agent->name}/llm.call.synthesis",
				result: [
					'stop_reason' => 'ceiling_synthesis',
					'text_preview' => mb_strcut($response->textOutput(), 0, 240, 'UTF-8'),
					'text' => $response->textOutput(),
					'compacted_from' => count($conversation),
					'compacted_to' => count($compacted),
					'cost_usd' => $response->costUsd,
				],
				traceId: $traceId,
			);
			return $response->textOutput();
		} catch (\Throwable $exc) {
			error_log('[AgentKit] ceiling synthesis failed: ' . $exc->getMessage());
			return '';
		}
	}

	/**
	 * Drop the tool traffic, keep what the model wrote.
	 *
	 * Tool RESULTS are dropped because they are the bulk and the model has
	 * already read them; tool USES are dropped with them, because a tool_use
	 * block whose result is gone is an unanswered call and several providers
	 * reject that shape outright. What survives is the opening prompt and every
	 * assistant text block — the run's own reasoning, in order.
	 *
	 * @param array<int, Message> $conversation
	 * @return array<int, Message>
	 */
	private function compactForSynthesis(array $conversation): array
	{
		$out = [];
		foreach ($conversation as $index => $message) {
			$text = '';
			foreach ($message->content as $block) {
				if (($block['type'] ?? null) === 'text') {
					$text .= (string) ($block['text'] ?? '');
				}
			}
			if (trim($text) === '') {
				continue;   // a turn that was nothing but tool traffic
			}
			// The first user message is the ceremony's brief and must survive
			// even if later user turns are only tool results.
			$out[] = $index === 0 || $message->role === 'user'
				? Message::userText($text)
				: Message::assistantText($text);
		}
		return $out;
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
	private function assertSessionCeiling(string $at, bool $reserveHeadroom = true): void
	{
		if ($this->sessionDeadline === null) {
			return; // no session open (direct unit-level use of the loop)
		}
		$tokenCeiling = self::envInt(
			'NOS_AGENT_SESSION_TOKEN_CEILING', self::SESSION_TOKEN_CEILING
		);
		// HEADROOM, so the run can still SAY something (2026-08-18). Measured on
		// the first bound surveyor run after the synthesis turn shipped: the
		// session died here at 260 745 in / 2 558 out after 23 calls. The call
		// cap is 30, so the reservation made that morning — one call held back
		// out of thirty — protected a bound that never binds for this agent. The
		// ceiling that actually fires is this one, and it fired mid-investigation
		// with nothing written, which is the same empty-handed run in a different
		// costume.
		//
		// So the working budget stops short of the ceiling and the difference is
		// spent on one compacted wrap-up call (see runToolUseLoop's catch). The
		// hard ceiling is unchanged and is still enforced — `$reserveHeadroom =
		// false` is how the wrap-up asks to be measured against it.
		if ($reserveHeadroom) {
			// THE RESERVE MUST COVER THE CALL THAT HAS NOT HAPPENED YET.
			//
			// Two wrong reserves shipped before this one, each disproved by a run:
			//   * a flat 20 000 — at the tightened test ceiling of 30 000 it ate
			//     two thirds of the budget;
			//   * 15% of the ceiling — the wrap-up was then REFUSED at
			//     `42 500 >= 40 000`, because the check happens BEFORE a call and
			//     the call it lets through costs whatever it costs. The budget was
			//     34 000, the loop was under it, one more call landed at 42 500,
			//     and the headroom had already been spent by the thing it was
			//     meant to leave room after.
			//
			// So the reserve is sized from what this session has actually cost:
			// the largest single call seen so far, plus room for the compacted
			// wrap-up itself. Both are measurements, and on call zero — where
			// there is nothing to measure — the floor stands in.
			$reserve = max(
				self::SYNTHESIS_MIN_RESERVE,
				$this->sessionLargestCall + self::SYNTHESIS_MIN_RESERVE,
			);
			$tokenCeiling = max(1, $tokenCeiling - $reserve);
		}
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
		// THE FALLBACK MUST NOT LEAVE THE DECLARED SERVING SET (2026-08-16).
		// It is built UNBOUND, and that was safe only by accident: every agent's
		// fallback happens to name `openclaw-*`, which Factory refuses to bind
		// anyway. The day one names a bindable provider, a MiniMax-bound agent
		// would fall back to the DEFAULT backend — answering from a party its own
		// Article-30 record does not name, under this session's attribution, with
		// nothing raised. Residency that a failure can silently revoke is a claim,
		// not a property; so a bound session refuses rather than degrades.
		if ($this->activeBinding !== null && $this->isBindableUri($agent->modelFallbackUri)) {
			throw new LLMPermanentError(
				"agent '{$agent->name}' is bound to backend "
				. "'{$this->activeBinding->name}' and declares a bindable fallback "
				. "('{$agent->modelFallbackUri}'), which would be served UNBOUND by "
				. 'the default backend. Declare a fallback the binding cannot reach, '
				. 'or none.'
			);
		}
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
					$toolResults[] = mb_strcut($content, 0, 400, 'UTF-8');
				}
			}
			$body = trim(implode("\n", array_filter([
				implode("\n", $texts),
				$toolUses === [] ? '' : 'TOOL_USE: ' . implode('; ', $toolUses),
				$toolResults === [] ? '' : 'TOOL_RESULT: ' . implode("\n---\n", $toolResults),
			])));
			$lines[] = "[{$i}] {$role}:\n{$body}";
		}
		// This IS the grader's request body — one bad byte kills the session
		// after the work is done (librarian, 2026-08-27, twice).
		$out = implode("\n\n", $lines);
		return mb_check_encoding($out, 'UTF-8')
			? $out
			: mb_convert_encoding($out, 'UTF-8', 'UTF-8')
				. "\n...[some bytes were not valid UTF-8 and were replaced]";
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

	/**
	 * `call_cap_synthesis` counts (2026-08-18): the run was cut short of the
	 * investigation it wanted, but it was given a final turn and it produced
	 * the report — which is the deliverable this method is asked about. Calling
	 * it a failure would make the exit code punish a full budget rather than a
	 * broken ceremony, and would leave the caller no way to tell it apart from
	 * a crash.
	 *
	 * That it was truncated is not lost: `stopReason` still says so, and a run
	 * of these rows in `agent_sessions` is the evidence for raising the cap.
	 * Successful is not the same as unconstrained.
	 */
	public function isSuccessful(): bool
	{
		return $this->error === null && in_array(
			$this->stopReason,
			['end_turn', 'outcome_satisfied', 'call_cap_synthesis'],
			true,
		);
	}
}
