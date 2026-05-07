<?php

declare(strict_types=1);

namespace App\AgentKit\Tools;

/**
 * Per-call context handed to a tool's execute(). Carries lightweight
 * audit + identity bits so the tool can write events with the correct
 * actor_action_id without the tool needing to import audit infrastructure.
 */
final class ToolContext
{
	public function __construct(
		public readonly string $sessionUuid,
		public readonly string $threadUuid,
		public readonly string $traceId,
		public readonly string $parentSpanId,
		public readonly string $actorId,
		public readonly string $toolUseId,
	) {
	}
}
