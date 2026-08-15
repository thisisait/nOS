<?php

declare(strict_types=1);

namespace App\AgentKit\LLMClient;

use App\AgentKit\Agent;
use App\AgentKit\Vault\CredentialResolver;
use Symfony\Component\Yaml\Yaml;

/**
 * Resolves an agent's declared `model.backend` into a Binding — or refuses.
 *
 * THE SIX GATES, in the order they are checked (prose with the history in
 * state/llm-backends.yml; the data-side half is held offline by
 * tests/anatomy/test_a_binding_reads_the_register.py):
 *
 *   1. per-agent declaration (`model.backend`); absent → default backend
 *   2. the name must exist in the registry
 *   3. armed via NOS_ARMED_BACKENDS — declared-but-disarmed is NOT an error:
 *      the run proceeds on the default backend and the decision says so, so
 *      the Runner can emit `agent_binding_disarmed`. Committing an agent.yml
 *      must never half-arm a backend the operator has not flipped on.
 *   4. the agent's own gdpr.processors must name the backend's processor —
 *      a routing the register does not declare REFUSES (the declaration is
 *      wrong, not the wire; running on the default instead would execute a
 *      ceremony whose compliance record is known-false)
 *   5. runner_status=deferred refuses: inspektor's `processors: []` is
 *      truthful only while it never runs, and its record says so
 *   6. the tier must have a model id: opus maps to null by ruling 1, and an
 *      armed backend with an empty model-id env refuses rather than sending
 *      a blank model
 *
 * The registry is read from state/llm-backends.yml under NOS_REPO_ROOT (the
 * env wing.plist already carries); no registry file → no non-default backend
 * can resolve, which is the fail-closed shape everything here inherits.
 */
final class BindingResolver
{
	public function __construct(
		private readonly CredentialResolver $credentials,
		private readonly ?string $registryPath = null,
	) {
	}

	public function resolve(Agent $agent): BindingDecision
	{
		$declared = $agent->backendName;
		if ($declared === null) {
			return BindingDecision::default();
		}

		$backends = $this->registry();
		if (!isset($backends[$declared])) {
			throw new BindingRefused(
				"agent '{$agent->name}' declares backend '{$declared}', which "
				. 'state/llm-backends.yml does not list. A backend joins the '
				. 'registry first (with its processor_match), then agents may '
				. 'name it.'
			);
		}
		$spec = (array) $backends[$declared];
		if (($spec['default'] ?? false) === true) {
			// Naming the default explicitly is a no-op, not an error.
			return BindingDecision::default();
		}

		// Gate 5 — a binding is an arming, and a deferred agent's Article-30
		// record is truthful only because it never runs.
		$status = strtolower((string) ($agent->metadata['runner_status'] ?? ''));
		if ($status === 'deferred') {
			throw new BindingRefused(
				"agent '{$agent->name}' is runner_status=deferred; its register "
				. "entry (processors: []) is truthful only while it never runs. "
				. 'Rewrite the gdpr block and the runner_status together before '
				. 'binding it anywhere.'
			);
		}

		// Gate 4 — the register is the INPUT to routing, never outrun by it.
		$match = (string) ($spec['processor_match'] ?? '');
		$named = false;
		foreach ((array) ($agent->gdpr['processors'] ?? []) as $p) {
			if ($match !== '' && str_contains((string) (((array) $p)['name'] ?? ''), $match)) {
				$named = true;
				break;
			}
		}
		if (!$named) {
			throw new BindingRefused(
				"agent '{$agent->name}' routes to '{$declared}' but its own "
				. "gdpr.processors never names '{$match}'. The Article-30 "
				. 'register would be complete, well-formed, and false — write '
				. 'the processor entry first.'
			);
		}

		// Gate 6 — the TIER WORD in the primary URI's tail, for both bindable
		// providers: `claude-sonnet` names it outright, and every Anthropic
		// API model id carries it (`anthropic-claude-opus-4-7`). Ruling 1
		// maps opus to null in the registry, so an opus-tier agent refuses
		// here REGARDLESS of which adapter would have served it — the
		// carve-out follows the tier, not the provider. A tail with no tier
		// word refuses too: a model the tiers cannot name cannot be remapped
		// by a tier table, and guessing would route it silently.
		$tail = substr($agent->modelPrimaryUri, (int) strpos($agent->modelPrimaryUri, '-') + 1);
		$tier = preg_match('/\b(haiku|sonnet|opus)\b/', $tail, $m) ? $m[1] : $tail;
		$modelEnvByTier = (array) ($spec['model_env'] ?? []);
		if (!array_key_exists($tier, $modelEnvByTier) || $modelEnvByTier[$tier] === null) {
			throw new BindingRefused(
				"agent '{$agent->name}' (tier '{$tier}', from '{$agent->modelPrimaryUri}') "
				. "has no model mapping on backend '{$declared}' — ruling 1 keeps "
				. 'opus-tier ceremonies on the default backend, and a tail without '
				. 'a tier word cannot be remapped by a tier table.'
			);
		}

		// Gate 3 — armed? Not an error when it is not: prepared, not armed.
		$armed = in_array(
			$declared,
			preg_split('/\s+/', trim((string) getenv('NOS_ARMED_BACKENDS')), -1, PREG_SPLIT_NO_EMPTY) ?: [],
			true,
		);
		if (!$armed) {
			return BindingDecision::disarmed($declared);
		}

		$modelId = (string) getenv((string) $modelEnvByTier[$tier]);
		if ($modelId === '') {
			throw new BindingRefused(
				"backend '{$declared}' is armed but {$modelEnvByTier[$tier]} is "
				. 'empty — the operator re-decides the tier pins consciously '
				. '(docs/minimax-groundwork.md ruling 3); refusing rather than '
				. 'sending a blank model id.'
			);
		}

		$token = $this->credentials->dereferenceRef((string) ($spec['auth_secret'] ?? ''));
		if ($token === null || $token === '') {
			throw new BindingRefused(
				"backend '{$declared}' is armed but its auth_secret "
				. "'{$spec['auth_secret']}' resolves to nothing — paste the key "
				. 'into credentials.yml and converge before arming.'
			);
		}

		return BindingDecision::bound(new Binding(
			name: $declared,
			baseUrl: (string) $spec['base_url'],
			authToken: $token,
			modelId: $modelId,
		));
	}

	/**
	 * @return array<string, mixed>
	 */
	private function registry(): array
	{
		$path = $this->registryPath
			?? ((getenv('NOS_REPO_ROOT') ?: '') . '/state/llm-backends.yml');
		if (!is_file($path)) {
			return [];
		}
		$doc = Yaml::parseFile($path);
		return is_array($doc) ? (array) ($doc['backends'] ?? []) : [];
	}
}

/**
 * What the resolver decided, in a shape the Runner can audit.
 *
 * Three states, and the middle one is the point: `declaredDisarmed` is the
 * name of a backend the agent asked for and the operator has not armed — the
 * run proceeds on the default backend, and the Runner emits
 * `agent_binding_disarmed` so the declared-but-dormant state is visible in
 * the audit trail instead of silently indistinguishable from "never asked".
 */
final class BindingDecision
{
	private function __construct(
		public readonly ?Binding $binding,
		public readonly ?string $declaredDisarmed,
	) {
	}

	public static function default(): self
	{
		return new self(null, null);
	}

	public static function disarmed(string $declared): self
	{
		return new self(null, $declared);
	}

	public static function bound(Binding $binding): self
	{
		return new self($binding, null);
	}

	public function backendName(): string
	{
		return $this->binding?->name ?? 'anthropic';
	}
}
