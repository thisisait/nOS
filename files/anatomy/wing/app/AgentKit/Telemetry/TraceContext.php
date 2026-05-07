<?php

declare(strict_types=1);

namespace App\AgentKit\Telemetry;

/**
 * W3C Trace Context primitives. Trace IDs are 16-byte (32 hex) random;
 * span IDs are 8-byte (16 hex) random.
 *
 * The runner generates one trace_id per agent session — every LLM call,
 * tool call, grader invocation, and child-agent thread within that session
 * shares the trace_id. Span ids cascade: session root → thread → llm.call.
 *
 * Format: lowercase hex, fixed length. We use random_bytes (CSPRNG) so
 * trace IDs cannot be guessed by an external party, mitigating the risk of
 * an attacker forging an audit row by guessing the actor_action_id.
 */
final class TraceContext
{
	public static function newTraceId(): string
	{
		return bin2hex(random_bytes(16));
	}

	public static function newSpanId(): string
	{
		return bin2hex(random_bytes(8));
	}
}
