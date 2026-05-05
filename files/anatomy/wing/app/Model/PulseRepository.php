<?php

declare(strict_types=1);

namespace App\Model;

use Nette\Database\Explorer;

/**
 * Pulse job catalog + run history. Anatomy P0.2 (2026-05-04).
 *
 * Tables ``pulse_jobs`` + ``pulse_runs`` are defined in
 * ``files/anatomy/wing/db/schema-extensions.sql:176-219``. The Pulse
 * daemon (``files/anatomy/pulse/``) polls Wing for due jobs, fires
 * them, and posts run_start + run_finish. Cron-expression parsing for
 * server-side ``next_fire_at`` recomputation is deferred — the MVP
 * advances by a flat fallback interval; A7 (gitleaks) lands real cron.
 */
final class PulseRepository
{
	/** Default next-fire advance when no cron parser is wired. */
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
	 * @param array{run_id: string, job_id: string, fired_at?: string, actor_id?: string} $payload
	 */
	public function recordStart(array $payload): string
	{
		$this->db->table('pulse_runs')->insert([
			'run_id'   => $payload['run_id'],
			'job_id'   => $payload['job_id'],
			'fired_at' => $payload['fired_at'] ?? date('c'),
			'actor_id' => $payload['actor_id'] ?? null,
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

		// Advance parent job's next_fire_at. MVP: flat fallback. Real
		// cron parsing (and respect for jitter_min) follows in A7.
		$nextIso = date('c', time() + self::FALLBACK_ADVANCE_SECONDS);
		$this->db->table('pulse_jobs')
			->where('id', $run->job_id)
			->update([
				'next_fire_at' => $nextIso,
				'updated_at'   => $nowIso,
			]);

		$run = $this->db->table('pulse_runs')->get($runId);
		return $run ? $run->toArray() : null;
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

		$existing = $this->db->table('pulse_jobs')->get($id);
		if ($existing) {
			$update = $fields;
			// Preserve next_fire_at when schedule is unchanged — don't reset
			// a job that is already scheduled close to now or mid-flight.
			if ($existing->schedule !== $payload['schedule']) {
				$update['next_fire_at'] = null;
			}
			$this->db->table('pulse_jobs')->where('id', $id)->update($update);
		} else {
			$this->db->table('pulse_jobs')->insert([
				'id'          => $id,
				'next_fire_at' => null, // fires on first Pulse tick after registration
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
}
