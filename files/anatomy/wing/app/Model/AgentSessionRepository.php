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
	 * @param array<string, mixed> $row
	 */
	public function startSession(array $row): int
	{
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
	 * Coordinator pre-creates a child agent_threads row in 'pending' status
	 * BEFORE spawning the subprocess. Status flips pending → running on
	 * spawn confirmation, then to idle / error / terminated on subprocess
	 * exit (handled by markChildThreadStatus / endChildThread).
	 *
	 * Why a separate method: keeps the multi-agent path explicit so future
	 * archaeology of "where do child threads come from?" lands on this entry
	 * point. Callers MUST set role='child' and parent_thread_uuid; the
	 * existing startThread() pattern stays the canonical primary-thread path.
	 *
	 * @param array<string, mixed> $row
	 */
	public function startChildThread(array $row): int
	{
		if (($row['role'] ?? null) !== 'child') {
			throw new \InvalidArgumentException(
				'startChildThread requires role=child; got ' . var_export($row['role'] ?? null, true)
			);
		}
		if (empty($row['parent_thread_uuid'])) {
			throw new \InvalidArgumentException(
				'startChildThread requires non-empty parent_thread_uuid'
			);
		}
		$insert = [
			'uuid'              => $row['uuid'],
			'session_uuid'      => $row['session_uuid'],
			'parent_thread_uuid'=> $row['parent_thread_uuid'],
			'agent_name'        => $row['agent_name'],
			'agent_version'     => (int) ($row['agent_version'] ?? 1),
			'role'              => 'child',
			'status'            => 'pending',
			'trace_id'          => $row['trace_id'],
			'span_id'           => $row['span_id'],
			'started_at'        => gmdate('c'),
		];
		$this->db->table('agent_threads')->insert($insert);
		return (int) $this->db->getConnection()->getPdo()->lastInsertId();
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
	 * one of idle | error | terminated mirroring ProcessPoolResult.status.
	 * Optional childSessionUuid links the parent thread row to the child's
	 * own agent_sessions row (the child runs Runner::run() which creates
	 * its own session uuid + trace_id; we capture it here so /agents UI
	 * can deep-link from coordinator → child).
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
		]);
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
