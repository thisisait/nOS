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
	 * `content` is FORCED into valid UTF-8 here, at the one point every tool
	 * routes through, because one invalid byte anywhere kills the session on
	 * every provider at once: json_encode refuses the whole request body, the
	 * fallback client fails identically, and the audit row that would explain
	 * it is the literal `0` json_encode returns on failure. Measured twice —
	 * BashReadOnlyTool 2026-08-17 (`tree` over a filesystem), librarian
	 * 2026-08-27 (KEAP's Czech corpus, 118k then 121k tokens). Guarding each
	 * tool separately is what let the second one happen.
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
