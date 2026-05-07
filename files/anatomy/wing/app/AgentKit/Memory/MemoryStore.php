<?php

declare(strict_types=1);

namespace App\AgentKit\Memory;

use App\Model\AgentMemoryStoreRepository;

/**
 * Domain-level facade over AgentMemoryStoreRepository for the Dreams cycle.
 *
 * The repository is the persistence-layer concern (Nette Database calls,
 * SQL shape, raw associative arrays). MemoryStore is the
 * App\AgentKit\Memory namespace surface that Dreamer consumes —
 * value-object-ish entries, telemetry-safe redaction helpers, and the
 * "recall + commit" pattern the dream cycle expresses.
 *
 * Plaintext rule (locked by the contract): NEVER log full content. The
 * helpers here always return / format `(uuid, title, length)` triples
 * for telemetry; full content is only ever returned by `recall()` for the
 * LLM call itself.
 */
final class MemoryStore
{
	public function __construct(
		private readonly AgentMemoryStoreRepository $repo,
	) {
	}

	/**
	 * @return array<int, MemoryEntry>
	 */
	public function recall(string $agentName, int $limit = 50): array
	{
		$out = [];
		foreach ($this->repo->listRecent($agentName, $limit) as $row) {
			$out[] = MemoryEntry::fromRow($row);
		}
		return $out;
	}

	public function size(string $agentName): int
	{
		return $this->repo->countForAgent($agentName);
	}

	/**
	 * Commit one memory entry. Upsert by (agent_name, title) — the LLM is
	 * expected to choose stable titles for facts it wants to update across
	 * dream cycles.
	 *
	 * Returns a delta record suitable for the dream-cycle JSON summary.
	 *
	 * @return array{uuid: string, title: string, action: 'created'|'updated', length: int}
	 */
	public function commit(
		string $agentName,
		string $title,
		string $content,
		?string $sourceSessionUuid = null,
		?string $traceId = null,
	): array {
		$res = $this->repo->upsertByTitle(
			$agentName,
			$title,
			$content,
			$sourceSessionUuid,
			$traceId,
		);
		return [
			'uuid' => $res['uuid'],
			'title' => $title,
			'action' => $res['created'] ? 'created' : 'updated',
			'length' => strlen($content),
		];
	}

	public function forget(string $uuid): bool
	{
		return $this->repo->deleteByUuid($uuid);
	}

	public function prune(string $agentName, int $keep): int
	{
		return $this->repo->pruneOldest($agentName, $keep);
	}

	/**
	 * Telemetry-safe summary: (uuid, title, length) — never the body.
	 *
	 * @param array<int, MemoryEntry> $entries
	 * @return array<int, array{uuid: string, title: string, length: int}>
	 */
	public static function redactForTelemetry(array $entries): array
	{
		$out = [];
		foreach ($entries as $entry) {
			$out[] = [
				'uuid' => $entry->uuid,
				'title' => $entry->title,
				'length' => strlen($entry->content),
			];
		}
		return $out;
	}
}

/**
 * One memory entry — immutable, value-object-shaped. Constructed only via
 * fromRow() so MemoryStore stays the single ingress point.
 */
final class MemoryEntry
{
	public function __construct(
		public readonly string $uuid,
		public readonly string $agentName,
		public readonly string $title,
		public readonly string $content,
		public readonly ?string $sourceSessionUuid,
		public readonly ?string $traceId,
		public readonly ?string $createdAt,
		public readonly ?string $updatedAt,
	) {
	}

	/**
	 * @param array<string, mixed> $row
	 */
	public static function fromRow(array $row): self
	{
		return new self(
			uuid: (string) ($row['uuid'] ?? ''),
			agentName: (string) ($row['agent_name'] ?? ''),
			title: (string) ($row['title'] ?? ''),
			content: (string) ($row['content'] ?? ''),
			sourceSessionUuid: isset($row['source_session_uuid']) ? (string) $row['source_session_uuid'] : null,
			traceId: isset($row['trace_id']) ? (string) $row['trace_id'] : null,
			createdAt: isset($row['created_at']) ? (string) $row['created_at'] : null,
			updatedAt: isset($row['updated_at']) ? (string) $row['updated_at'] : null,
		);
	}
}
