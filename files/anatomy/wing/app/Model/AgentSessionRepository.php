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
