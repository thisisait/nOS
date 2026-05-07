<?php

declare(strict_types=1);

namespace App\AgentKit\LLMClient;

/**
 * One conversation turn. Vendor-neutral shape — adapters translate to/from
 * provider-specific JSON in send().
 *
 * `role` is always 'user' or 'assistant'. System prompts are NOT messages —
 * they're a separate parameter on send().
 *
 * `content` is an array of content blocks. Each block is one of:
 *   ['type' => 'text', 'text' => '...']
 *   ['type' => 'tool_use', 'id' => 'toolu_...', 'name' => '...', 'input' => [...]]
 *   ['type' => 'tool_result', 'tool_use_id' => 'toolu_...', 'content' => '...', 'is_error' => bool]
 *
 * This shape is borrowed verbatim from Anthropic's Messages API because it's
 * already the de-facto industry shape (OpenAI's Chat Completions and most
 * tool-calling LLMs map to it cleanly).
 */
final class Message
{
	/**
	 * @param 'user'|'assistant' $role
	 * @param array<int, array<string, mixed>> $content content blocks
	 */
	public function __construct(
		public readonly string $role,
		public readonly array $content,
	) {
	}

	public static function userText(string $text): self
	{
		return new self('user', [['type' => 'text', 'text' => $text]]);
	}

	public static function assistantText(string $text): self
	{
		return new self('assistant', [['type' => 'text', 'text' => $text]]);
	}

	/**
	 * Build a user message that delivers tool results back to the model.
	 *
	 * @param array<int, array{tool_use_id: string, content: string, is_error?: bool}> $results
	 */
	public static function userToolResults(array $results): self
	{
		$blocks = [];
		foreach ($results as $r) {
			$blocks[] = [
				'type' => 'tool_result',
				'tool_use_id' => $r['tool_use_id'],
				'content' => $r['content'],
				'is_error' => (bool) ($r['is_error'] ?? false),
			];
		}
		return new self('user', $blocks);
	}
}
