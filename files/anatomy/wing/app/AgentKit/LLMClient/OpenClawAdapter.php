<?php

declare(strict_types=1);

namespace App\AgentKit\LLMClient;

use GuzzleHttp\Client as HttpClient;
use GuzzleHttp\Exception\ConnectException;
use GuzzleHttp\Exception\GuzzleException;
use GuzzleHttp\Exception\RequestException;

/**
 * LLMClient backed by OpenClaw (local Ollama-style HTTP gateway running on
 * the host).  Implements the same tool-use loop semantics as
 * AnthropicAdapter so an agent flips backends with a one-line URI change.
 *
 * Wire format: OpenClaw mirrors Anthropic's Messages API on
 * /v1/messages (system + messages + tools + max_tokens) and returns a
 * shape-compatible response. Until OpenClaw fully ships its tool-use
 * surface this adapter sends tools as a passthrough hint and accepts
 * text-only responses; tool_use blocks are extracted if present.
 *
 * Configuration:
 *   OPENCLAW_BASE_URL   default http://127.0.0.1:18789
 *   OPENCLAW_TIMEOUT    default 120 (seconds; local LLM can be slow)
 */
final class OpenClawAdapter implements LLMClientInterface
{
	private readonly string $modelId;

	public function __construct(
		private readonly HttpClient $http,
		private readonly string $modelUri,
		private readonly string $baseUrl = 'http://127.0.0.1:18789',
		private readonly float $timeout = 120,
	) {
		if (!str_starts_with($modelUri, 'openclaw-')) {
			throw new \InvalidArgumentException("OpenClawAdapter requires openclaw-* URI; got {$modelUri}");
		}
		$this->modelId = substr($modelUri, strlen('openclaw-'));
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
		$payload = [
			'model' => $this->modelId,
			'max_tokens' => $maxTokens,
			'messages' => array_map(static fn (Message $m) => [
				'role' => $m->role,
				'content' => $m->content,
			], $messages),
		];
		if ($systemPrompt !== '') {
			$payload['system'] = $systemPrompt;
		}
		if ($tools !== []) {
			$payload['tools'] = array_map(
				static fn (ToolSchema $t) => $t->toAnthropicArray(),
				$tools,
			);
		}

		try {
			$response = $this->http->request('POST', rtrim($this->baseUrl, '/') . '/v1/messages', [
				'json' => $payload,
				'timeout' => $this->timeout,
				'headers' => ['Content-Type' => 'application/json'],
			]);
		} catch (ConnectException $exc) {
			throw new LLMTransientError(
				'OpenClaw unreachable at ' . $this->baseUrl . ': ' . $exc->getMessage(),
				previous: $exc,
			);
		} catch (RequestException $exc) {
			$status = $exc->getResponse()?->getStatusCode();
			if ($status !== null && $status >= 400 && $status < 500 && $status !== 429) {
				throw new LLMPermanentError(
					"OpenClaw permanent error (HTTP {$status}): " . $exc->getMessage(),
					previous: $exc,
				);
			}
			throw new LLMTransientError(
				'OpenClaw transient error: ' . $exc->getMessage(),
				previous: $exc,
			);
		} catch (GuzzleException $exc) {
			throw new LLMTransientError(
				'OpenClaw HTTP error: ' . $exc->getMessage(),
				previous: $exc,
			);
		}

		$body = (string) $response->getBody();
		$decoded = json_decode($body, true);
		if (!is_array($decoded)) {
			throw new LLMTransientError('OpenClaw returned non-JSON body: ' . substr($body, 0, 200));
		}

		$content = $decoded['content'] ?? [];
		if (!is_array($content)) {
			$content = [['type' => 'text', 'text' => (string) $content]];
		}
		// Normalise simplified text responses
		if ($content !== [] && !isset($content[0]['type']) && isset($content[0])) {
			$content = [['type' => 'text', 'text' => json_encode($content) ?: '']];
		}

		$usage = $decoded['usage'] ?? [];
		return new LLMResponse(
			stopReason: (string) ($decoded['stop_reason'] ?? 'end_turn'),
			contentBlocks: $content,
			tokensInput: (int) ($usage['input_tokens'] ?? 0),
			tokensOutput: (int) ($usage['output_tokens'] ?? 0),
		);
	}
}
