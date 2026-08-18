<?php

declare(strict_types=1);

namespace App\AgentKit\Telemetry;

use App\Model\EventRepository;
use App\Model\UnchainedAuditWrite;

/**
 * Emits AgentKit lifecycle events into the wing.db `events` table via
 * EventRepository. This is the SOURCE OF TRUTH for the audit trail —
 * every agent session, tool call, iteration, and webhook leaves a
 * deterministic, queryable row here.
 *
 * Why direct insert (not HMAC POST to /api/v1/events): we're already
 * inside Wing's process; HMAC is for cross-process / external callers.
 * Going through the repo skips the HTTP round-trip and keeps the audit
 * insert in the same transactional context as the agent_sessions row
 * the runner is also writing.
 */
final class AuditEmitter
{
	public function __construct(
		private readonly EventRepository $events,
	) {
	}

	/**
	 * @param array<string, mixed> $result
	 */
	public function emit(
		string $type,
		string $actorActionId,
		string $actorId,
		?string $task = null,
		array $result = [],
		?string $traceId = null,
	): void {
		$payload = [
			'ts' => gmdate('c'),
			'type' => $type,
			'run_id' => $actorActionId,
			'source' => 'agentkit',
			'actor_id' => $actorId,
			'actor_action_id' => $actorActionId,
			'acted_at' => gmdate('c'),
		];
		if ($task !== null) {
			$payload['task'] = $task;
		}
		if ($traceId !== null) {
			$result['trace_id'] = $traceId;
		}
		if ($result !== []) {
			$payload['result'] = $result;
		}
		try {
			$this->events->insert($payload);
		} catch (UnchainedAuditWrite $exc) {
			// NOT swallowed, and the asymmetry is the point. A transient insert
			// failure leaves a hole in the trail; this one means the trail has
			// stopped being verifiable, and every further row buries the break
			// deeper. Measured 2026-08-16: swallowed here, the librarian ran to
			// completion and exit 0 while appending 37 unsigned rows, and the
			// nightly verify has failed every night since without a single
			// signal from the run that produced it.
			throw $exc;
		} catch (\Throwable $exc) {
			// Audit is critical but we never want to crash the agent because
			// a single insert failed. Log to stderr; the OTel span will still
			// carry the same data.
			error_log('[agentkit] audit insert failed: ' . $exc->getMessage() . ' type=' . $type);
		}
	}
}
