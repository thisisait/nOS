<?php

declare(strict_types=1);

namespace App\AgentKit\Tools;

/**
 * Tool execution result, fed back to the LLM as a tool_result content block.
 *
 * `content` is what the LLM sees. Keep it terse; tools should NOT dump full
 * stdout if a 5-line summary suffices — context is precious.
 *
 * `isError=true` flags the result as a failure so the LLM can self-correct
 * without the runner having to terminate the session.
 *
 * `metadata` is opaque to the LLM but lands in the audit event for the
 * tool call. Use it for things like exit codes, timing, file paths touched.
 */
final class ToolResult
{
	public readonly string $content;

	/**
	 * `content` is forced into valid UTF-8 HERE, where every tool meets: one
	 * invalid byte makes json_encode refuse the whole request body and kills
	 * the session on every provider at once (2026-08-17, 2026-08-27).
	 *
	 * @param array<string, mixed> $metadata
	 */
	public function __construct(
		string $content,
		public readonly bool $isError = false,
		public readonly array $metadata = [],
	) {
		$this->content = mb_check_encoding($content, 'UTF-8')
			? $content
			: mb_convert_encoding($content, 'UTF-8', 'UTF-8')
				. "\n...[some bytes were not valid UTF-8 and were replaced]";
	}

	public static function ok(string $content, array $metadata = []): self
	{
		return new self($content, false, $metadata);
	}

	public static function error(string $content, array $metadata = []): self
	{
		return new self($content, true, $metadata);
	}
}
