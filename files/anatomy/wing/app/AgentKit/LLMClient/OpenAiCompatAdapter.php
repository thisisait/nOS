<?php

declare(strict_types=1);

namespace App\AgentKit\LLMClient;

use GuzzleHttp\Client as HttpClient;
use GuzzleHttp\Exception\ConnectException;
use GuzzleHttp\Exception\RequestException;

/**
 * The OpenAI-compatible wire protocol, as an AgentKit client.
 *
 * ONE ADAPTER, MANY VENDORS — that is the entire design. `POST
 * {base}/chat/completions` with Bearer auth is the most widely implemented
 * LLM protocol in existence: Mistral (the EU-residency motive that
 * commissioned this), DeepSeek, vLLM, and Ollama's OpenAI surface (the
 * future local orchestrators) all speak it. So this adapter is deliberately
 * VENDOR-BLANK: it has no default endpoint, no env-var key fallback, and a
 * REQUIRED Binding — `openai-*` names a protocol, and a protocol without a
 * backend row is not a place requests can go. The registry row supplies
 * endpoint + bearer + model; the resolver's gates decide whether it may.
 *
 * BUILT ON GUZZLE, NOT AN SDK, and finding 3 of 2026-08-16 is the reason:
 * `AnthropicAdapter` died on `create(...$params)` spreading `max_tokens`
 * into an SDK whose named parameter is `$maxTokens` — a name that merely
 * looked right, failing at call time and blaming the fallback. Here the
 * call convention IS the wire protocol: the JSON body is the contract, and
 * the effect gate pins the exact bytes
 * (tests/anatomy/test_openai_compat_adapter_effects.py, MockHandler +
 * history middleware — request asserted, no network).
 *
 * THE VERIFIED TRIP WIRES (2026-08-16, docs.mistral.ai + probes), each
 * carried structurally rather than as a vendor branch:
 *   * `tool_call_id` must be EXACTLY 9 alphanumeric chars on Mistral.
 *     Anthropic-style ids (`toolu_…`, 24 chars) arrive here whenever a
 *     conversation crosses backends — serveFallback re-sends the SAME
 *     transcript — so every id is passed through `wireId()`: already-legal
 *     ids survive verbatim, everything else maps deterministically
 *     (md5-prefix) so the assistant's tool_calls and the tool results that
 *     answer them stay consistent within and across requests. Universal:
 *     OpenAI and vLLM accept 9-char alphanumerics too.
 *   * Mistral spells it `random_seed`, OpenAI `seed`. This adapter sends
 *     NEITHER — determinism is not a ceremony need — and the gate pins the
 *     absence, so whoever adds it meets the naming split consciously.
 *   * `max_tokens` is the body key both dialects accept (OpenAI's newer
 *     `max_completion_tokens` is not implemented by most compatibles).
 *   * Mistral requires `parameters` present on every function tool, and an
 *     empty one must be a JSON OBJECT — PHP's empty array encodes as `[]`,
 *     so the empty case is forced to `{"type":"object","properties":{}}`.
 */
final class OpenAiCompatAdapter implements LLMClientInterface
{
	public function __construct(
		private readonly HttpClient $http,
		private readonly string $modelUri,
		private readonly Binding $binding,
	) {
		if (!str_starts_with($modelUri, 'openai-')) {
			throw new \InvalidArgumentException("OpenAiCompatAdapter requires openai-* URI; got {$modelUri}");
		}
	}

	public function identifier(): string
	{
		return $this->modelUri;
	}

	/** Which backend serves this adapter's traffic. Never a default. */
	public function backendName(): string
	{
		return $this->binding->name;
	}

	public function send(
		string $systemPrompt,
		array $messages,
		array $tools = [],
		int $maxTokens = 4096,
	): LLMResponse {
		$body = [
			// The binding's tier-resolved id, same rule as the bound
			// AnthropicAdapter: the URI names declared intent, the binding
			// names the served model, and model_effective records it.
			'model' => $this->binding->modelId,
			'max_tokens' => max(1, $maxTokens),
			'messages' => $this->translateMessages($systemPrompt, $messages),
		];
		if ($tools !== []) {
			$body['tools'] = array_map(
				static fn (ToolSchema $t) => $t->toOpenAiArray(),
				$tools,
			);
		}

		try {
			$response = $this->http->request(
				'POST',
				rtrim($this->binding->baseUrl, '/') . '/chat/completions',
				[
					'headers' => [
						'Authorization' => 'Bearer ' . $this->binding->authToken,
						'Content-Type' => 'application/json',
					],
					'json' => $body,
					'http_errors' => true,
				],
			);
		} catch (ConnectException $exc) {
			throw new LLMTransientError(
				"openai-compat backend '{$this->binding->name}' unreachable: " . $exc->getMessage(),
				previous: $exc,
			);
		} catch (RequestException $exc) {
			$status = $exc->getResponse()?->getStatusCode();
			$detail = substr((string) $exc->getResponse()?->getBody(), 0, 300);
			if ($status !== null && $status >= 400 && $status < 500 && $status !== 429) {
				throw new LLMPermanentError(
					"openai-compat '{$this->binding->name}' HTTP {$status}: {$detail}",
					previous: $exc,
				);
			}
			throw new LLMTransientError(
				"openai-compat '{$this->binding->name}' HTTP " . ($status ?? '?') . ": {$detail}",
				previous: $exc,
			);
		}

		$decoded = json_decode((string) $response->getBody(), true);
		if (!is_array($decoded) || !isset($decoded['choices'][0]['message'])) {
			throw new LLMTransientError(
				"openai-compat '{$this->binding->name}' answered 200 without a "
				. 'choices[0].message — a proxy page or a half-implemented '
				. 'compatible, not a completion'
			);
		}

		$message = $decoded['choices'][0]['message'];
		$blocks = [];
		if (isset($message['content']) && is_string($message['content']) && $message['content'] !== '') {
			$blocks[] = ['type' => 'text', 'text' => $message['content']];
		}
		foreach ((array) ($message['tool_calls'] ?? []) as $call) {
			$args = json_decode((string) ($call['function']['arguments'] ?? '{}'), true);
			$blocks[] = [
				'type' => 'tool_use',
				'id' => (string) ($call['id'] ?? ''),
				'name' => (string) ($call['function']['name'] ?? ''),
				// A model emitting unparseable arguments is surfaced as an
				// empty input plus the raw string, not a crash: the Runner
				// hands it to the tool, whose validation says what is wrong.
				'input' => is_array($args) ? $args : ['_raw' => (string) ($call['function']['arguments'] ?? '')],
			];
		}

		$finish = (string) ($decoded['choices'][0]['finish_reason'] ?? 'stop');
		$usage = (array) ($decoded['usage'] ?? []);

		return new LLMResponse(
			stopReason: match ($finish) {
				'stop' => 'end_turn',
				'tool_calls' => 'tool_use',
				'length' => 'max_tokens',
				default => $finish,
			},
			contentBlocks: $blocks,
			tokensInput: (int) ($usage['prompt_tokens'] ?? 0),
			tokensOutput: (int) ($usage['completion_tokens'] ?? 0),
			tokensCacheRead: 0,
			tokensCacheCreation: 0,
		);
	}

	/**
	 * The Anthropic-shaped conversation (Runner's native format), rendered as
	 * OpenAI messages. Roles survive; tool_use becomes assistant tool_calls;
	 * each tool_result becomes its own role=tool message answering the
	 * sanitised id of the call it belongs to.
	 *
	 * @param array<int, Message> $messages
	 * @return array<int, array<string, mixed>>
	 */
	private function translateMessages(string $systemPrompt, array $messages): array
	{
		$out = [];
		if (trim($systemPrompt) !== '') {
			$out[] = ['role' => 'system', 'content' => $systemPrompt];
		}
		foreach ($messages as $msg) {
			$texts = [];
			$toolCalls = [];
			$toolResults = [];
			foreach ($msg->content as $block) {
				$type = is_array($block) ? ($block['type'] ?? '') : '';
				if ($type === 'text') {
					$texts[] = (string) ($block['text'] ?? '');
				} elseif ($type === 'tool_use') {
					$toolCalls[] = [
						'id' => $this->wireId((string) ($block['id'] ?? '')),
						'type' => 'function',
						'function' => [
							'name' => (string) ($block['name'] ?? ''),
							'arguments' => json_encode($block['input'] ?? new \stdClass()) ?: '{}',
						],
					];
				} elseif ($type === 'tool_result') {
					$content = $block['content'] ?? '';
					if (!is_string($content)) {
						$content = json_encode($content) ?: '';
					}
					if (($block['is_error'] ?? false) === true) {
						// OpenAI's protocol has no is_error flag on tool
						// messages; the fact must survive IN the content or
						// the model reads a failure as an answer.
						$content = "ERROR: {$content}";
					}
					$toolResults[] = [
						'role' => 'tool',
						'tool_call_id' => $this->wireId((string) ($block['tool_use_id'] ?? '')),
						'content' => $content,
					];
				}
			}

			if ($msg->role === 'assistant') {
				$entry = ['role' => 'assistant'];
				$entry['content'] = $texts === [] ? null : implode("\n", $texts);
				if ($toolCalls !== []) {
					$entry['tool_calls'] = $toolCalls;
				}
				$out[] = $entry;
			} else {
				// A user turn: tool results first (they answer the previous
				// assistant turn), then any plain text as its own message.
				foreach ($toolResults as $r) {
					$out[] = $r;
				}
				if ($texts !== []) {
					$out[] = ['role' => 'user', 'content' => implode("\n", $texts)];
				}
			}
		}
		return $out;
	}

	/**
	 * A tool id every compatible accepts: exactly 9 alphanumerics (Mistral's
	 * hard requirement; legal everywhere else). Already-legal ids pass
	 * verbatim — same-backend round-trips stay byte-identical — and foreign
	 * ids (Anthropic's `toolu_…` arriving via a cross-backend fallback
	 * transcript) map deterministically, so a call and its result always
	 * agree without the adapter keeping state.
	 */
	private function wireId(string $id): string
	{
		if (preg_match('/^[a-zA-Z0-9]{9}$/', $id)) {
			return $id;
		}
		return substr(md5($id), 0, 9);
	}
}
