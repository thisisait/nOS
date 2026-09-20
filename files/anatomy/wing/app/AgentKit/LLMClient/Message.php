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
 *   ['type' => 'image', 'source' => ['type' => 'base64', 'media_type' => 'image/png', 'data' => '...']]
 *
 * This shape is borrowed verbatim from Anthropic's Messages API because it's
 * already the de-facto industry shape (OpenAI's Chat Completions and most
 * tool-calling LLMs map to it cleanly). The image block is Anthropic's own
 * wire shape for the same reason: AnthropicAdapter::send() passes
 * `$msg->content` straight through, so a block shaped for Anthropic needs no
 * adapter change there; OpenAiCompatAdapter::translateMessages() is the one
 * that re-encodes it (base64 data URI in an `image_url` part — the OpenAI
 * vision content-block shape Ollama's OpenAI-compatible endpoint documents,
 * https://docs.ollama.com/api/openai-compatibility).
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
	 * A user turn carrying an image (e.g. an invoice scan) plus an optional
	 * caption/prompt. Bytes in, not a path — the caller (OneShot) owns
	 * reading the file, so this stays testable with a stub adapter and no
	 * filesystem.
	 */
	public static function userImageBytes(string $bytes, string $mediaType, ?string $prompt = null): self
	{
		$blocks = [];
		if ($prompt !== null && trim($prompt) !== '') {
			$blocks[] = ['type' => 'text', 'text' => $prompt];
		}
		$blocks[] = [
			'type' => 'image',
			'source' => ['type' => 'base64', 'media_type' => $mediaType, 'data' => base64_encode($bytes)],
		];
		return new self('user', $blocks);
	}

	/** Reads $path off disk and infers media_type from its extension. */
	public static function userImage(string $path, ?string $prompt = null): self
	{
		$bytes = @file_get_contents($path);
		if ($bytes === false) {
			throw new \RuntimeException("Message::userImage: cannot read {$path}");
		}
		return self::userImageBytes($bytes, self::mediaTypeFor($path), $prompt);
	}

	private static function mediaTypeFor(string $path): string
	{
		return match (strtolower(pathinfo($path, PATHINFO_EXTENSION))) {
			'jpg', 'jpeg' => 'image/jpeg',
			'png' => 'image/png',
			'gif' => 'image/gif',
			'webp' => 'image/webp',
			default => throw new \InvalidArgumentException(
				"Message::userImage: unsupported image extension in {$path} "
				. '(supported: jpg, jpeg, png, gif, webp)'
			),
		};
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
