<?php

declare(strict_types=1);

namespace App\Model;

use Nette\Database\Explorer;

/**
 * Operator-attention notifications (Anatomy A9, 2026-05-16).
 *
 * One row per emitted notification. Source-of-truth is wing.db.notifications;
 * Bone's POST /api/v1/notifications inserts here, the /inbox presenter reads
 * here, and the dispatch worker (bin/dispatch-notifications.php) updates the
 * per-channel timestamps as it delivers to ntfy/mail.
 *
 * All writes go through insert(); the only mutator outside that is markRead()
 * (operator clicks "mark read" in /inbox) and the two channel-dispatched
 * helpers used by the dispatch worker.
 */
final class NotificationRepository
{
	/** @var string[] Whitelisted severity levels (manifest-aligned). */
	public const VALID_SEVERITIES = ['critical', 'high', 'medium', 'low', 'info'];

	/** @var string[] Whitelisted channels. */
	public const VALID_CHANNELS = ['wing-inbox', 'ntfy', 'mail'];

	public function __construct(
		private Explorer $db,
	) {
	}

	/**
	 * Insert one notification. Returns the new row id.
	 *
	 * Caller is responsible for severity + channels whitelisting (Bone does
	 * this at the API gate); we re-validate here as defense-in-depth.
	 *
	 * @param array<string,mixed> $payload
	 */
	public function insert(array $payload): int
	{
		$severity = (string) ($payload['severity'] ?? 'info');
		if (!in_array($severity, self::VALID_SEVERITIES, true)) {
			throw new \InvalidArgumentException("invalid severity: {$severity}");
		}

		$channels = $payload['channels'] ?? ['wing-inbox'];
		if (!is_array($channels) || $channels === []) {
			$channels = ['wing-inbox'];
		}
		foreach ($channels as $ch) {
			if (!in_array($ch, self::VALID_CHANNELS, true)) {
				throw new \InvalidArgumentException("invalid channel: {$ch}");
			}
		}

		$metadata = $payload['metadata'] ?? [];
		if (!is_array($metadata)) {
			$metadata = [];
		}

		$row = [
			'uuid'            => (string) ($payload['uuid'] ?? self::uuid4()),
			'severity'        => $severity,
			'title'           => (string) ($payload['title'] ?? ''),
			'body'            => $payload['body']            ?? null,
			'actor_id'        => $payload['actor_id']        ?? null,
			'actor_action_id' => $payload['actor_action_id'] ?? null,
			'target_actor_id' => (string) ($payload['target_actor_id'] ?? 'operator'),
			'origin_plugin'   => $payload['origin_plugin']   ?? null,
			'origin_agent'    => $payload['origin_agent']    ?? null,
			'source_event_id' => isset($payload['source_event_id']) ? (int) $payload['source_event_id'] : null,
			'channels_json'   => json_encode(array_values(array_unique($channels))),
			'metadata_json'   => json_encode($metadata),
		];

		if ($row['title'] === '') {
			throw new \InvalidArgumentException('title is required');
		}

		$this->db->table('notifications')->insert($row);
		return (int) $this->db->getConnection()->getPdo()->lastInsertId();
	}

	/**
	 * List notifications for an inbox view.
	 *
	 * Filters: target_actor_id (default 'operator'), severity, unread_only,
	 * since (ISO-8601). limit capped at 500.
	 *
	 * @param array<string,mixed> $filters
	 * @return array{items: array<int,array<string,mixed>>, total: int}
	 */
	public function query(array $filters = [], int $limit = 100): array
	{
		$limit = max(1, min(500, $limit));
		$query = $this->db->table('notifications')->order('id DESC');

		$target = $filters['target_actor_id'] ?? 'operator';
		$query->where('target_actor_id', (string) $target);

		if (!empty($filters['severity'])) {
			$query->where('severity', $filters['severity']);
		}
		if (!empty($filters['unread_only'])) {
			$query->where('wing_inbox_read_at', null);
		}
		if (!empty($filters['since'])) {
			$query->where('created_at >= ?', $filters['since']);
		}
		if (!empty($filters['actor_action_id'])) {
			$query->where('actor_action_id', $filters['actor_action_id']);
		}

		$total = (clone $query)->count('*');
		$query->limit($limit);

		$items = [];
		foreach ($query as $r) {
			$items[] = $this->hydrate($r);
		}
		return ['items' => $items, 'total' => (int) $total];
	}

	public function findByUuid(string $uuid): ?array
	{
		$r = $this->db->table('notifications')->where('uuid', $uuid)->fetch();
		return $r ? $this->hydrate($r) : null;
	}

	/**
	 * Count unread for an actor (cheap; used by the navbar badge).
	 */
	public function countUnread(string $targetActorId = 'operator'): int
	{
		return (int) $this->db->table('notifications')
			->where('target_actor_id', $targetActorId)
			->where('wing_inbox_read_at', null)
			->count('*');
	}

	/**
	 * Mark a notification as read. Returns true if a row was updated.
	 */
	public function markRead(string $uuid): bool
	{
		$now = gmdate('c');
		$affected = $this->db->table('notifications')
			->where('uuid', $uuid)
			->where('wing_inbox_read_at', null)
			->update(['wing_inbox_read_at' => $now]);
		return $affected > 0;
	}

	/**
	 * Rows whose `channel` is listed in channels_json but the per-channel
	 * dispatched_at column is NULL. Used by the dispatch worker.
	 *
	 * @return array<int,array<string,mixed>>
	 */
	public function pendingForChannel(string $channel, int $limit = 100): array
	{
		if (!in_array($channel, self::VALID_CHANNELS, true)) {
			throw new \InvalidArgumentException("invalid channel: {$channel}");
		}
		if ($channel === 'wing-inbox') {
			throw new \InvalidArgumentException('wing-inbox has no dispatch pipeline; use unread_only query filter');
		}

		$column = $channel === 'ntfy' ? 'ntfy_dispatched_at' : 'mail_dispatched_at';
		$limit = max(1, min(500, $limit));

		$rows = $this->db->getConnection()->fetchAll(
			"SELECT * FROM notifications
			 WHERE {$column} IS NULL
			   AND channels_json LIKE ?
			 ORDER BY id ASC
			 LIMIT ?",
			'%"' . $channel . '"%',
			$limit,
		);

		$out = [];
		foreach ($rows as $r) {
			$out[] = $this->hydrate($r);
		}
		return $out;
	}

	public function markDispatched(string $uuid, string $channel, ?string $error = null): bool
	{
		if (!in_array($channel, ['ntfy', 'mail'], true)) {
			throw new \InvalidArgumentException("invalid dispatch channel: {$channel}");
		}
		$tsColumn  = $channel === 'ntfy' ? 'ntfy_dispatched_at' : 'mail_dispatched_at';
		$errColumn = $channel === 'ntfy' ? 'ntfy_error'         : 'mail_error';

		$now = gmdate('c');
		$update = [$tsColumn => $now];
		if ($error !== null && $error !== '') {
			$update[$errColumn] = $error;
		}
		$affected = $this->db->table('notifications')
			->where('uuid', $uuid)
			->update($update);
		return $affected > 0;
	}

	/**
	 * @param iterable<string,mixed>|object $row
	 * @return array<string,mixed>
	 */
	private function hydrate(mixed $row): array
	{
		$arr = is_array($row) ? $row : iterator_to_array($row);
		$channels = [];
		if (!empty($arr['channels_json'])) {
			$decoded = json_decode((string) $arr['channels_json'], true);
			if (is_array($decoded)) {
				$channels = $decoded;
			}
		}
		$metadata = [];
		if (!empty($arr['metadata_json'])) {
			$decoded = json_decode((string) $arr['metadata_json'], true);
			if (is_array($decoded)) {
				$metadata = $decoded;
			}
		}
		$arr['channels'] = $channels;
		$arr['metadata'] = $metadata;
		return $arr;
	}

	private static function uuid4(): string
	{
		$data = random_bytes(16);
		$data[6] = chr((ord($data[6]) & 0x0f) | 0x40);
		$data[8] = chr((ord($data[8]) & 0x3f) | 0x80);
		return vsprintf('%s%s-%s-%s-%s-%s%s%s', str_split(bin2hex($data), 4));
	}
}
