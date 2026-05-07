<?php

declare(strict_types=1);

namespace App\AgentKit;

use App\AgentKit\Telemetry\AuditEmitter;
use App\AgentKit\Telemetry\TraceContext;
use App\Model\AgentSessionRepository;

/**
 * Multi-agent coordinator.
 *
 * Two callers, two surfaces:
 *
 *  1. `run()` - historical surface kept intact for Runner.php's expectations.
 *     A coordinator agent's LLM picks a child via the synthetic `delegate-to`
 *     tool; the LLM-driven path stays in-process.
 *
 *  2. `runWithChildren()` - explicit caller-supplied batch dispatch. The CLI
 *     / Pulse / API caller hands in a list of {agent, prompt, vault, actor}
 *     specs; the coordinator pre-creates one agent_threads row per spec
 *     (status=pending, parent_thread_uuid=primary), spawns each as its own
 *     `bin/run-agent.php` subprocess via ProcessPool with the configured
 *     concurrency cap, drains results, and writes the child->parent lineage
 *     into agent_threads + the events table.
 *
 * Why subprocesses, not threads:
 *   - PHP threading (pthreads, parallel) is not in standard FrankenPHP.
 *   - Each child is a full Runner::run() lifecycle with its own LLM client,
 *     credential resolver, and OTel exporter. Crash isolation by OS.
 *
 * Audit lineage (locked by tests):
 *   - The coordinator's primary thread is the parent_thread_uuid for every
 *     child thread row. SELECT * FROM agent_threads WHERE
 *     parent_thread_uuid=? reconstructs the dispatch tree.
 *   - The coordinator emits agent_thread_start / agent_thread_end events
 *     into its OWN trace, with actor_action_id = coordinator_session_uuid
 *     and result_json carrying the child's session_uuid.
 *   - Every child thread's stop_reason embeds the child's session_uuid so
 *     /agents UI can render the deep tree without an extra column.
 *
 * Concurrency cap:
 *   - agent.yml::multiagent.max_concurrent_threads (default 4, max 16).
 *   - ProcessPool clamps silently.
 *
 * Timeout:
 *   - agent.yml::metadata.coordinator_timeout (seconds, default 600).
 *   - On timeout, ProcessPool SIGTERMs all running children with a 5s
 *     grace period, then SIGKILL.
 *   - Sibling failure is non-fatal.
 *
 * NEVER edits Runner.php. NEVER touches MemoryStore / dream-agent.php
 * (sibling worker territory).
 */
final class Coordinator
{
	/** Default coordinator timeout in seconds. agent.yml metadata override wins. */
	public const DEFAULT_COORDINATOR_TIMEOUT_SECONDS = 600;

	public function __construct(
		private readonly Runner $runner,
		private readonly AgentLoader $loader,
		private readonly AgentSessionRepository $sessions,
		private readonly AuditEmitter $audit,
	) {
	}

	/**
	 * Convenience entry: same surface as Runner::run().
	 */
	public function run(
		string $coordinatorAgent,
		?string $userPrompt = null,
		?string $vaultName = null,
		string $trigger = 'operator',
		?string $triggerId = null,
		?string $actorId = null,
	): RunResult {
		return $this->runner->run(
			$coordinatorAgent,
			$userPrompt,
			$vaultName,
			$trigger,
			$triggerId,
			$actorId,
		);
	}

	/**
	 * Run a coordinator agent and dispatch a fixed batch of children in
	 * parallel via ProcessPool.
	 *
	 * @param array<int, ChildSpec> $children
	 */
	public function runWithChildren(
		string $coordinatorAgent,
		array $children,
		?string $userPrompt = null,
		?string $vaultName = null,
		string $trigger = 'operator',
		?string $triggerId = null,
		?string $actorId = null,
	): ChildrenRunResult {
		$agent = $this->loader->load($coordinatorAgent);
		if (!$agent->isCoordinator()) {
			throw new \InvalidArgumentException(
				"Agent '{$coordinatorAgent}' is multiagent.type='{$agent->multiagentType}', not 'coordinator'."
			);
		}

		$coordResult = $this->runner->run(
			$coordinatorAgent,
			$userPrompt,
			$vaultName,
			$trigger,
			$triggerId,
			$actorId,
		);

		if ($children === []) {
			return new ChildrenRunResult($coordResult, []);
		}

		$primaryThreadUuid = $this->primaryThreadFor($coordResult->sessionUuid);
		if ($primaryThreadUuid === null) {
			error_log('[coordinator] primary thread not found for session ' . $coordResult->sessionUuid);
			return new ChildrenRunResult($coordResult, []);
		}

		$jobs = [];
		$childMeta = [];
		$wingRoot = realpath(__DIR__ . '/../..') ?: dirname(__DIR__, 2);
		$runAgentScript = $wingRoot . '/bin/run-agent.php';

		$resolvedActor = $actorId ?? ('agent:' . $coordinatorAgent);

		foreach ($children as $i => $spec) {
			$childThreadUuid = self::uuid();
			$childSpanId = TraceContext::newSpanId();
			$this->sessions->startChildThread([
				'uuid' => $childThreadUuid,
				'session_uuid' => $coordResult->sessionUuid,
				'parent_thread_uuid' => $primaryThreadUuid,
				'agent_name' => $spec->agentName,
				'agent_version' => 1,
				'role' => 'child',
				'trace_id' => $coordResult->traceId,
				'span_id' => $childSpanId,
			]);

			$argv = $this->buildChildArgv($runAgentScript, $spec, $childThreadUuid, $coordResult, $primaryThreadUuid);
			$env = $this->minimalEnv();
			$jobId = 'child-' . $i . '-' . substr($childThreadUuid, 0, 8);

			$jobs[] = new ProcessPoolJob(
				id: $jobId,
				argv: $argv,
				env: $env,
				cwd: $wingRoot,
				context: ['child_thread_uuid' => $childThreadUuid, 'spec' => $spec],
			);
			$childMeta[$jobId] = ['thread_uuid' => $childThreadUuid, 'spec' => $spec];
		}

		$maxConcurrent = $agent->maxConcurrentThreads;
		$metadataCap = $agent->metadata['max_concurrent_threads'] ?? null;
		if (is_int($metadataCap) && $metadataCap > 0) {
			$maxConcurrent = $metadataCap;
		}
		$timeoutSeconds = self::DEFAULT_COORDINATOR_TIMEOUT_SECONDS;
		$metadataTimeout = $agent->metadata['coordinator_timeout'] ?? null;
		if (is_int($metadataTimeout) && $metadataTimeout > 0) {
			$timeoutSeconds = $metadataTimeout;
		}

		$pool = new ProcessPool($maxConcurrent, $timeoutSeconds);

		$onStart = function (ProcessPoolJob $job) use ($childMeta, $coordResult, $resolvedActor): void {
			$meta = $childMeta[$job->id] ?? null;
			if ($meta === null) {
				return;
			}
			$this->sessions->markChildThreadRunning($meta['thread_uuid']);
			$this->audit->emit(
				type: 'agent_thread_start',
				actorActionId: $coordResult->sessionUuid,
				actorId: $resolvedActor,
				task: 'agent:' . $meta['spec']->agentName . '/spawn',
				result: [
					'child_thread_uuid' => $meta['thread_uuid'],
					'child_agent' => $meta['spec']->agentName,
					'job_id' => $job->id,
				],
				traceId: $coordResult->traceId,
			);
		};
		$onEnd = function (ProcessPoolJob $job, ProcessPoolResult $result) use ($childMeta, $coordResult, $resolvedActor): void {
			$meta = $childMeta[$job->id] ?? null;
			if ($meta === null) {
				return;
			}
			$childSummary = $this->parseChildSummary($result->stdout);
			$childSessionUuid = $childSummary['session_uuid'] ?? null;
			$tokensIn = $childSummary['tokens']['input'] ?? null;
			$tokensOut = $childSummary['tokens']['output'] ?? null;
			$errorMessage = $result->status === 'idle'
				? null
				: (trim($result->stderr) ?: ($childSummary['error'] ?? 'child exited ' . $result->exitCode));
			$this->sessions->endChildThread(
				$meta['thread_uuid'],
				$result->status,
				is_string($childSessionUuid) ? $childSessionUuid : null,
				is_int($tokensIn) ? $tokensIn : null,
				is_int($tokensOut) ? $tokensOut : null,
				$result->status === 'idle' ? null : $errorMessage,
			);
			$this->audit->emit(
				type: 'agent_thread_end',
				actorActionId: $coordResult->sessionUuid,
				actorId: $resolvedActor,
				task: 'agent:' . $meta['spec']->agentName . '/spawn',
				result: [
					'child_thread_uuid' => $meta['thread_uuid'],
					'child_agent' => $meta['spec']->agentName,
					'child_session_uuid' => $childSessionUuid,
					'status' => $result->status,
					'exit_code' => $result->exitCode,
					'duration_ms' => $result->durationMs,
				],
				traceId: $coordResult->traceId,
			);
		};

		$results = $pool->dispatch($jobs, $onStart, $onEnd);

		$outcomes = [];
		foreach ($jobs as $job) {
			$meta = $childMeta[$job->id];
			$result = $results[$job->id] ?? null;
			$childSummary = $result !== null ? $this->parseChildSummary($result->stdout) : [];
			$outcomes[] = new ChildOutcome(
				agentName: $meta['spec']->agentName,
				threadUuid: $meta['thread_uuid'],
				status: $result?->status ?? 'error',
				exitCode: $result?->exitCode ?? -1,
				durationMs: $result?->durationMs ?? 0,
				childSessionUuid: is_string($childSummary['session_uuid'] ?? null)
					? $childSummary['session_uuid']
					: null,
				tokensInput: is_int($childSummary['tokens']['input'] ?? null)
					? $childSummary['tokens']['input']
					: null,
				tokensOutput: is_int($childSummary['tokens']['output'] ?? null)
					? $childSummary['tokens']['output']
					: null,
				stopReason: is_string($childSummary['stop_reason'] ?? null)
					? $childSummary['stop_reason']
					: null,
				error: $result !== null && $result->status !== 'idle'
					? (trim($result->stderr) ?: ($childSummary['error'] ?? null))
					: null,
			);
		}

		return new ChildrenRunResult($coordResult, $outcomes);
	}

	private function primaryThreadFor(string $sessionUuid): ?string
	{
		foreach ($this->sessions->listThreadsForSession($sessionUuid) as $row) {
			if (($row['role'] ?? null) === 'primary') {
				return (string) $row['uuid'];
			}
		}
		return null;
	}

	/**
	 * Build the argv for spawning bin/run-agent.php as a child. ARRAY form
	 * only - values pass verbatim to proc_open which exec()s the binary
	 * directly (no /bin/sh -c).
	 *
	 * @return array<int, string>
	 */
	private function buildChildArgv(
		string $script,
		ChildSpec $spec,
		string $threadUuid,
		RunResult $coordResult,
		string $primaryThreadUuid,
	): array {
		$phpBinary = (defined('PHP_BINARY') && PHP_BINARY !== '') ? PHP_BINARY : 'php';
		$argv = [$phpBinary, $script, '--agent=' . $spec->agentName];
		if ($spec->prompt !== null) {
			$argv[] = '--prompt=' . $spec->prompt;
		}
		if ($spec->vaultName !== null) {
			$argv[] = '--vault=' . $spec->vaultName;
		}
		$argv[] = '--trigger=coordinator';
		$argv[] = '--trigger-id=' . $coordResult->sessionUuid;
		$argv[] = '--parent-thread-uuid=' . $primaryThreadUuid;
		$argv[] = '--thread-uuid=' . $threadUuid;
		if ($spec->actorId !== null) {
			$argv[] = '--actor=' . $spec->actorId;
		}
		return $argv;
	}

	/**
	 * Whitelisted env vars passed to child processes.
	 *
	 * @return array<string, string>
	 */
	private function minimalEnv(): array
	{
		$allowed = [
			'PATH', 'HOME', 'LANG', 'LC_ALL', 'LC_CTYPE', 'TZ', 'PWD', 'TMPDIR',
			'ANTHROPIC_API_KEY',
			'ANTHROPIC_BASE_URL',
			'OPENCLAW_BASE_URL',
			'OPENAI_API_KEY',
			'WING_BASE_URL',
			'WING_API_TOKEN',
			'BONE_BASE_URL',
			'BONE_SECRET',
			'OTEL_EXPORTER_OTLP_ENDPOINT',
		];
		$env = [];
		foreach ($allowed as $name) {
			$value = getenv($name);
			if (is_string($value) && $value !== '') {
				$env[$name] = $value;
			}
		}
		if (!isset($env['PATH'])) {
			$env['PATH'] = '/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin';
		}
		return $env;
	}

	/**
	 * Parse the JSON summary that bin/run-agent.php prints on stdout.
	 *
	 * @return array<string, mixed>
	 */
	private function parseChildSummary(string $stdout): array
	{
		$stdout = trim($stdout);
		if ($stdout === '') {
			return [];
		}
		$lastBrace = strrpos($stdout, '{');
		if ($lastBrace === false) {
			return [];
		}
		$candidate = substr($stdout, $lastBrace);
		$decoded = json_decode($candidate, true);
		if (!is_array($decoded)) {
			return [];
		}
		return $decoded;
	}

	private static function uuid(): string
	{
		$d = random_bytes(16);
		$d[6] = chr((ord($d[6]) & 0x0f) | 0x40);
		$d[8] = chr((ord($d[8]) & 0x3f) | 0x80);
		return vsprintf('%s%s-%s-%s-%s-%s%s%s', str_split(bin2hex($d), 4));
	}
}

/**
 * One child specification handed to Coordinator::runWithChildren().
 */
final class ChildSpec
{
	public function __construct(
		public readonly string $agentName,
		public readonly ?string $prompt = null,
		public readonly ?string $vaultName = null,
		public readonly ?string $actorId = null,
	) {
	}
}

/**
 * One child's outcome.
 */
final class ChildOutcome
{
	public function __construct(
		public readonly string $agentName,
		public readonly string $threadUuid,
		public readonly string $status,
		public readonly int $exitCode,
		public readonly int $durationMs,
		public readonly ?string $childSessionUuid,
		public readonly ?int $tokensInput,
		public readonly ?int $tokensOutput,
		public readonly ?string $stopReason,
		public readonly ?string $error,
	) {
	}
}

/**
 * Combined return value of Coordinator::runWithChildren().
 */
final class ChildrenRunResult
{
	/**
	 * @param array<int, ChildOutcome> $children
	 */
	public function __construct(
		public readonly RunResult $coordinator,
		public readonly array $children,
	) {
	}

	public function allChildrenSucceeded(): bool
	{
		foreach ($this->children as $c) {
			if ($c->status !== 'idle') {
				return false;
			}
		}
		return true;
	}
}
