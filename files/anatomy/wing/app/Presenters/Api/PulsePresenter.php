<?php

declare(strict_types=1);

namespace App\Presenters\Api;

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
		$this->sendSuccess($updated);
	}

	private function createRun(): void
	{
		$body = $this->getJsonBody();
		foreach (['run_id', 'job_id'] as $required) {
			if (empty($body[$required])) {
				$this->sendError("$required is required", 400);
			}
		}
		try {
			$runId = $this->pulse->recordStart($body);
		} catch (\Throwable $e) {
			$this->sendError('insert failed: ' . $e->getMessage(), 500);
		}
		$this->sendCreated(['accepted' => true, 'run_id' => $runId]);
	}
}
