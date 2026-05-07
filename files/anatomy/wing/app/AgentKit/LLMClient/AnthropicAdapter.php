<?php

declare(strict_types=1);

namespace App\AgentKit\LLMClient;

use Anthropic\Client;
use Anthropic\Core\Exceptions\APIException;

/**
 * LLMClient backed by the official Anthropic PHP SDK.
 *
 * Model URI translation: `anthropic-claude-opus-4-7` → SDK model id
 * `claude-opus-4-7`. The URI scheme strips the leading `anthropic-` and
 * passes the rest verbatim — letting agent.yml use future model names
 * without an adapter change.
 *
 * Errors:
 *  - 4xx (other than 429) → LLMPermanentError. Auth, deprecated model,
 *    bad request — retrying won't help.
 *  - 429 / 5xx / network → LLMTransientError. Caller (Runner) backs off
 *    and retries up to N times before falling back to the secondary URI.
 */
final class AnthropicAdapter implements LLMClientInterface
{
	private readonly string $modelId;

	public function __construct(
		private readonly Client $client,
		private readonly string $modelUri,
	) {
		if (!str_starts_with($modelUri, 'anthropic-')) {
			throw new \InvalidArgumentException("AnthropicAdapter requires anthropic-* URI; got {$modelUri}");
		}
		$this->modelId = substr($modelUri, strlen('anthropic-'));
	}

	public function identifier(): string
	{
		return $this->modelUri;
	}

	public function send(
		string $systemPrompt,
		array $messages,
		array $tools = [],
		int $maxTokens = 4096,
	): LLMResponse {
		$apiMessages = [];
		foreach ($messages as $msg) {
			$apiMessages[] = [
				'role' => $msg->role,
				'content' => $msg->content,
			];
		}

		$apiTools = [];
		foreach ($tools as $tool) {
			$apiTools[] = $tool->toAnthropicArray();
		}

		$params = [
			'model' => $this->modelId,
			'max_tokens' => $maxTokens,
			'messages' => $apiMessages,
		];
		if ($systemPrompt !== '') {
			$params['system'] = $systemPrompt;
		}
		if ($apiTools !== []) {
			$params['tools'] = $apiTools;
		}

		try {
			$message = $this->client->messages->create(...$params);
		} catch (APIException $exc) {
			$status = $this->extractStatus($exc);
			if ($status !== null && $status >= 400 && $status < 500 && $status !== 429) {
				throw new LLMPermanentError(
					"Anthropic API permanent error (HTTP {$status}): " . $exc->getMessage(),
					previous: $exc,
				);
			}
			throw new LLMTransientError(
				'Anthropic API transient error: ' . $exc->getMessage(),
				previous: $exc,
			);
		} catch (\Throwable $exc) {
			throw new LLMTransientError(
				'Anthropic SDK unexpected error: ' . $exc->getMessage(),
				previous: $exc,
			);
		}

		// Translate SDK response → vendor-neutral LLMResponse.
		$contentBlocks = $this->serialiseContent($message->content);
		$usage = $message->usage ?? null;

		return new LLMResponse(
			stopReason: (string) ($message->stopReason ?? 'end_turn'),
			contentBlocks: $contentBlocks,
			tokensInput: $usage?->inputTokens ?? 0,
			tokensOutput: $usage?->outputTokens ?? 0,
			tokensCacheRead: $usage?->cacheReadInputTokens ?? 0,
			tokensCacheCreation: $usage?->cacheCreationInputTokens ?? 0,
		);
	}

	/**
	 * @return array<int, array<string, mixed>>
	 */
	private function serialiseContent(mixed $content): array
	{
		if (is_array($content)) {
			$blocks = $content;
		} elseif (is_iterable($content)) {
			$blocks = iterator_to_array($content, false);
		} else {
			return [];
		}

		$out = [];
		foreach ($blocks as $block) {
			$out[] = $this->blockToArray($block);
		}
		return $out;
	}

	/**
	 * @return array<string, mixed>
	 */
	private function blockToArray(mixed $block): array
	{
		if (is_array($block)) {
			return $block;
		}
		if (is_object($block)) {
			$type = $this->inferBlockType($block);
			$payload = ['type' => $type];
			foreach (['text', 'id', 'name', 'input', 'content', 'tool_use_id', 'is_error'] as $field) {
				if (isset($block->{$field})) {
					$payload[$field] = $this->scalarise($block->{$field});
				}
			}
			return $payload;
		}
		return ['type' => 'text', 'text' => (string) $block];
	}

	private function scalarise(mixed $value): mixed
	{
		if (is_object($value) && method_exists($value, 'toArray')) {
			return $value->toArray();
		}
		if (is_object($value)) {
			return json_decode((string) json_encode($value), true) ?? [];
		}
		return $value;
	}

	private function inferBlockType(object $block): string
	{
		if (isset($block->type) && is_string($block->type)) {
			return $block->type;
		}
		$class = (new \ReflectionClass($block))->getShortName();
		return match (true) {
			str_contains($class, 'Text') => 'text',
			str_contains($class, 'ToolUse') => 'tool_use',
			str_contains($class, 'ToolResult') => 'tool_result',
			default => 'unknown',
		};
	}

	private function extractStatus(APIException $exc): ?int
	{
		if (method_exists($exc, 'getStatusCode')) {
			$status = $exc->getStatusCode();
			if (is_int($status)) {
				return $status;
			}
		}
		// Fallback: regex over message
		if (preg_match('/\b(\d{3})\b/', $exc->getMessage(), $m)) {
			$code = (int) $m[1];
			if ($code >= 400 && $code < 600) {
				return $code;
			}
		}
		return null;
	}
}
