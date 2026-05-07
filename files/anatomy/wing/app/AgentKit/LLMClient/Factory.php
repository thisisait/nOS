<?php

declare(strict_types=1);

namespace App\AgentKit\LLMClient;

use Anthropic\Client as AnthropicClient;
use App\AgentKit\Vault\CredentialResolver;
use GuzzleHttp\Client as HttpClient;

/**
 * Builds an LLMClientInterface from a model URI.
 *
 * URI scheme: `<provider>-<model-id>`. Provider determines adapter:
 *   anthropic-* → AnthropicAdapter (needs ANTHROPIC_API_KEY)
 *   openclaw-*  → OpenClawAdapter  (HTTP to OPENCLAW_BASE_URL)
 *   openai-*    → reserved (not yet implemented; throws)
 *   local-*     → reserved (not yet implemented; throws)
 *
 * The factory is the ONLY place that touches secrets — everywhere else
 * we pass the LLMClientInterface around. CredentialResolver feeds the
 * factory; if a vault has a credential bound to scope=anthropic-api
 * the factory pulls it from there, else falls back to env.
 */
final class Factory
{
	public function __construct(
		private readonly CredentialResolver $credentials,
	) {
	}

	public function fromUri(string $modelUri): LLMClientInterface
	{
		[$provider, ] = $this->splitUri($modelUri);
		return match ($provider) {
			'anthropic' => $this->buildAnthropic($modelUri),
			'openclaw'  => $this->buildOpenClaw($modelUri),
			default     => throw new \InvalidArgumentException(
				"LLM provider '{$provider}' not yet supported (URI: {$modelUri})"
			),
		};
	}

	/**
	 * @return array{0: string, 1: string}
	 */
	private function splitUri(string $modelUri): array
	{
		if (!preg_match('/^([a-z]+)-(.+)$/', $modelUri, $m)) {
			throw new \InvalidArgumentException("Invalid model URI: {$modelUri}");
		}
		return [$m[1], $m[2]];
	}

	private function buildAnthropic(string $modelUri): AnthropicAdapter
	{
		$apiKey = $this->credentials->resolve('anthropic-api')
			?? getenv('ANTHROPIC_API_KEY')
			?: '';
		if ($apiKey === '') {
			throw new \RuntimeException(
				'ANTHROPIC_API_KEY missing — set the env var or bind a credential ' .
				'with scope=anthropic-api to the agent vault.'
			);
		}
		$client = new AnthropicClient(apiKey: $apiKey);
		return new AnthropicAdapter($client, $modelUri);
	}

	private function buildOpenClaw(string $modelUri): OpenClawAdapter
	{
		$baseUrl = getenv('OPENCLAW_BASE_URL') ?: 'http://127.0.0.1:18789';
		$timeout = (float) (getenv('OPENCLAW_TIMEOUT') ?: 120);
		$http = new HttpClient([
			'http_errors' => true,
			'timeout' => $timeout,
		]);
		return new OpenClawAdapter($http, $modelUri, $baseUrl, $timeout);
	}
}
