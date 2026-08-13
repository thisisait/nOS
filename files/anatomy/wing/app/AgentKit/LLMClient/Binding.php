<?php

declare(strict_types=1);

namespace App\AgentKit\LLMClient;

/**
 * A resolved backend binding — where a `claude-*` run's traffic is pointed.
 *
 * A BACKEND IS NOT A PROVIDER (state/llm-backends.yml carries the argument in
 * full): the genome's provider enum names which adapter runs, fail-closed and
 * adapter-first; this names the env contract the `claude` CLI honours
 * (ANTHROPIC_BASE_URL / ANTHROPIC_AUTH_TOKEN / ANTHROPIC_MODEL). A Binding
 * only ever reaches ClaudeCliAdapter — Factory throws if one is offered to
 * any other provider, because no other adapter speaks this contract.
 *
 * `$authToken` is the RESOLVED secret, present here for exactly the adapter
 * spawn and nowhere else — same lifetime discipline as CredentialResolver's
 * function locals: never logged, never serialised, never stored back. The
 * value object is readonly and carries no toString/jsonSerialize on purpose.
 *
 * `$modelId` is already tier-resolved (the resolver mapped this agent's
 * haiku/sonnet tier through the registry's model_env), so the adapter has no
 * mapping left to do — it exports the id and, per ruling 3, does NOT pass
 * `--model`, because the CLI's flag outranks the env and would silently undo
 * the remap.
 */
final class Binding
{
	public function __construct(
		public readonly string $name,
		public readonly string $baseUrl,
		public readonly string $authToken,
		public readonly string $modelId,
	) {
	}
}
