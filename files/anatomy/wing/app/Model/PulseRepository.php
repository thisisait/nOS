<?php

declare(strict_types=1);

namespace App\Model;

use Cron\CronExpression;
use Nette\Database\Explorer;

/**
 * Pulse job catalog + run history. Anatomy P0.2 (2026-05-04).
 *
 * Tables ``pulse_jobs`` + ``pulse_runs`` are defined in
 * ``files/anatomy/wing/db/schema-extensions.sql:176-219``. The Pulse
 * daemon (``files/anatomy/pulse/``) polls Wing for due jobs, fires
 * them, and posts run_start + run_finish. Server-side ``next_fire_at``
 * recomputation uses dragonmantank/cron-expression (added 2026-05-07
 * in the systematic Variant-A finalize sweep) — falls back to a flat
 * advance only when the schedule string can't be parsed.
 */
final class PulseRepository
{
	/**
	 * Used only when CronExpression rejects the schedule string —
	 * keeps the job from being stuck "due" every poll, which would
	 * spam the runner. Real cron parsing is the primary path.
	 */
	private const FALLBACK_ADVANCE_SECONDS = 3600;

	public function __construct(
		private Explorer $db,
	) {
	}

	/**
	 * Returns jobs that are due to fire. "Due" means:
	 *   - paused = 0
	 *   - removed_at IS NULL (soft-delete filter)
	 *   - next_fire_at IS NULL  OR  next_fire_at <= datetime('now')
	 *
	 * Pulse fires every job in the result, then posts run_start to claim
	 * the slot. Multi-instance Pulse coordination is not solved here —
	 * single host launchd in PoC.
	 *
	 * @return list<array<string, mixed>>
	 */
	public function listDue(int $limit = 50): array
	{
		$rows = [];
		foreach (
			$this->db->table('pulse_jobs')
				->where('paused', 0)
				->where('removed_at', null)
				->where('next_fire_at IS NULL OR next_fire_at <= ?', date('c'))
				->order('next_fire_at')
				->limit($limit)
				->fetchAll() as $row
		) {
			$rows[] = [
				'id'             => $row->id,
				'plugin_name'    => $row->plugin_name,
				'job_name'       => $row->job_name,
				'runner'         => $row->runner,
				'command'        => $row->command,
				'args'           => json_decode($row->args_json, true) ?: [],
				'env'            => json_decode($row->env_json, true) ?: [],
				'schedule'       => $row->schedule,
				'jitter_min'     => (int) $row->jitter_min,
				'max_runtime_s'  => (int) $row->max_runtime_s,
				'max_concurrent' => (int) $row->max_concurrent,
				'next_fire_at'   => $row->next_fire_at,
				'last_fired_at'  => $row->last_fired_at,
			];
		}
		return $rows;
	}

	/**
	 * Record the start of a job execution. Called by Pulse immediately
	 * after it decides to fire a job. Returns the row's run_id (echoed
	 * from input — Pulse generates the UUID).
	 *
	 * @param array{run_id: string, job_id: string, fired_at?: string, actor_id?: string, actor_action_id?: string, acted_at?: string} $payload
	 */
	public function recordStart(array $payload): string
	{
		// X.1.a (2026-05-08): actor_action_id + acted_at are A10 audit
		// columns; stored alongside actor_id so an agent's pulse run
		// joins to the matching events table rows by actor_action_id.
		$this->db->table('pulse_runs')->insert([
			'run_id'          => $payload['run_id'],
			'job_id'          => $payload['job_id'],
			'fired_at'        => $payload['fired_at'] ?? date('c'),
			'actor_id'        => $payload['actor_id'] ?? null,
			'actor_action_id' => $payload['actor_action_id'] ?? null,
			'acted_at'        => $payload['acted_at'] ?? ($payload['fired_at'] ?? date('c')),
		]);
		// Bump pulse_jobs.last_fired_at so the catalog reflects activity
		// even if the run never finishes (timeout / SIGKILL surface).
		$this->db->table('pulse_jobs')
			->where('id', $payload['job_id'])
			->update([
				'last_fired_at' => $payload['fired_at'] ?? date('c'),
				'updated_at'    => date('c'),
			]);
		return $payload['run_id'];
	}

	/**
	 * Record the finish of a job execution. Updates the pulse_runs row
	 * AND advances the parent job's next_fire_at by the fallback
	 * interval (real cron parsing lands with A7 gitleaks). Returns the
	 * updated run row.
	 *
	 * @param array{exit_code: int, finished_at?: string, duration_ms?: int, stdout_tail?: string, stderr_tail?: string} $payload
	 */
	public function recordFinish(string $runId, array $payload): ?array
	{
		$run = $this->db->table('pulse_runs')->get($runId);
		if (!$run) {
			return null;
		}
		$nowIso = date('c');
		$update = [
			'exit_code'   => (int) $payload['exit_code'],
			'finished_at' => $payload['finished_at'] ?? $nowIso,
			'duration_ms' => isset($payload['duration_ms']) ? (int) $payload['duration_ms'] : null,
			'stdout_tail' => $payload['stdout_tail'] ?? null,
			'stderr_tail' => $payload['stderr_tail'] ?? null,
			'updated_at'  => $nowIso,
		];
		$this->db->table('pulse_runs')->where('run_id', $runId)->update($update);

		// Advance parent job's next_fire_at by parsing the cron schedule.
		// Without this, jobs whose next_fire_at would otherwise be NULL
		// (e.g. fresh upserts, or runs that finish after a Wing restart)
		// stay perpetually "due" and re-fire every Pulse tick — observed
		// live 2026-05-07 as a 30-second-spam loop until both jobs were
		// manually paused.
		$job = $this->db->table('pulse_jobs')->get($run->job_id);
		$nextIso = $this->computeNextFireAt(
			$job ? (string) $job->schedule : '',
			(int) ($job->jitter_min ?? 0),
		);
		$this->db->table('pulse_jobs')
			->where('id', $run->job_id)
			->update([
				'next_fire_at' => $nextIso,
				'last_fired_at' => $update['finished_at'],
				'updated_at'   => $nowIso,
			]);

		$run = $this->db->table('pulse_runs')->get($runId);
		return $run ? $run->toArray() : null;
	}

	/**
	 * Compute next_fire_at from a 5-field crontab string (minute hour
	 * day-of-month month day-of-week). Falls back to FALLBACK_ADVANCE_SECONDS
	 * when the schedule string can't be parsed (so the job doesn't get
	 * stuck "due" — that would re-fire every Pulse tick).
	 *
	 * jitter_min adds a uniform-random 0..jitter_min minutes to the cron
	 * timestamp so a herd of jobs scheduled at the same minute don't all
	 * fire simultaneously. Pulse already adds its own ThrottleInterval;
	 * this is the wing-side stagger for the catalog.
	 */
	private function computeNextFireAt(string $schedule, int $jitterMin = 0): string
	{
		$now = time();
		try {
			$cron = new CronExpression($schedule);
			$next = $cron->getNextRunDate('@' . $now)->getTimestamp();
		} catch (\Throwable) {
			$next = $now + self::FALLBACK_ADVANCE_SECONDS;
		}
		if ($jitterMin > 0) {
			$next += random_int(0, $jitterMin * 60);
		}
		return date('c', $next);
	}

	/**
	 * Read-only view of a single run, for poll-after-trigger flows.
	 */
	public function getRun(string $runId): ?array
	{
		$row = $this->db->table('pulse_runs')->get($runId);
		return $row ? $row->toArray() : null;
	}

	// ── Job catalog (A7) ──────────────────────────────────────────────────

	/**
	 * Upsert a job registration from the plugin loader's post_compose hook.
	 *
	 * Idempotency key: id = "<plugin_name>:<job_name>".
	 * On UPDATE: next_fire_at is preserved when the schedule is unchanged
	 * (avoids resetting a mid-flight or imminently-scheduled job); set to
	 * NULL (fire immediately) when the schedule changes.
	 *
	 * @param array{plugin_name: string, job_name: string, command: string, schedule: string, ...} $payload
	 * @return array<string, mixed>  Full job row after upsert.
	 */
	public function upsertJob(array $payload): array
	{
		$id  = sprintf('%s:%s', $payload['plugin_name'], $payload['job_name']);
		$now = date('c');

		$fields = [
			'plugin_name'    => $payload['plugin_name'],
			'job_name'       => $payload['job_name'],
			'runner'         => $payload['runner']          ?? 'subprocess',
			'command'        => $payload['command'],
			'args_json'      => json_encode($payload['args'] ?? [], JSON_UNESCAPED_SLASHES),
			'env_json'       => json_encode($payload['env']  ?? [], JSON_UNESCAPED_SLASHES),
			'schedule'       => $payload['schedule'],
			'jitter_min'     => (int) ($payload['jitter_min']     ?? 0),
			'max_runtime_s'  => (int) ($payload['max_runtime_s']  ?? 300),
			'max_concurrent' => (int) ($payload['max_concurrent'] ?? 1),
			'updated_at'     => $now,
		];

		// Compute next_fire_at from the schedule string. Used for fresh
		// inserts AND when an existing job's schedule changed (to retire
		// the stale scheduled time). Without this, NULL → "due every
		// tick" → spam loop (live-observed 2026-05-07 before the cron
		// parser landed).
		$initialNext = $this->computeNextFireAt(
			$payload['schedule'],
			(int) ($payload['jitter_min'] ?? 0),
		);

		$existing = $this->db->table('pulse_jobs')->get($id);
		if ($existing) {
			$update = $fields;
			// Preserve next_fire_at when schedule is unchanged — don't reset
			// a job that is already scheduled close to now or mid-flight.
			if ($existing->schedule !== $payload['schedule']) {
				$update['next_fire_at'] = $initialNext;
			}
			$this->db->table('pulse_jobs')->where('id', $id)->update($update);
		} else {
			$this->db->table('pulse_jobs')->insert([
				'id'          => $id,
				'next_fire_at' => $initialNext,
				'created_at'  => $now,
				...$fields,
			]);
		}

		return $this->db->table('pulse_jobs')->get($id)->toArray();
	}

	/**
	 * Fetch a single job by its composite id (plugin_name:job_name).
	 */
	public function getJob(string $id): ?array
	{
		$row = $this->db->table('pulse_jobs')->get($id);
		return $row ? $row->toArray() : null;
	}

	/**
	 * List all non-removed jobs, ordered by plugin then job name.
	 *
	 * @return list<array<string, mixed>>
	 */
	public function listJobs(): array
	{
		return array_map(
			fn($r) => $r->toArray(),
			iterator_to_array(
				$this->db->table('pulse_jobs')
					->where('removed_at', null)
					->order('plugin_name, job_name')
					->fetchAll(),
			),
		);
	}

	// ── Emergency halt (A12 — /admin big-red-button, 2026-05-07) ─────────
	//
	// Sentinel prefix in pulse_jobs.paused_reason — operator-set "manual:*"
	// pauses must NOT be auto-resumed when the operator clicks Resume after
	// emergency halt. Only halt-set pauses (with this prefix) are eligible
	// for the bulk un-pause.
	private const HALT_REASON_PREFIX = 'emergency-halt:';

	/**
	 * Pause every currently-unpaused job. Returns the number of jobs that
	 * actually transitioned (already-paused jobs are NOT touched —
	 * preserves the operator's manual pause intent across halt cycles).
	 *
	 * The reason field encodes "who halted, when" so the resume sweep
	 * can target only halt-set pauses without disturbing manual ones.
	 */
	public function emergencyHaltAll(string $operator): int
	{
		$now = date('c');
		$reason = self::HALT_REASON_PREFIX . $operator . ':' . $now;

		$affected = $this->db->table('pulse_jobs')
			->where('paused', 0)
			->where('removed_at', null)
			->update([
				'paused'        => 1,
				'paused_reason' => $reason,
				'updated_at'    => $now,
			]);
		return (int) $affected;
	}

	/**
	 * Resume only the jobs paused by an emergency halt (paused_reason
	 * starts with the sentinel prefix). Manual pauses (paused_reason
	 * starting with 'manual:' or anything else) are NOT touched.
	 */
	public function emergencyResumeAll(): int
	{
		$now = date('c');
		$pattern = self::HALT_REASON_PREFIX . '%';

		$affected = $this->db->table('pulse_jobs')
			->where('paused', 1)
			->where('paused_reason LIKE ?', $pattern)
			->where('removed_at', null)
			->update([
				'paused'        => 0,
				'paused_reason' => null,
				'updated_at'    => $now,
			]);
		return (int) $affected;
	}

	/**
	 * Whether at least one job is currently in emergency-halted state.
	 * Used by the layout header to decide whether to show the red banner.
	 */
	public function isEmergencyHaltActive(): bool
	{
		$pattern = self::HALT_REASON_PREFIX . '%';
		return (bool) $this->db->table('pulse_jobs')
			->where('paused', 1)
			->where('paused_reason LIKE ?', $pattern)
			->where('removed_at', null)
			->count('*');
	}

	/**
	 * Counts for the /admin status page: unpaused / emergency-halted /
	 * manually paused / total. The four buckets sum to total, so the
	 * page can render an accurate by-state breakdown without a second
	 * query.
	 *
	 * @return array{unpaused: int, emergency_halted: int, manually_paused: int, total: int}
	 */
	public function jobStateCounts(): array
	{
		$pattern = self::HALT_REASON_PREFIX . '%';
		$tbl = fn() => $this->db->table('pulse_jobs')->where('removed_at', null);
		return [
			'unpaused'         => (int) $tbl()->where('paused', 0)->count('*'),
			'emergency_halted' => (int) $tbl()->where('paused', 1)
				->where('paused_reason LIKE ?', $pattern)->count('*'),
			'manually_paused'  => (int) $tbl()->where('paused', 1)
				->where('paused_reason NOT LIKE ?', $pattern)->count('*'),
			'total'            => (int) $tbl()->count('*'),
		];
	}
}
