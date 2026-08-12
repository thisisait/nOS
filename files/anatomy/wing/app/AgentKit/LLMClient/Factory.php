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
 *   claude-*    → ClaudeCliAdapter (the local `claude` binary, no API key)
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
			// `claude-*` is the LOCAL CLI, not the API. Added 2026-08-11 because
			// AgentKit could not drive the only backend this estate has: the
			// nightly agents run on the operator's `claude` subscription through
			// pulse-run-agent.sh, and neither existing provider reaches it —
			// anthropic-* wants an API key nobody sets, openclaw-* wants a
			// gateway that was dead for weeks. That gap, not "two runtimes" in
			// the abstract, is why agent_sessions held 3 rows and
			// agent_iterations held 0.
			'claude'    => $this->buildClaudeCli($modelUri),
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

	/**
	 * `claude-sonnet` → the CLI with `--model sonnet`.
	 *
	 * NO CREDENTIAL PASSES THROUGH HERE, which makes this the one provider the
	 * factory's "only place that touches secrets" docblock does not describe:
	 * the CLI carries the operator's own session. Worth stating rather than
	 * leaving as an omission — it means an agent on this backend inherits the
	 * operator's identity and cannot be scoped down by a vault binding, and any
	 * per-agent isolation has to come from what the ceremony is allowed to call.
	 *
	 * AND THAT IDENTITY RUNS UNGATED: the adapter invokes the CLI with a
	 * hardcoded `--permission-mode bypassPermissions`, so anything the CLI's
	 * own internal tool loop decides to do, it does as the operator with no
	 * prompt in the way. That is the same posture `pulse-run-agent.sh` runs the
	 * nightly ceremonies under, and it is stated here because THIS note is
	 * where the identity consequences of this backend live: no vault scoping,
	 * no permission gate — the ceremony's own reach is the only boundary.
	 * Deliberately not configurable: a per-agent permission mode would be a
	 * capability toggled by data, and softer modes block on interactive
	 * prompts no daemon can answer.
	 */
	private function buildClaudeCli(string $modelUri): ClaudeCliAdapter
	{
		[, $model] = $this->splitUri($modelUri);
		$binary = getenv('NOS_CLAUDE_BIN') ?: 'claude';
		$timeout = (int) (getenv('NOS_CLAUDE_TIMEOUT_S') ?: 900);
		return new ClaudeCliAdapter($modelUri, $model, $binary, $timeout);
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
