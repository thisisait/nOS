<?php

declare(strict_types=1);

namespace App\AgentKit\LLMClient;

/**
 * One LLM round-trip result. Vendor-neutral.
 *
 * `stopReason` is one of:
 *   - 'end_turn'    — model is done, no more action requested
 *   - 'tool_use'    — model returned tool_use blocks; runner must execute them
 *   - 'max_tokens'  — hit the per-call cap; runner may continue or stop
 *   - 'error'       — adapter wrapped a recoverable error; check $errorMessage
 *
 * `contentBlocks` is the assistant's response content in the same shape as
 * Message::$content — array of {type, ...}. The runner appends a Message
 * with role='assistant' and content=$contentBlocks to the conversation.
 */
final class LLMResponse
{
	/**
	 * @param array<int, array<string, mixed>> $contentBlocks
	 */
	public function __construct(
		public readonly string $stopReason,
		public readonly array $contentBlocks,
		public readonly int $tokensInput,
		public readonly int $tokensOutput,
		public readonly int $tokensCacheRead = 0,
		public readonly int $tokensCacheCreation = 0,
		public readonly ?string $errorMessage = null,
		// Dollars, when the backend reports them. Null means "not reported",
		// which is every API-priced backend today — the claude CLI is the one
		// that states its own cost (`.total_cost_usd`), and a token tally alone
		// cannot reconstruct it there (subscription vs API pricing differ).
		// Null and 0.0 are different facts; do not collapse them.
		public readonly ?float $costUsd = null,
	) {
	}

	/**
	 * @return array<int, array{id: string, name: string, input: array<string, mixed>}>
	 */
	public function toolUseBlocks(): array
	{
		$out = [];
		foreach ($this->contentBlocks as $block) {
			if (($block['type'] ?? null) === 'tool_use') {
				$out[] = [
					'id' => (string) ($block['id'] ?? ''),
					'name' => (string) ($block['name'] ?? ''),
					'input' => (array) ($block['input'] ?? []),
				];
			}
		}
		return $out;
	}

	public function textOutput(): string
	{
		$out = '';
		foreach ($this->contentBlocks as $block) {
			if (($block['type'] ?? null) === 'text') {
				$out .= (string) ($block['text'] ?? '');
			}
		}
		return $out;
	}
}
