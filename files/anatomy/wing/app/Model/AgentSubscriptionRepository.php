<?php

declare(strict_types=1);

namespace App\Model;

use Nette\Database\Explorer;

/**
 * Persistence for agent_subscriptions (outbound webhook receivers).
 * Used by App\AgentKit\Webhook\WebhookDispatcher.
 */
final class AgentSubscriptionRepository
{
	public function __construct(
		private Explorer $db,
	) {
	}

	/**
	 * @param array<int, string> $eventTypes
	 */
	public function create(string $url, array $eventTypes, string $signingSecret): int
	{
		$this->db->table('agent_subscriptions')->insert([
			'uuid'           => bin2hex(random_bytes(16)),
			'url'            => $url,
			'event_types'    => implode(',', $eventTypes),
			'signing_secret' => $signingSecret,
		]);
		return (int) $this->db->getConnection()->getPdo()->lastInsertId();
	}

	/**
	 * @return array<int, array{id: int, url: string, signing_secret: string, event_types: string}>
	 */
	public function listEnabledForEventType(string $eventType): array
	{
		$out = [];
		foreach ($this->db->table('agent_subscriptions')
			->where('enabled', 1)
			->fetchAll() as $row) {
			$types = explode(',', (string) $row->event_types);
			if (in_array($eventType, $types, true)) {
				$out[] = [
					'id' => (int) $row->id,
					'url' => (string) $row->url,
					'signing_secret' => (string) $row->signing_secret,
					'event_types' => (string) $row->event_types,
				];
			}
		}
		return $out;
	}

	public function recordSuccess(int $id): void
	{
		$this->db->table('agent_subscriptions')->where('id', $id)->update([
			'consecutive_failures' => 0,
			'last_attempted_at' => gmdate('c'),
			'last_succeeded_at' => gmdate('c'),
			'updated_at' => gmdate('c'),
		]);
	}

	public function recordFailure(int $id): int
	{
		$row = $this->db->table('agent_subscriptions')->where('id', $id)->fetch();
		if ($row === null) {
			return 0;
		}
		$next = (int) $row->consecutive_failures + 1;
		$this->db->table('agent_subscriptions')->where('id', $id)->update([
			'consecutive_failures' => $next,
			'last_attempted_at' => gmdate('c'),
			'updated_at' => gmdate('c'),
		]);
		return $next;
	}

	public function disable(int $id, string $reason): void
	{
		$this->db->table('agent_subscriptions')->where('id', $id)->update([
			'enabled' => 0,
			'disabled_reason' => $reason,
			'updated_at' => gmdate('c'),
		]);
	}

	/**
	 * @return array<int, array<string, mixed>>
	 */
	public function listAll(): array
	{
		$out = [];
		foreach ($this->db->table('agent_subscriptions')->order('id DESC')->fetchAll() as $row) {
			$out[] = $row->toArray();
		}
		return $out;
	}
}
