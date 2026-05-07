<?php

declare(strict_types=1);

namespace App\AgentKit\LLMClient;

/**
 * Platform-agnostic LLM contract. Every backend (Anthropic API, OpenClaw,
 * OpenAI, future local Ollama) implements this exact protocol so an agent
 * defined with `model.primary: anthropic-claude-opus-4-7` can flip to
 * `openclaw-qwen-coder-32b` by swapping the URI — system prompt, tool
 * roster, audit trail, OTel spans all stay identical.
 *
 * The contract is deliberately minimal:
 *  - send(): one tool-use round trip. The runner loops until the model
 *    returns end_turn or max_iterations is reached.
 *  - identifier(): the URI scheme used in agent.yml + audit events.
 *
 * Anything richer (streaming, multi-turn buffering, model-specific knobs)
 * lives in the adapter, not in the interface, so we don't accidentally
 * pull a feature from one provider that another can't honour.
 */
interface LLMClientInterface
{
	/**
	 * The URI form of this client's model — exactly what appears in
	 * agent.yml::model.primary and in audit events. Lowercase + dashes.
	 * Examples: 'anthropic-claude-opus-4-7', 'openclaw-qwen-coder-32b'.
	 */
	public function identifier(): string;

	/**
	 * One model invocation.
	 *
	 * @param string $systemPrompt    may be empty
	 * @param array<int, Message> $messages conversation history (oldest first)
	 * @param array<int, ToolSchema> $tools tool definitions in vendor-neutral form
	 * @param int    $maxTokens
	 * @return LLMResponse           contains text + tool_use blocks + token usage
	 * @throws LLMTransientError      when retry-able (rate limit, 5xx, network)
	 * @throws LLMPermanentError      when fatal (auth, model deprecation, bad request)
	 */
	public function send(
		string $systemPrompt,
		array $messages,
		array $tools = [],
		int $maxTokens = 4096,
	): LLMResponse;
}
