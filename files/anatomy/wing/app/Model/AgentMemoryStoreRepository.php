<?php

declare(strict_types=1);

namespace App\Model;

use Nette\Database\Explorer;

/**
 * Persistence for agent_memory_stores (Dreams, post-A14 follow-up).
 *
 * Each row is one consolidated memory entry for an agent — a markdown / text
 * body distilled from recent agent_sessions by the Dreams cycle
 * (bin/dream-agent.php). The table is keyed (agent_name, title) at the
 * application level: upserts replace an existing entry with the same title
 * for the same agent, otherwise insert a new one. SQLite-side we keep the
 * UUID unique only — the de-duplication semantics live here so the LLM
 * driving the dream cycle can express "update this title" via the same
 * repository call as "create this title".
 *
 * Plaintext rules: memory entries are NOT secrets, but they DO carry task
 * context that may include operator notes. NEVER log full `content` in
 * telemetry; restrict to (uuid, title, length) at most. The runtime audit
 * layer (App\AgentKit\Telemetry\AuditEmitter) is the right channel for
 * structured events that want to record "memory updated" — keep payloads
 * small.
 */
final class AgentMemoryStoreRepository
{
	public function __construct(
		private Explorer $db,
	) {
	}

	/**
	 * Most-recent first. Used by Runner::loadMemoryContext() and by the
	 * Dreamer to seed the consolidation prompt.
	 *
	 * @return array<int, array<string, mixed>>
	 */
	public function listRecent(string $agentName, int $limit = 50): array
	{
		if ($limit < 1) {
			return [];
		}
		$out = [];
		foreach ($this->db->table('agent_memory_stores')
			->where('agent_name', $agentName)
			->order('updated_at DESC, id DESC')
			->limit($limit)
			->fetchAll() as $row) {
			$out[] = $row->toArray();
		}
		return $out;
	}

	public function findByUuid(string $uuid): ?array
	{
		$row = $this->db->table('agent_memory_stores')->where('uuid', $uuid)->fetch();
		return $row !== null ? $row->toArray() : null;
	}

	public function findByAgentAndTitle(string $agentName, string $title): ?array
	{
		$row = $this->db->table('agent_memory_stores')
			->where('agent_name', $agentName)
			->where('title', $title)
			->fetch();
		return $row !== null ? $row->toArray() : null;
	}

	public function countForAgent(string $agentName): int
	{
		return (int) $this->db->table('agent_memory_stores')
			->where('agent_name', $agentName)
			->count('*');
	}

	/**
	 * Upsert by (agent_name, title): if an entry exists with the same agent
	 * and title, update its content + source_session_uuid + trace_id and
	 * bump updated_at; otherwise insert a fresh row with a new UUID.
	 *
	 * Returns the row's UUID (newly minted on insert, existing on update)
	 * and a `created` flag that distinguishes the two paths — useful for
	 * dream-cycle deltas reporting.
	 *
	 * @return array{uuid: string, created: bool}
	 */
	public function upsertByTitle(
		string $agentName,
		string $title,
		string $content,
		?string $sourceSessionUuid = null,
		?string $traceId = null,
	): array {
		$existing = $this->findByAgentAndTitle($agentName, $title);
		if ($existing !== null) {
			$this->db->table('agent_memory_stores')
				->where('id', $existing['id'])
				->update([
					'content' => $content,
					'source_session_uuid' => $sourceSessionUuid,
					'trace_id' => $traceId,
					'updated_at' => gmdate('Y-m-d H:i:s'),
				]);
			return ['uuid' => (string) $existing['uuid'], 'created' => false];
		}
		$uuid = self::uuid();
		$this->db->table('agent_memory_stores')->insert([
			'uuid' => $uuid,
			'agent_name' => $agentName,
			'title' => $title,
			'content' => $content,
			'source_session_uuid' => $sourceSessionUuid,
			'trace_id' => $traceId,
		]);
		return ['uuid' => $uuid, 'created' => true];
	}

	public function deleteByUuid(string $uuid): bool
	{
		$affected = $this->db->table('agent_memory_stores')
			->where('uuid', $uuid)
			->delete();
		return $affected > 0;
	}

	/**
	 * Prune oldest entries beyond `keep` for the given agent. Used by the
	 * Dreamer to honour `dream.max_entries`. Returns number of rows removed.
	 */
	public function pruneOldest(string $agentName, int $keep): int
	{
		if ($keep < 0) {
			$keep = 0;
		}
		$rows = $this->db->table('agent_memory_stores')
			->where('agent_name', $agentName)
			->order('updated_at DESC, id DESC')
			->fetchAll();
		$total = count($rows);
		if ($total <= $keep) {
			return 0;
		}
		$removed = 0;
		$idx = 0;
		foreach ($rows as $row) {
			$idx++;
			if ($idx <= $keep) {
				continue;
			}
			$this->db->table('agent_memory_stores')->where('id', $row->id)->delete();
			$removed++;
		}
		return $removed;
	}

	private static function uuid(): string
	{
		$d = random_bytes(16);
		$d[6] = chr((ord($d[6]) & 0x0f) | 0x40);
		$d[8] = chr((ord($d[8]) & 0x3f) | 0x80);
		return vsprintf('%s%s-%s-%s-%s-%s%s%s', str_split(bin2hex($d), 4));
	}
}
