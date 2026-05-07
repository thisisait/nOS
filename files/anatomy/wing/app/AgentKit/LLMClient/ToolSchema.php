<?php

declare(strict_types=1);

namespace App\AgentKit\LLMClient;

/**
 * Vendor-neutral tool declaration. Adapters translate this into provider-
 * specific JSON when calling send() — Anthropic's `tools` array, OpenAI's
 * `tools` array (function-calling), or whatever OpenClaw decides on.
 *
 * `inputSchema` is a JSON-Schema-shaped array describing the tool's input.
 * The same schema serves every adapter; downstream tooling (audit, OTel
 * span attributes, /agents UI) reads it once.
 */
final class ToolSchema
{
	/**
	 * @param array<string, mixed> $inputSchema JSON-Schema-shaped
	 */
	public function __construct(
		public readonly string $name,
		public readonly string $description,
		public readonly array $inputSchema,
	) {
	}

	/**
	 * @return array{name: string, description: string, input_schema: array<string, mixed>}
	 */
	public function toAnthropicArray(): array
	{
		return [
			'name' => $this->name,
			'description' => $this->description,
			'input_schema' => $this->inputSchema,
		];
	}
}
