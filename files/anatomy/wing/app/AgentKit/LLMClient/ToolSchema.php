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

	/**
	 * OpenAI function-calling shape. `parameters` is ALWAYS present, and an
	 * empty one is forced to a JSON OBJECT: Mistral rejects a tool without
	 * parameters, and PHP's empty array would encode as `[]` where the
	 * protocol demands `{}` (verified 2026-08-16, docs.mistral.ai).
	 *
	 * @return array{type: string, function: array<string, mixed>}
	 */
	public function toOpenAiArray(): array
	{
		$parameters = $this->inputSchema;
		if ($parameters === []) {
			$parameters = ['type' => 'object', 'properties' => new \stdClass()];
		} elseif (($parameters['properties'] ?? null) === []) {
			$parameters['properties'] = new \stdClass();
		}
		return [
			'type' => 'function',
			'function' => [
				'name' => $this->name,
				'description' => $this->description,
				'parameters' => $parameters,
			],
		];
	}
}
