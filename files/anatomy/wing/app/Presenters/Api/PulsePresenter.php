<?php

declare(strict_types=1);

namespace App\Presenters\Api;

use App\Model\NotificationRepository;
use App\Model\PulseRepository;

/**
 * GET  /api/v1/pulse_jobs/due            — list jobs whose next_fire_at <= now
 * POST /api/v1/pulse_jobs                — upsert a job (plugin loader post_compose hook)
 * GET  /api/v1/pulse_jobs                — list all registered jobs (admin/debug)
 * GET  /api/v1/pulse_jobs/<id>           — single job by plugin_name:job_name id
 * POST /api/v1/pulse_runs                — Pulse claims a fired job (start row)
 * POST /api/v1/pulse_runs/<id>/finish    — Pulse posts the run's exit_code + tails
 * GET  /api/v1/pulse_runs/<id>           — poll-after-trigger view of one run
 *
 * All endpoints require Bearer token auth. Pulse holds a service token
 * issued at boot (client_credentials via Authentik). The plugin loader
 * uses the operator's playbook-time token for POST /pulse_jobs.
 *
 * Anatomy P0.2 (2026-05-04) + A7 (2026-05-06).
 */
final class PulsePresenter extends BaseApiPresenter
{
	public function __construct(
		private PulseRepository $pulse,
		private NotificationRepository $notifications,
	) {
	}

	/**
	 * POST /api/v1/pulse_jobs           — upsert job (plugin loader hook)
	 *   body: {plugin_name, job_name, command, schedule, runner?, args?, env?,
	 *          jitter_min?, max_runtime_s?, max_concurrent?}
	 * GET  /api/v1/pulse_jobs           — list all registered jobs
	 * GET  /api/v1/pulse_jobs/<id>      — single job by id (plugin_name:job_name)
	 */
	public function actionJobs(?string $id = null): void
	{
		if ($id !== null) {
			$this->requireMethod('GET');
			$job = $this->pulse->getJob($id);
			if (!$job) {
				$this->sendError('Job not found', 404);
			}
			$this->sendSuccess($job);
			return;
		}

		if ($this->getMethod() === 'POST') {
			$body = $this->getJsonBody();
			foreach (['plugin_name', 'job_name', 'command', 'schedule'] as $req) {
				if (empty($body[$req])) {
					$this->sendError("$req is required");
				}
			}
			// SEC-8 (2026-05-23): command + args allowlist. Pre-this,
			// any holder of any active Wing API token could schedule
			// `command=/bin/sh, args=["-c","curl … | sh"]` and arbitrary
			// RCE fired on next Pulse tick. Defense:
			//   1. command must be an absolute path under a known
			//      executable prefix (Homebrew, /usr/local, the
			//      playbook plugin dir).
			//   2. basename must NOT be a shell interpreter — even when
			//      the path passes (e.g. /opt/homebrew/bin/bash).
			//   3. each arg must match a strict regex banning whitespace
			//      + every shell metacharacter.
			$this->validatePulseCommand((string) $body['command'], $body['args'] ?? []);
			$job = $this->pulse->upsertJob($body);
			$this->sendCreated(['accepted' => true, 'job' => $job]);
			return;
		}

		$this->requireMethod('GET');
		$this->sendSuccess([
			'generated_at' => gmdate('c'),
			'jobs'         => $this->pulse->listJobs(),
		]);
	}

	/**
	 * GET /api/v1/pulse_jobs/due
	 *
	 * Query params:
	 *   limit (int, default 50, max 200) — cap on returned jobs
	 */
	public function actionJobsDue(): void
	{
		$this->requireMethod('GET');
		$limit = max(1, min(200, (int) ($this->getParameter('limit') ?? 50)));
		$this->sendSuccess([
			'generated_at' => gmdate('c'),
			'jobs'         => $this->pulse->listDue($limit),
		]);
	}

	/**
	 * POST /api/v1/pulse_runs        — body: {run_id, job_id, fired_at?, actor_id?}
	 * GET  /api/v1/pulse_runs/<id>   — read one run row
	 */
	public function actionRuns(?string $id = null): void
	{
		if ($id === null) {
			$this->requireMethod('POST');
			$this->createRun();
			return;
		}
		$this->requireMethod('GET');
		$run = $this->pulse->getRun($id);
		if (!$run) {
			$this->sendError('Run not found', 404);
		}
		$this->sendSuccess($run);
	}

	/**
	 * POST /api/v1/pulse_runs/<id>/finish — body: {exit_code, finished_at?, duration_ms?, stdout_tail?, stderr_tail?}
	 *
	 * Updates pulse_runs row AND advances pulse_jobs.next_fire_at.
	 * Returns the updated run row.
	 */
	public function actionRunFinish(string $id): void
	{
		$this->requireMethod('POST');
		$body = $this->getJsonBody();
		if (!isset($body['exit_code'])) {
			$this->sendError('exit_code is required', 400);
		}
		$updated = $this->pulse->recordFinish($id, $body);
		if (!$updated) {
			$this->sendError('Run not found', 404);
		}
		$this->emitRunStateChangeNotification($id, $updated);
		$this->sendSuccess($updated);
	}

	/**
	 * W6.1 (2026-06-10): state-change inbox notification for pulse runs.
	 *
	 * This is THE single choke point that sees EVERY run result — including
	 * the daemon-exception synthetic rc=255 (a job whose script never even
	 * exec'd, e.g. the 2026-06-10 EACCES on scan-runner.sh, emits here too;
	 * a per-script emitter can be skipped by exactly the failures that
	 * matter most). Semantics:
	 *   success→failure  → HIGH  "job failing"   (first failure only)
	 *   failure→success  → INFO  "job recovered"
	 *   repeat failure   → silent (no inbox flood from per-minute jobs)
	 * Channels default to wing-inbox via NotificationRepository::insert —
	 * the PHP insert path does not read notification-routing.json (same
	 * contract as breach-scan.php). Failures here are swallowed: a broken
	 * notifications table must never 500 the run-recording API.
	 */
	private function emitRunStateChangeNotification(string $runId, array $run): void
	{
		try {
			$exit = (int) ($run['exit_code'] ?? 0);
			$jobId = (string) ($run['job_id'] ?? '');
			if ($jobId === '') {
				return;
			}
			$prev = $this->pulse->previousExitCode($jobId, $runId);
			$failedNow = $exit !== 0;
			$failedBefore = $prev !== null && $prev !== 0;
			if ($failedNow === $failedBefore) {
				return; // steady state (incl. first-ever success) — no emit
			}
			$originPlugin = explode(':', $jobId, 2)[0] ?: null;
			if ($failedNow) {
				$stderr = trim((string) ($run['stderr_tail'] ?? ''));
				$payload = [
					'severity' => 'high',
					'title'    => "Pulse job {$jobId} failing (rc={$exit})",
					'body'     => ($stderr !== '' ? "```\n" . mb_substr($stderr, 0, 1500) . "\n```\n" : '')
						. "run_id: {$runId}",
				];
			} else {
				$payload = [
					'severity' => 'info',
					'title'    => "Pulse job {$jobId} recovered (rc=0)",
					'body'     => "run_id: {$runId}",
				];
			}
			$payload['actor_id'] = $run['actor_id'] ?? 'pulse';
			$payload['actor_action_id'] = $run['actor_action_id'] ?? null;
			$payload['origin_plugin'] = $originPlugin;
			$this->notifications->insert($payload);
		} catch (\Throwable $e) {
			// Best-effort only — log via error_log, never break the API.
			error_log('pulse run-finish notification emit failed: ' . $e->getMessage());
		}
	}

	private function createRun(): void
	{
		$body = $this->getJsonBody();
		foreach (['run_id', 'job_id'] as $required) {
			if (empty($body[$required])) {
				$this->sendError("$required is required", 400);
			}
		}
		// X.1.b (2026-05-08): default actor_id from the validated Bearer
		// token's `name` field if the caller didn't provide one. Pulse
		// runs without an explicit actor (most subprocess-runner jobs)
		// inherit the daemon's identity; agent-runner jobs that already
		// pass actor_id explicitly (pulse-run-agent.sh sets it from
		// CLIENT_ID after Authentik auth) keep their value.
		if (empty($body['actor_id'])) {
			$autoActor = $this->getActorId();
			if ($autoActor !== null) {
				$body['actor_id'] = $autoActor;
			}
		}
		try {
			$runId = $this->pulse->recordStart($body);
		} catch (\Throwable $e) {
			$this->sendError('insert failed: ' . $e->getMessage(), 500);
		}
		$this->sendCreated(['accepted' => true, 'run_id' => $runId]);
	}

	/**
	 * Allowed path prefixes for Pulse `command`. The basename after the
	 * prefix is matched against ALLOWED_BASENAME_PATTERN; combined with
	 * the BANNED_BASENAMES list this lets `php`/`python3` through (they
	 * require a script arg the arg-regex itself validates) but rejects
	 * shell interpreters that take inline scripts via `-c`.
	 *
	 * Hardcoded — anatomy gate pins the list. Operators wiring a new
	 * subprocess runner add a path to the live plugin manifest, which
	 * lands under one of these prefixes by convention; if not, the
	 * playbook fails loud here rather than at runtime.
	 */
	private const ALLOWED_COMMAND_PREFIXES = [
		'/opt/homebrew/bin/',     // Homebrew-installed CLIs (gitleaks, trivy, php, …)
		'/usr/local/bin/',        // legacy/system-managed CLIs
		'/Users/',                // host-owned scripts on macOS (wing/app/bin, plugins/<x>/skills/)
		'/home/',                 // host-owned scripts on Linux (playbook_dir = /home/<user>/…)
	];

	/**
	 * Shell-interpreter basenames that take inline scripts via -c and
	 * thus get full RCE even when the path itself is in the allowlist.
	 * php is NOT here — it can only run a file given as a positional
	 * arg, and the arg-regex bans the shell-meta needed for `php -r`
	 * inline-eval (the `-r` flag + space-separated body fails the
	 * arg-regex).
	 */
	private const BANNED_BASENAMES = [
		'sh', 'bash', 'zsh', 'dash', 'csh', 'ksh', 'fish',
		'sudo', 'su', 'env',
	];

	/**
	 * Per-arg regex. Allows: alnum, dot, underscore, dash, slash, colon,
	 * equals, comma, plus, tilde, at-sign. Bans: whitespace (any flavor),
	 * quotes (single, double, backtick), shell-control (& | ; > <),
	 * parens, brackets, braces, backslash, dollar-sign, newline.
	 *
	 * Effectively this lets file paths, simple flags (`--key=value`),
	 * URLs, env-var literals through. Rejects any payload-as-arg shape
	 * that needs `-c '...'` semantics.
	 */
	private const ARG_REGEX = '/^[a-zA-Z0-9._@\/:=,+~-]{0,512}$/';

	private function validatePulseCommand(string $command, mixed $args): void
	{
		if ($command === '') {
			$this->sendError('command is required');
		}
		if ($command[0] !== '/') {
			$this->sendError('command must be an absolute path', 400);
		}
		$inPrefix = false;
		foreach (self::ALLOWED_COMMAND_PREFIXES as $prefix) {
			if (str_starts_with($command, $prefix)) {
				$inPrefix = true;
				break;
			}
		}
		if (!$inPrefix) {
			$this->sendError(
				'command path not in Pulse allowlist (see PulsePresenter::ALLOWED_COMMAND_PREFIXES)',
				400,
			);
		}
		$basename = basename($command);
		if (in_array($basename, self::BANNED_BASENAMES, true)) {
			$this->sendError(
				"command basename '{$basename}' is banned (shell interpreter — accepts -c inline scripts)",
				400,
			);
		}
		// Strict shape check on basename — catches null bytes, NUL,
		// embedded path traversal residue.
		if (!preg_match('/^[a-z][a-zA-Z0-9._-]{0,63}$/', $basename)) {
			$this->sendError('command basename malformed', 400);
		}

		if ($args !== null && $args !== []) {
			if (!is_array($args)) {
				$this->sendError('args must be a JSON array', 400);
			}
			foreach ($args as $i => $arg) {
				if (!is_string($arg)) {
					$this->sendError("args[{$i}] must be a string", 400);
				}
				if (!preg_match(self::ARG_REGEX, $arg)) {
					$this->sendError(
						"args[{$i}] contains banned characters (whitespace / shell metacharacters)",
						400,
					);
				}
			}
		}
	}
}
