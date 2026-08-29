<?php

declare(strict_types=1);

namespace App\Model;

use Nette\Database\Explorer;

/**
 * Persistence for agent_sessions, agent_threads, agent_iterations.
 * Single repo to keep the lifecycle joins in one mind.
 */
final class AgentSessionRepository
{
	public function __construct(
		private Explorer $db,
	) {
	}

	/**
	 * W6.3 (2026-06-10): session-cap minutes for the stale reaper + the
	 * list-page countdown. Overridable via AGENT_SESSION_CAP_MINUTES env
	 * (wing.plist). 45 = the ~30-min agent budget + grace; a session
	 * legitimately running longer than this has lost its runner anyway
	 * (Pulse max_runtime_s kills the process far earlier).
	 *
	 * Moved here from AgentsPresenter on 2026-08-23, when the reaper gained
	 * callers that are not a page.
	 */
	private const SESSION_CAP_MINUTES_DEFAULT = 45;

	/**
	 * The cap, resolved once here so the reaper and every surface that reports
	 * it cannot drift apart. `AgentsPresenter` used to own this constant and
	 * `terminateStale()` took it as an argument, which meant the only caller
	 * also defined the policy.
	 */
	public function staleCapMinutes(): int
	{
		$env = (int) (getenv('AGENT_SESSION_CAP_MINUTES') ?: 0);
		return $env > 0 ? $env : self::SESSION_CAP_MINUTES_DEFAULT;
	}

	/**
	 * @param array<string, mixed> $row
	 */
	public function startSession(array $row): int
	{
		// A successor closes what its predecessor could not. See
		// `terminateStale()` for why this call is here and not only on a page.
		$this->terminateStale($this->staleCapMinutes());

		$insert = [
			'uuid'          => $row['uuid'],
			'agent_name'    => $row['agent_name'],
			'agent_version' => (int) $row['agent_version'],
			'status'        => 'running',
			'trigger'       => $row['trigger'],
			'trigger_id'    => $row['trigger_id'] ?? null,
			'actor_id'      => $row['actor_id'],
			'trace_id'      => $row['trace_id'],
			'model_uri'     => $row['model_uri'],
			'outcome_id'    => $row['outcome_id'] ?? null,
			'started_at'    => gmdate('c'),
		];
		$this->db->table('agent_sessions')->insert($insert);
		return (int) $this->db->getConnection()->getPdo()->lastInsertId();
	}

	/**
	 * @param array<string, mixed> $patch
	 */
	public function endSession(string $uuid, string $status, string $stopReason, array $patch = []): void
	{
		$update = array_merge([
			'status' => $status,
			'stop_reason' => $stopReason,
			'ended_at' => gmdate('c'),
		], $patch);
		// JSON-encode result_json / error_json if arrays
		foreach (['result_json', 'error_json'] as $jsonField) {
			if (isset($update[$jsonField]) && is_array($update[$jsonField])) {
				$update[$jsonField] = json_encode($update[$jsonField]) ?: null;
			}
		}
		$this->db->table('agent_sessions')->where('uuid', $uuid)->update($update);
	}

	public function findByUuid(string $uuid): ?array
	{
		$row = $this->db->table('agent_sessions')->where('uuid', $uuid)->fetch();
		return $row !== null ? $row->toArray() : null;
	}

	/**
	 * Synthesize an agent_sessions row from a pulse / claude-CLI agent event
	 * (`agent_run_start` / `agent_run_end`). That runtime (pulse-run-agent.sh,
	 * the no-API-key Claude-Max path) emits events grouped by actor_action_id
	 * but never created a session row, so its runs were invisible in /agents
	 * (only /timeline). We upsert the row here keyed on uuid == actor_action_id,
	 * so the run's existing events (the transcript reads them by
	 * actor_action_id) attach automatically. Idempotent: a re-ingested start is
	 * a no-op; the PHP runner's own sessions use agent_session_* event types, so
	 * they never collide with this agent_run_* path.
	 *
	 * @param array<string, mixed> $event
	 */
	public function syncFromAgentEvent(array $event): void
	{
		$type = (string) ($event['type'] ?? '');
		if ($type !== 'agent_run_start' && $type !== 'agent_run_end') {
			return;
		}
		$uuid = (string) ($event['actor_action_id'] ?? '');
		if ($uuid === '') {
			return;
		}
		$actorId = (string) ($event['actor_id'] ?? '');
		// actor_id 'nos-scout' / 'agent:nos-scout' → agent_name 'scout'.
		$agentName = preg_replace('/^(agent:)?nos-/', '', $actorId);
		$agentName = ($agentName !== null && $agentName !== '') ? $agentName : ($actorId ?: 'unknown');
		$ts = (string) ($event['ts'] ?? gmdate('c'));
		$runId = (string) ($event['run_id'] ?? '');
		$existing = $this->findByUuid($uuid);

		// Repair orphaned same-run events: the inner agent writes its own
		// conductor_report event and may leave actor_action_id null (scout
		// did; remediator stamped it). All three share the run_id, so stamp
		// the session uuid onto any null-attribution event of this run — so
		// the report shows in the session transcript regardless of the
		// agent's self-attribution. Idempotent (only touches null/empty).
		if ($runId !== '') {
			$this->db->query(
				'UPDATE events SET actor_action_id = ? WHERE run_id = ? AND (actor_action_id IS NULL OR actor_action_id = ?)',
				$uuid,
				$runId,
				'',
			);
		}

		if ($type === 'agent_run_start') {
			if ($existing !== null) {
				return; // idempotent
			}
			// Same reconcile as the PHP runner's startSession(). This is the
			// path the claude-CLI bridge takes, and it is the path the 2026-08
			// orphan arrived on — so reaping only in the other one would have
			// left exactly this case uncovered.
			$this->terminateStale($this->staleCapMinutes());
			$this->db->table('agent_sessions')->insert($this->synthRow($uuid, $agentName, $actorId, $ts, 'running'));
			return;
		}

		// agent_run_end
		$startedAt = (string) ($existing['started_at'] ?? $ts);
		// Token usage the claude-CLI runtime captured from `claude --output-format
		// json` (.usage) and carried in result.tokens_*. Without it the session
		// detail showed 0/0 for every pulse-run agent. Only set columns present.
		$result = is_array($event['result'] ?? null) ? $event['result'] : [];
		$tokenCols = [];
		foreach (['tokens_input', 'tokens_output', 'tokens_cache_read'] as $col) {
			if (isset($result[$col]) && is_numeric($result[$col])) {
				$tokenCols[$col] = (int) $result[$col];
			}
		}
		if ($existing === null) {
			$row = $this->synthRow($uuid, $agentName, $actorId, $ts, 'idle');
			$row['ended_at'] = $ts;
			$row['stop_reason'] = 'run_end';
			$this->db->table('agent_sessions')->insert($row + $tokenCols);
		} elseif (($existing['status'] ?? '') !== 'idle') {
			$this->db->table('agent_sessions')->where('uuid', $uuid)->update([
				'status'      => 'idle',
				'ended_at'    => $ts,
				'stop_reason' => (string) ($event['result']['stop_reason'] ?? 'run_end'),
			] + $tokenCols);
		}
		$this->linkAgentReports($uuid, $agentName, $actorId, $startedAt, $ts);
	}

	/**
	 * Link the agent's own report events to this session. The inner agent
	 * posts conductor_report with its OWN run_id/actor_action_id (sometimes
	 * NOS_RUN_ID, sometimes self-generated), so neither the run_id repair nor
	 * a lower-bound-only window reliably attaches it. Bind to the run's FULL
	 * window [started_at, ended_at]: agents run one-at-a-time on-demand, so a
	 * report posted in that window belongs to this run — authoritative, so we
	 * override any prior (mis)link. The session's own agent_run_* events are
	 * already this uuid, so `actor_action_id <> uuid` leaves them alone.
	 */
	private function linkAgentReports(string $uuid, string $agentName, string $actorId, string $startedAt, string $endedAt): void
	{
		$this->db->query(
			'UPDATE events SET actor_action_id = ?
			 WHERE (source = ? OR actor_id = ?)
			   AND ts >= ? AND ts <= ?
			   AND (actor_action_id IS NULL OR actor_action_id <> ?)',
			$uuid,
			$agentName,
			$actorId,
			$startedAt,
			$endedAt,
			$uuid,
		);
	}

	/**
	 * @return array<string, mixed>
	 */
	private function synthRow(string $uuid, string $agentName, string $actorId, string $ts, string $status): array
	{
		return [
			'uuid'          => $uuid,
			'agent_name'    => $agentName,
			'agent_version' => 1,
			'status'        => $status,
			'trigger'       => 'pulse',
			'actor_id'      => $actorId,
			'trace_id'      => '',          // claude-CLI runs carry no OTel trace
			// A SENTINEL, and deliberately not URI-shaped. This slot held
			// 'claude-cli' until 2026-08-12 — harmless while no provider was
			// named `claude`, but the day the local-CLI adapter landed that
			// string became a VALID model uri meaning `claude --model cli`, a
			// model that does not exist. A synth row's model is UNRECORDED (the
			// shell bridge does not report which model NOS_AGENT_MODEL pinned),
			// and the sentinel now says so in a shape no Factory::fromUri can
			// parse — feed it to the factory and it throws instead of
			// dispatching a ghost. Rows written before 2026-08-12 still carry
			// 'claude-cli'; they are historical facts, not re-labelled.
			'model_uri'     => 'cli:unrecorded',
			'started_at'    => $ts,
		];
	}

	/**
	 * @return array<int, array<string, mixed>>
	 */
	public function listRecent(int $limit = 50, ?string $agentName = null): array
	{
		$q = $this->db->table('agent_sessions')->order('id DESC')->limit($limit);
		if ($agentName !== null) {
			$q->where('agent_name', $agentName);
		}
		$out = [];
		foreach ($q->fetchAll() as $row) {
			$out[] = $row->toArray();
		}
		return $out;
	}

	/**
	 * WHO CALLS THIS, AND WHY THAT CHANGED (2026-08-23). Until today the only
	 * caller was `AgentsPresenter::renderDefault()`, on the reasoning that
	 * "the page where orphans annoy is the page that clears them". That was
	 * true while Wing /agents was the only surface showing them. It stopped
	 * being true when `tools/red-status.py` shipped (2026-08-18): orphans now
	 * annoy on a READER, which by design cannot write, so the complaint moved
	 * to a surface that must not act and the repair stayed on one nobody had
	 * opened. Measured cost: a surveyor session sat `running` for 110 hours and
	 * was reported red for four days — while a LATER surveyor run started,
	 * finished and went idle beside it without touching it.
	 *
	 * So it is now also called at session OPEN, on both runtimes. A successor
	 * closes what its predecessor could not, which is the right authorship:
	 * the row that says "this run died" is written by something that is
	 * demonstrably alive, never by the run itself.
	 *
	 * W6.3 (2026-06-10): auto-terminate `running` sessions older than the
	 * cap. Failed/killed agent runs (concurrency crash, timeout SIGKILL,
	 * LLM socket error) never emit agent_run_end, so their row hung
	 * `running` forever — 5 orphans were hand-cleaned on 2026-05-30 alone.
	 * Returns the number of rows reaped.
	 */
	public function terminateStale(int $capMinutes): int
	{
		$cutoff = gmdate('c', time() - $capMinutes * 60);
		return $this->db->table('agent_sessions')
			->where('status', 'running')
			->where('started_at < ?', $cutoff)
			->update([
				'status'      => 'terminated',
				'stop_reason' => 'interrupted',
				'ended_at'    => gmdate('c'),
				'error_json'  => json_encode([
					'reason' => "auto-terminated: exceeded {$capMinutes}-minute session cap",
					'by'     => 'wing-stale-reaper',
				]),
			]);
	}

	/**
	 * W6.3: operator manual kill. Marks the SESSION ROW dead so surfaces
	 * self-clean — the OS process (claude CLI) is governed separately by
	 * the Pulse max_runtime kill; this does not signal it. Only a
	 * `running` row can be interrupted (idempotent on repeat clicks).
	 */
	public function markInterrupted(string $uuid, string $by): bool
	{
		$n = $this->db->table('agent_sessions')
			->where('uuid', $uuid)
			->where('status', 'running')
			->update([
				'status'      => 'terminated',
				'stop_reason' => 'interrupted',
				'ended_at'    => gmdate('c'),
				'error_json'  => json_encode(['reason' => 'operator kill', 'by' => $by]),
			]);
		return $n > 0;
	}

	/**
	 * @param array<string, mixed> $row
	 */
	public function startThread(array $row): int
	{
		$insert = [
			'uuid'              => $row['uuid'],
			'session_uuid'      => $row['session_uuid'],
			'parent_thread_uuid'=> $row['parent_thread_uuid'] ?? null,
			'agent_name'        => $row['agent_name'],
			'agent_version'     => (int) $row['agent_version'],
			'role'              => $row['role'],
			'status'            => 'running',
			'trace_id'          => $row['trace_id'],
			'span_id'           => $row['span_id'],
			'started_at'        => gmdate('c'),
		];
		$this->db->table('agent_threads')->insert($insert);
		return (int) $this->db->getConnection()->getPdo()->lastInsertId();
	}

	public function endThread(string $threadUuid, string $stopReason, ?int $tokensIn = null, ?int $tokensOut = null): void
	{
		$update = [
			'status' => 'idle',
			'stop_reason' => $stopReason,
			'ended_at' => gmdate('c'),
		];
		if ($tokensIn !== null) {
			$update['tokens_input'] = $tokensIn;
		}
		if ($tokensOut !== null) {
			$update['tokens_output'] = $tokensOut;
		}
		$this->db->table('agent_threads')->where('uuid', $threadUuid)->update($update);
	}


	/**
	 * Flip a pre-created child thread's status — pending → running on spawn
	 * confirmation. Separate from endChildThread so spawn/exit are clearly
	 * distinguishable in the audit trail.
	 */
	public function markChildThreadRunning(string $threadUuid): void
	{
		$this->db->table('agent_threads')
			->where('uuid', $threadUuid)
			->where('role', 'child')
			->update(['status' => 'running']);
	}

	/**
	 * Close a child thread row when its subprocess exits. status surfaces
	 * one of idle | error | terminated. Optional childSessionUuid links the
	 * parent thread row to the child's own agent_sessions row so /agents UI
	 * can deep-link parent → child. No caller since 2026-08-28 (see above).
	 */
	public function endChildThread(
		string $threadUuid,
		string $status,
		?string $childSessionUuid = null,
		?int $tokensIn = null,
		?int $tokensOut = null,
		?string $errorMessage = null,
	): void {
		// stop_reason captures the cross-process linkage in a single TEXT
		// column without a schema migration. Format: "child_session=<uuid>;
		// status=<status>" with optional "; error=<truncated>". Trivially
		// greppable in the audit trail.
		$parts = [];
		if ($childSessionUuid !== null) {
			$parts[] = 'child_session=' . $childSessionUuid;
		}
		$parts[] = 'status=' . $status;
		if ($errorMessage !== null && $errorMessage !== '') {
			$parts[] = 'error=' . substr(str_replace([';', "\n"], [',', ' '], $errorMessage), 0, 200);
		}
		$update = [
			'status' => $status,
			'stop_reason' => implode('; ', $parts),
			'ended_at' => gmdate('c'),
		];
		if ($tokensIn !== null) {
			$update['tokens_input'] = $tokensIn;
		}
		if ($tokensOut !== null) {
			$update['tokens_output'] = $tokensOut;
		}
		$this->db->table('agent_threads')
			->where('uuid', $threadUuid)
			->where('role', 'child')
			->update($update);
	}

	/**
	 * @return array<int, array<string, mixed>>
	 */
	public function listThreadsForSession(string $sessionUuid): array
	{
		$out = [];
		foreach ($this->db->table('agent_threads')
			->where('session_uuid', $sessionUuid)
			->order('id ASC')
			->fetchAll() as $row) {
			$out[] = $row->toArray();
		}
		return $out;
	}

	public function recordIteration(
		string $sessionUuid,
		int $iteration,
		string $graderResult,
		string $graderFeedback,
		string $graderModel,
		int $durationMs,
		int $tokensIn,
		int $tokensOut,
		/** The gate run that decided this iteration. The DB refuses a
		 *  'satisfied' row without one — see the agent_iterations_satisfied_*
		 *  triggers in bin/init-db.php. */
		?string $gateRunId = null,
	): void {
		$this->db->table('agent_iterations')->insert([
			'session_uuid'    => $sessionUuid,
			'iteration'       => $iteration,
			'grader_result'   => $graderResult,
			'grader_feedback' => $graderFeedback,
			'grader_model'    => $graderModel,
			'duration_ms'     => $durationMs,
			'tokens_input'    => $tokensIn,
			'tokens_output'   => $tokensOut,
			'gate_run_id'     => $gateRunId,
		]);
	}

	/**
	 * Stamp that SOMETHING in this session's structured output had to be
	 * repaired before a consumer could read it — by the deterministic shape
	 * parser or by the one format-only re-ask. Idempotent: many repairs, one
	 * flag. Written by the reader of the repair, never by the repair itself.
	 */
	public function markOutputRepaired(string $sessionUuid): void
	{
		$this->db->table('agent_sessions')
			->where('uuid', $sessionUuid)
			->update(['output_repaired' => 1]);
	}

	/**
	 * @return array<int, array<string, mixed>>
	 */
	public function listIterations(string $sessionUuid): array
	{
		$out = [];
		foreach ($this->db->table('agent_iterations')
			->where('session_uuid', $sessionUuid)
			->order('iteration ASC')
			->fetchAll() as $row) {
			$out[] = $row->toArray();
		}
		return $out;
	}
}
