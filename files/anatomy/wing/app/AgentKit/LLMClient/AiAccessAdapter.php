<?php

declare(strict_types=1);

namespace App\AgentKit\LLMClient;

use AIAccess;
use AIAccess\Chat\FinishReason;
use AIAccess\Chat\Role;
use AIAccess\Chat\TextPart;
use AIAccess\Chat\ToolCallPart;
use AIAccess\Provider\OpenAICompatible;

/**
 * `dg/ai-access` as a TRANSPORT, behind the estate's own two-method contract.
 *
 * THE SPIKE (2026-08-18), decided in `docs/idea/16-orchestrator-question.md` §5.
 * Doc 16 §2 lists the commodity layer — provider adapters, request
 * construction, retry/backoff, tool-schema translation, structured output —
 * and calls it "no differentiation, pure liability". This class is the exit:
 * one file that borrows someone else's maintained client for exactly that
 * layer, while the Runner keeps the iteration, the session ceilings, the
 * synthesis turn and every audit row.
 *
 * WHAT THE SPIKE VERIFIED, since doc 16 §5 listed it as unestablished:
 * `OpenAICompatible\Client` takes `$apiKey` AND `$baseUrl` as constructor
 * arguments, per instance — which is precisely the binding contract in
 * `state/llm-backends.yml` (base_url + bearer resolved per session). No
 * globals, no singleton, no environment. `setOptions()` additionally moves
 * the auth header and prefix, so an endpoint wanting `api-key:` rather than
 * `Authorization: Bearer` needs no new class either.
 *
 * WHY THE STATELESS REPLAY BELOW IS DELIBERATE AND NOT A WORKAROUND.
 * `LLMClientInterface::send()` is stateless by design — the caller hands over
 * the whole conversation every time, which is what lets the Runner rewind an
 * outcome iteration to prompt + feedback. ai-access's `Chat` is stateful. The
 * two meet by building a fresh `Chat` per call and replaying history into it.
 * That is cheap (no I/O until `sendMessage()`) and it keeps the seam honest:
 * the conversation lives in the Runner, so the audit trail cannot drift from
 * what was actually sent.
 *
 * THE ONE THING THIS CLASS MUST NEVER DO. `Chat::setToolLoop()` makes the
 * library execute tool calls itself. It is off by default and it must stay
 * off: that mode moves tool execution — and with it the `agent_tool_use` /
 * `agent_tool_result` audit rows and the pre-spend ceiling check — inside a
 * library's loop. It is the ergonomic path and it is the one shape that gives
 * away the property this estate exists for. Pinned by
 * `tests/anatomy/test_the_borrowed_client_does_not_own_the_loop.py`.
 */
final class AiAccessAdapter implements LLMClientInterface
{
	/** Wire dialects the estate's backends actually speak. */
	public const DIALECT_OPENAI = 'openai';
	public const DIALECT_ANTHROPIC = 'anthropic';

	/**
	 * @param string $uri         our model URI, as it appears in agent.yml and audit rows
	 * @param string $servedModel what the endpoint itself calls the model
	 * @param string $dialect     self::DIALECT_* — see `state/llm-backends.yml`,
	 *                            where `minimax` binds an ANTHROPIC-dialect URL
	 *                            (`api.minimax.io/anthropic`) and `mistral` an
	 *                            OpenAI one. A single dialect would have covered
	 *                            one of the two armed backends.
	 */
	public function __construct(
		private readonly string $uri,
		private readonly string $servedModel,
		private readonly string $baseUrl,
		private readonly string $apiKey,
		private readonly string $dialect = self::DIALECT_OPENAI,
		/** @var array<string, string> extra headers, e.g. OpenRouter's HTTP-Referer */
		private readonly array $extraHeaders = [],
		private readonly ?string $authHeader = null,
		private readonly ?string $authPrefix = null,
	) {
	}

	/**
	 * Both provider clients honour a per-instance base URL — the OpenAI-compatible
	 * one as a constructor argument, the Claude one through `setOptions()`. That
	 * is what makes a binding possible at all, and it is the fact doc 16 §5
	 * listed as unverified.
	 */
	private function client(): AIAccess\Chat\Service
	{
		if ($this->dialect === self::DIALECT_ANTHROPIC) {
			$client = new AIAccess\Provider\Claude\Client(
				apiKey: $this->apiKey,
				chatModel: $this->servedModel,
			);
			$client->setOptions(customBaseUrl: $this->baseUrl);
			return $client;
		}

		$client = new OpenAICompatible\Client(
			apiKey: $this->apiKey,
			baseUrl: $this->baseUrl,
			chatModel: $this->servedModel,
		);
		if ($this->authHeader !== null || $this->authPrefix !== null || $this->extraHeaders !== []) {
			$client->setOptions(
				authHeader: $this->authHeader,
				authPrefix: $this->authPrefix,
				extraHeaders: $this->extraHeaders ?: null,
			);
		}
		return $client;
	}

	public function identifier(): string
	{
		return $this->uri;
	}

	public function send(
		string $systemPrompt,
		array $messages,
		array $tools = [],
		int $maxTokens = 4096,
	): LLMResponse {
		$chat = $this->client()->createChat();
		if ($systemPrompt !== '') {
			$chat->setSystemInstruction($systemPrompt);
		}
		// No handler argument anywhere below — see the class note. Omitting it
		// is what leaves the round trip with us.
		foreach ($tools as $tool) {
			$chat->addTool(new AIAccess\Chat\Tool(
				name: $tool->name,
				description: $tool->description,
				parameters: $tool->inputSchema,
			));
		}

		$this->replay($chat, $messages);

		try {
			$response = $chat->sendMessage();
		} catch (AIAccess\CommunicationException $exc) {
			// Could not reach the endpoint or could not read what came back.
			// Always worth one more attempt; the Runner owns how many.
			throw new LLMTransientError($exc->getMessage(), (int) $exc->getCode(), $exc);
		} catch (AIAccess\ApiException $exc) {
			// The library cuts its exceptions by CAUSE; the estate cuts by
			// RETRYABILITY, which is a different question, so the mapping is
			// ours to make rather than a name-for-name translation.
			// `ApiException` is constructed with the HTTP status as its code
			// (verified against OpenAICompatible\Client), so 429 and 5xx are
			// the transient half and everything else is a request we would
			// only re-send identically.
			$code = (int) $exc->getCode();
			if ($code === 429 || ($code >= 500 && $code < 600)) {
				throw new LLMTransientError($exc->getMessage(), $code, $exc);
			}
			throw new LLMPermanentError($exc->getMessage(), $code, $exc);
		} catch (AIAccess\ServiceException $exc) {
			// UnexpectedResponseException and anything the library adds later.
			// Permanent by default: an unreadable response repeats.
			throw new LLMPermanentError($exc->getMessage(), (int) $exc->getCode(), $exc);
		}

		$usage = $response->getUsage();

		return new LLMResponse(
			stopReason: $this->stopReason($response->getFinishReason()),
			contentBlocks: $this->blocks($response),
			tokensInput: $usage?->inputTokens ?? 0,
			tokensOutput: $usage?->outputTokens ?? 0,
			// A column `agent_sessions` has carried since A14 and that no
			// hand-written adapter ever filled.
			tokensCacheRead: $usage?->cacheReadTokens ?? 0,
			tokensCacheCreation: $usage?->cacheWriteTokens ?? 0,
			// Null, not 0.0: this transport is API-priced and states no cost.
			// The two are different facts (see LLMResponse).
			costUsd: null,
		);
	}

	/**
	 * Replay the Runner's conversation into a fresh Chat.
	 *
	 * Tool results are added through `addToolResult()` rather than as raw
	 * messages because the library merges them into a single Tool turn —
	 * Claude rejects parallel results spread over several turns, and that
	 * merging is one of the provider quirks we are here to stop owning.
	 *
	 * @param array<int, Message> $messages
	 */
	private function replay(AIAccess\Chat\Chat $chat, array $messages): void
	{
		foreach ($messages as $message) {
			$parts = [];
			foreach ($message->content as $block) {
				switch ($block['type'] ?? null) {
					case 'text':
						$parts[] = new TextPart((string) ($block['text'] ?? ''));
						break;
					case 'tool_use':
						$parts[] = new ToolCallPart(
							callId: (string) ($block['id'] ?? ''),
							name: (string) ($block['name'] ?? ''),
							arguments: (array) ($block['input'] ?? []),
						);
						break;
					case 'tool_result':
						// Emitted immediately so `findToolCall()` sees the call
						// that this answers, which was added on the turn before.
						$chat->addToolResult(
							(string) ($block['tool_use_id'] ?? ''),
							(string) ($block['content'] ?? ''),
							(bool) ($block['is_error'] ?? false),
						);
						break;
				}
			}
			if ($parts !== []) {
				$chat->addMessage($parts, $message->role === 'assistant' ? Role::Model : Role::User);
			}
		}
	}

	/**
	 * @return array<int, array<string, mixed>> in Message::$content shape
	 */
	private function blocks(AIAccess\Chat\Response $response): array
	{
		$out = [];
		// getText() is documented to return '' rather than null, and to stay
		// silent about why — getFinishReason() carries that.
		$text = $response->getText();
		if ($text !== '') {
			$out[] = ['type' => 'text', 'text' => $text];
		}
		foreach ($response->getToolCalls() as $call) {
			$out[] = [
				'type' => 'tool_use',
				'id' => $call->callId,
				'name' => $call->name,
				'input' => $call->arguments,
			];
		}
		return $out;
	}

	/**
	 * `FinishReason` is RICHER than the estate's four values, and the mapping
	 * loses information on purpose rather than by accident: `ContentFiltered`
	 * and `Cancelled` both become 'error' because the Runner's only decision
	 * is whether to continue, and neither can be continued. The raw value
	 * stays retrievable from the library if a caller ever needs the
	 * distinction; nothing needs it today.
	 */
	private function stopReason(FinishReason $reason): string
	{
		return match ($reason) {
			FinishReason::ToolCall => 'tool_use',
			FinishReason::TokenLimit => 'max_tokens',
			FinishReason::Complete => 'end_turn',
			FinishReason::ContentFiltered, FinishReason::Cancelled => 'error',
			// Unknown is NOT mapped to end_turn. A provider we cannot read
			// must not be recorded as one that said it was done — that is the
			// exact shape of the defect this loop was fixed for on 2026-08-18.
			FinishReason::Unknown => 'error',
		};
	}
}
