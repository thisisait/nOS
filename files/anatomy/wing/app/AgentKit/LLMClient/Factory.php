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
 *   openai-*    → OpenAiCompatAdapter (bound only: a registry row names the endpoint)
 *   openclaw-*  → OpenAiCompatAdapter (bound only: the gateway's /v1/chat/completions)
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

	/**
	 * @param ?Binding $binding backend binding (state/habitat/llm-backends.yml),
	 *        resolved by BindingResolver. TWO providers accept one, each by
	 *        its own mechanism — and the asymmetry is the 2026-08-15 spine
	 *        redirect ("primarily through the classic API"):
	 *          `anthropic` — the PRIMARY bindable path. The SDK client is
	 *          rebuilt with the binding's baseUrl + bearer, and because
	 *          AgentKit's Runner drives the tool loop against this adapter,
	 *          a bound run keeps tools — the structural dissolution of the
	 *          CLI adapter's tools refusal.
	 *          `claude` — the env contract the CLI honours; tool-less
	 *          ceremonies only, by that adapter's own refusal.
	 *        `openai` / `openclaw` — OpenAiCompatAdapter, bound only. OpenClaw
	 *        2026.7.1 answers 404 on /v1/messages; its gateway's OpenAI surface
	 *        is the one it actually serves (2026-10-01).
	 */
	public function fromUri(string $modelUri, ?Binding $binding = null): LLMClientInterface
	{
		[$provider, ] = $this->splitUri($modelUri);
		if ($binding !== null && !in_array($provider, ['claude', 'anthropic', 'openai', 'openclaw'], true)) {
			throw new \InvalidArgumentException(
				"backend binding '{$binding->name}' offered to provider "
				. "'{$provider}', which speaks neither the ANTHROPIC_* env "
				. 'contract nor the SDK base-url mechanism. Accepting it here '
				. 'would drop it silently.'
			);
		}
		return match ($provider) {
			'anthropic' => $this->buildAnthropic($modelUri, $binding),
			// `openai-*` names a PROTOCOL, not a vendor default: this estate has
			// no default OpenAI endpoint, so the provider exists ONLY bound —
			// the registry row (mistral-eu, a local server) is what makes it a
			// place requests can go. Adapter-first rule satisfied 2026-08-16:
			// this arm and the genome enum member land in the same commit.
			'openai'    => $this->buildOpenAiCompat($modelUri, $binding),
			// `claude-*` is the LOCAL CLI, not the API. Added 2026-08-11 because
			// AgentKit could not drive the only backend this estate has: the
			// nightly agents run on the operator's `claude` subscription through
			// pulse-run-agent.sh, and neither existing provider reaches it —
			// anthropic-* wants an API key nobody sets, openclaw-* wants a
			// gateway that was dead for weeks. That gap, not "two runtimes" in
			// the abstract, is why agent_sessions held 3 rows and
			// agent_iterations held 0.
			'claude'    => $this->buildClaudeCli($modelUri, $binding),
			'openclaw'  => $this->buildOpenAiCompat($modelUri, $binding),
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
	private function buildClaudeCli(string $modelUri, ?Binding $binding = null): ClaudeCliAdapter
	{
		[, $model] = $this->splitUri($modelUri);
		// agents_separate_user on: NOS_CLAUDE_BIN is the nos-agent wrapper, whose launcher
		// drops bypassPermissions for dontAsk + an allow-list (pazny.mac.agent_user).
		$binary = getenv('NOS_CLAUDE_BIN') ?: 'claude';
		$timeout = (int) (getenv('NOS_CLAUDE_TIMEOUT_S') ?: 900);
		return new ClaudeCliAdapter($modelUri, $model, $binary, $timeout, $binding);
	}

	private function buildAnthropic(string $modelUri, ?Binding $binding = null): AnthropicAdapter
	{
		if ($binding !== null) {
			// The bound path authenticates with the BINDING's bearer against
			// the BINDING's endpoint — never with ANTHROPIC_API_KEY, which
			// belongs to a different party. `authToken` is the SDK's
			// Authorization-Bearer form, the same credential shape the CLI's
			// ANTHROPIC_AUTH_TOKEN carries; MiniMax's Anthropic-compatible
			// endpoint takes exactly that. The token came out of the resolver
			// at session open (nos:… secret_ref) and lives in the client for
			// the session — the same lifetime the unbound apiKey has.
			$client = new AnthropicClient(
				authToken: $binding->authToken,
				baseUrl: $binding->baseUrl,
			);
			return new AnthropicAdapter($client, $modelUri, $binding);
		}
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

	private function buildOpenAiCompat(string $modelUri, ?Binding $binding): OpenAiCompatAdapter
	{
		if ($binding === null) {
			throw new \RuntimeException(
				"{$modelUri}: openai-/openclaw-* name a protocol, not a vendor default "
				. '— this estate has no default endpoint. Give the agent a model.backend '
				. '(or fallback_backend) whose registry row speaks protocol openai.'
			);
		}
		$http = new HttpClient([
			'http_errors' => true,
			// Same per-request ceiling the Anthropic SDK defaults to; the
			// session wall-clock in Runner bounds the sum.
			'timeout' => (float) (getenv('NOS_OPENAI_COMPAT_TIMEOUT_S') ?: 600),
		]);
		return new OpenAiCompatAdapter($http, $modelUri, $binding);
	}
}
