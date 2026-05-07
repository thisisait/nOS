<?php

declare(strict_types=1);

namespace App\AgentKit;

/**
 * Sliding-window concurrent process driver — the engine behind Coordinator's
 * parallel sub-agent dispatch (Multi-agent A14 follow-up, 2026-05-07).
 *
 * Why a dedicated class:
 *   1. The proc_open + non-blocking poll dance is fiddly; centralising it in
 *      one tested unit lets Coordinator stay focused on lineage / audit.
 *   2. Anatomy gates can grep this file directly to assert the array-form
 *      proc_open invariant (carries A14.1 doctrine forward).
 *   3. Future use cases (Pulse fan-out, Dreams batch consolidation) can reuse
 *      the same driver without touching agent code.
 *
 * Doctrine, locked by tests/anatomy/test_agentkit_multiagent_pool.py:
 *   - proc_open ALWAYS receives the argv array form, never a string. String
 *     form delegates to /bin/sh -c on POSIX and reopens the A14.1 RCE class.
 *   - Pipes are non-blocking (stream_set_blocking $pipe false) and drained on
 *     every poll iteration so a chatty child can't fill its 64KB stdout pipe
 *     and deadlock.
 *   - Sliding window: at any moment len(running) <= maxConcurrent. A finished
 *     job's slot is taken by the next pending job in the same poll iteration.
 *   - Hard cap: maxConcurrent is silently clamped to [1, 16]. The 16 cap
 *     mirrors the A14 multi-agent doctrine — beyond that you want a real
 *     queue (Pulse), not in-process parallelism.
 *   - Timeout: when wallclock - poolStarted exceeds timeoutSeconds, every
 *     still-running job is SIGTERM'd via posix_kill. SIGKILL is reserved for
 *     a subsequent grace-period sweep (default 5s) so children get a chance
 *     to flush their final agent_session_end audit row.
 *   - Sibling failure non-fatal: a non-zero exit code marks that single job
 *     as 'error' but the pool keeps draining the rest.
 *
 * NO new composer deps — pure stdlib (proc_open, proc_get_status,
 * stream_select, posix_kill).
 */
final class ProcessPool
{
	/** Hard cap on concurrent processes. Beyond this you want a queue runner. */
	public const MAX_CONCURRENCY_CAP = 16;

	/** Default cap when caller passes 0 / negative. */
	public const DEFAULT_CONCURRENCY = 4;

	/** SIGTERM grace period before a SIGKILL sweep, in seconds. */
	private const TERM_GRACE_SECONDS = 5;

	/** Poll iteration delay (microseconds). */
	private const POLL_USLEEP = 50_000;

	private readonly int $maxConcurrent;
	private readonly int $timeoutSeconds;

	public function __construct(int $maxConcurrent = self::DEFAULT_CONCURRENCY, int $timeoutSeconds = 600)
	{
		// Clamp into [1, MAX_CONCURRENCY_CAP] — never trust caller input here,
		// agent.yml's max_concurrent_threads can have been authored years ago
		// when the cap was different.
		if ($maxConcurrent < 1) {
			$maxConcurrent = self::DEFAULT_CONCURRENCY;
		}
		if ($maxConcurrent > self::MAX_CONCURRENCY_CAP) {
			$maxConcurrent = self::MAX_CONCURRENCY_CAP;
		}
		if ($timeoutSeconds < 1) {
			$timeoutSeconds = 600;
		}
		$this->maxConcurrent = $maxConcurrent;
		$this->timeoutSeconds = $timeoutSeconds;
	}

	public function maxConcurrent(): int
	{
		return $this->maxConcurrent;
	}

	public function timeoutSeconds(): int
	{
		return $this->timeoutSeconds;
	}

	/**
	 * Run a batch of jobs with the configured concurrency cap.
	 *
	 * Each job is a value object with:
	 *   id        — caller-chosen identifier echoed back in the result
	 *   argv      — argv array passed verbatim to proc_open (NEVER a string)
	 *   env       — explicit env array; if null we pass [] (NO inherited env,
	 *               same defense-in-depth as BashReadOnlyTool::minimalEnv)
	 *   cwd       — working directory or null
	 *
	 * Callbacks (optional, useful for live audit-event emission):
	 *   onStart(job)  fired when the child is spawned (we have a PID now).
	 *   onEnd(job, result)  fired when the child exits (success, error, or
	 *                       timeout). Result has stdout/stderr/exit_code/
	 *                       status/duration_ms.
	 *
	 * @param array<int, ProcessPoolJob> $jobs
	 * @param ?callable(ProcessPoolJob): void $onStart
	 * @param ?callable(ProcessPoolJob, ProcessPoolResult): void $onEnd
	 * @return array<int, ProcessPoolResult> indexed by job id
	 */
	public function dispatch(
		array $jobs,
		?callable $onStart = null,
		?callable $onEnd = null,
	): array {
		$results = [];
		$pending = $jobs;
		/** @var array<string, array{job: ProcessPoolJob, proc: resource, pipes: array<int, resource>, started: float, stdout: string, stderr: string}> */
		$running = [];

		$poolStarted = microtime(true);
		$timedOut = false;

		while ($pending !== [] || $running !== []) {
			// 1) Fill the window from pending — sliding-window dispatch.
			while ($pending !== [] && count($running) < $this->maxConcurrent && !$timedOut) {
				$job = array_shift($pending);
				$spawn = $this->spawn($job);
				if ($spawn === null) {
					// Spawn failure is sibling-non-fatal — mark this one as error
					// and continue to the next.
					$result = new ProcessPoolResult(
						jobId: $job->id,
						status: 'error',
						exitCode: -1,
						stdout: '',
						stderr: 'failed to spawn process',
						durationMs: 0,
					);
					$results[$job->id] = $result;
					if ($onEnd !== null) {
						$onEnd($job, $result);
					}
					continue;
				}
				$running[$job->id] = [
					'job' => $job,
					'proc' => $spawn['proc'],
					'pipes' => $spawn['pipes'],
					'started' => microtime(true),
					'stdout' => '',
					'stderr' => '',
				];
				if ($onStart !== null) {
					$onStart($job);
				}
			}

			if ($running === []) {
				break;
			}

			// 2) Drain pipes + check exit status on every running child.
			foreach ($running as $jobId => $slot) {
				$slot['stdout'] .= (string) stream_get_contents($slot['pipes'][1]);
				$slot['stderr'] .= (string) stream_get_contents($slot['pipes'][2]);
				$running[$jobId]['stdout'] = $slot['stdout'];
				$running[$jobId]['stderr'] = $slot['stderr'];

				$status = proc_get_status($slot['proc']);
				if (!$status['running']) {
					// Final drain — the child is gone but the pipes may still have buffered output.
					$running[$jobId]['stdout'] .= (string) stream_get_contents($slot['pipes'][1]);
					$running[$jobId]['stderr'] .= (string) stream_get_contents($slot['pipes'][2]);
					@fclose($slot['pipes'][1]);
					@fclose($slot['pipes'][2]);
					$exit = proc_close($slot['proc']);
					if ($exit === -1 && isset($status['exitcode'])) {
						$exit = (int) $status['exitcode'];
					}
					$durationMs = (int) ((microtime(true) - $slot['started']) * 1000);
					$result = new ProcessPoolResult(
						jobId: $jobId,
						status: $exit === 0 ? 'idle' : 'error',
						exitCode: $exit,
						stdout: $running[$jobId]['stdout'],
						stderr: $running[$jobId]['stderr'],
						durationMs: $durationMs,
					);
					$results[$jobId] = $result;
					unset($running[$jobId]);
					if ($onEnd !== null) {
						$onEnd($slot['job'], $result);
					}
				}
			}

			// 3) Timeout check — once tripped, sweep ALL still-running children.
			if (!$timedOut && microtime(true) - $poolStarted > $this->timeoutSeconds) {
				$timedOut = true;
				foreach ($running as $jobId => $slot) {
					$status = proc_get_status($slot['proc']);
					if ($status['running'] && $status['pid'] > 0) {
						// SIGTERM 15 — children's shutdown handlers fire and
						// flush their final agent_session_end audit row.
						@posix_kill($status['pid'], 15);
					}
				}
				// Grace-period: poll for natural exit a few more iterations,
				// then SIGKILL anything still alive.
				$graceUntil = microtime(true) + self::TERM_GRACE_SECONDS;
				while ($running !== [] && microtime(true) < $graceUntil) {
					foreach ($running as $jobId => $slot) {
						$slot['stdout'] .= (string) stream_get_contents($slot['pipes'][1]);
						$slot['stderr'] .= (string) stream_get_contents($slot['pipes'][2]);
						$running[$jobId]['stdout'] = $slot['stdout'];
						$running[$jobId]['stderr'] = $slot['stderr'];
						$status = proc_get_status($slot['proc']);
						if (!$status['running']) {
							$running[$jobId]['stdout'] .= (string) stream_get_contents($slot['pipes'][1]);
							$running[$jobId]['stderr'] .= (string) stream_get_contents($slot['pipes'][2]);
							@fclose($slot['pipes'][1]);
							@fclose($slot['pipes'][2]);
							$exit = proc_close($slot['proc']);
							if ($exit === -1 && isset($status['exitcode'])) {
								$exit = (int) $status['exitcode'];
							}
							$durationMs = (int) ((microtime(true) - $slot['started']) * 1000);
							$result = new ProcessPoolResult(
								jobId: $jobId,
								status: 'terminated',
								exitCode: $exit,
								stdout: $running[$jobId]['stdout'],
								stderr: $running[$jobId]['stderr'],
								durationMs: $durationMs,
							);
							$results[$jobId] = $result;
							unset($running[$jobId]);
							if ($onEnd !== null) {
								$onEnd($slot['job'], $result);
							}
						}
					}
					usleep(self::POLL_USLEEP);
				}
				// SIGKILL sweep for stragglers.
				foreach ($running as $jobId => $slot) {
					$status = proc_get_status($slot['proc']);
					if ($status['running'] && $status['pid'] > 0) {
						@posix_kill($status['pid'], 9);
					}
					@fclose($slot['pipes'][1]);
					@fclose($slot['pipes'][2]);
					$exit = proc_close($slot['proc']);
					$durationMs = (int) ((microtime(true) - $slot['started']) * 1000);
					$result = new ProcessPoolResult(
						jobId: $jobId,
						status: 'terminated',
						exitCode: $exit,
						stdout: $slot['stdout'],
						stderr: $slot['stderr'],
						durationMs: $durationMs,
					);
					$results[$jobId] = $result;
					if ($onEnd !== null) {
						$onEnd($slot['job'], $result);
					}
				}
				$running = [];
				// Mark every still-pending job as terminated too — coordinator
				// timeout drains the entire batch.
				foreach ($pending as $job) {
					$result = new ProcessPoolResult(
						jobId: $job->id,
						status: 'terminated',
						exitCode: -1,
						stdout: '',
						stderr: 'coordinator timeout reached before dispatch',
						durationMs: 0,
					);
					$results[$job->id] = $result;
					if ($onEnd !== null) {
						$onEnd($job, $result);
					}
				}
				$pending = [];
				break;
			}

			if ($running !== []) {
				usleep(self::POLL_USLEEP);
			}
		}

		return $results;
	}

	/**
	 * Spawn one child via array-form proc_open. Returns null on failure.
	 *
	 * @return ?array{proc: resource, pipes: array<int, resource>}
	 */
	private function spawn(ProcessPoolJob $job): ?array
	{
		$descriptors = [
			0 => ['pipe', 'r'],
			1 => ['pipe', 'w'],
			2 => ['pipe', 'w'],
		];
		// ARRAY-form proc_open — NEVER a string. String form delegates to
		// /bin/sh -c on POSIX, which is the original A14.1 RCE class. The
		// anatomy gate test_processpool_uses_array_form_proc_open enforces
		// this invariant.
		$pipes = [];
		$proc = proc_open($job->argv, $descriptors, $pipes, $job->cwd, $job->env);
		if (!is_resource($proc)) {
			return null;
		}
		// Close stdin immediately — children read no input from us.
		@fclose($pipes[0]);
		// Non-blocking pipes prevent a chatty child from deadlocking when its
		// 64KB stdout buffer fills.
		stream_set_blocking($pipes[1], false);
		stream_set_blocking($pipes[2], false);
		return ['proc' => $proc, 'pipes' => $pipes];
	}
}

/**
 * One queued process to be dispatched by ProcessPool. Immutable value object.
 */
final class ProcessPoolJob
{
	/**
	 * @param array<int, string> $argv  argv array passed VERBATIM to proc_open.
	 *                                  argv[0] is the executable; never a shell.
	 * @param ?array<string, string> $env  explicit environment for the child;
	 *                                     null means an empty env (drop
	 *                                     everything from the parent's env —
	 *                                     same default as BashReadOnlyTool).
	 * @param ?string $cwd                 working directory or null.
	 * @param array<string, mixed> $context  caller-chosen metadata, echoed back
	 *                                       to onStart/onEnd callbacks. Useful
	 *                                       for binding child_thread_uuid +
	 *                                       agent_name to the audit emission.
	 */
	public function __construct(
		public readonly string $id,
		public readonly array $argv,
		public readonly ?array $env = null,
		public readonly ?string $cwd = null,
		public readonly array $context = [],
	) {
	}
}

/**
 * Outcome of one ProcessPool job. Immutable.
 *
 * Status surface:
 *   - idle:       child exited 0 (mirrors agent_sessions.status semantics)
 *   - error:      child exited non-zero or spawn failed
 *   - terminated: SIGTERM/SIGKILL'd because of coordinator timeout
 */
final class ProcessPoolResult
{
	public function __construct(
		public readonly string $jobId,
		public readonly string $status,
		public readonly int $exitCode,
		public readonly string $stdout,
		public readonly string $stderr,
		public readonly int $durationMs,
	) {
	}
}
