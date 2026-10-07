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
 * state/habitat/llm-backends.yml; the data-side half is held offline by
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
 * The registry is read from state/habitat/llm-backends.yml under NOS_REPO_ROOT (the
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
		return $this->decide($agent, $agent->backendName, $agent->modelPrimaryUri);
	}

	/**
	 * The fallback, held to the same gates as the primary — and it never degrades.
	 * A disarmed or default fallback would answer UNBOUND from the default backend,
	 * a party the agent's record may not name (Runner::serveFallback, 2026-08-16).
	 */
	public function resolveFallback(Agent $agent): Binding
	{
		$declared = (string) $agent->fallbackBackendName;
		$d = $this->decide($agent, $declared, (string) $agent->modelFallbackUri);
		if ($d->binding === null) {
			throw new BindingRefused(
				"agent '{$agent->name}': fallback backend '{$declared}' is "
				. ($d->declaredDisarmed !== null ? 'not armed' : 'the default')
				. ' — a fallback is served bound or not at all.'
			);
		}
		return $d->binding;
	}

	private function decide(Agent $agent, ?string $declared, string $uri): BindingDecision
	{
		if ($declared === null) {
			return BindingDecision::default();
		}

		$backends = self::readRegistry($this->registryPath);
		if (!isset($backends[$declared])) {
			throw new BindingRefused(
				"agent '{$agent->name}' declares backend '{$declared}', which "
				. 'state/habitat/llm-backends.yml does not list. A backend joins the '
				. 'registry first (with its processor_match), then agents may '
				. 'name it.'
			);
		}
		$spec = (array) $backends[$declared];
		if (($spec['default'] ?? false) === true) {
			// Naming the default explicitly is a no-op, not an error.
			return BindingDecision::default();
		}

		// Gate 7 (2026-08-16, the Mistral-readiness gate) — the adapter must
		// SPEAK the backend's wire protocol. Both current providers speak
		// `anthropic` (the SDK natively; the CLI via its vendor's env
		// contract), so today this refuses nothing — it exists so that the
		// day an `openai`-protocol backend row lands (Mistral), an
		// anthropic-* primary bound to it refuses at session open instead of
		// dying at the endpoint with a shape error nothing classifies.
		$provider = substr($uri, 0, (int) strpos($uri, '-'));
		$speaks = ['claude' => 'anthropic', 'anthropic' => 'anthropic', 'openai' => 'openai', 'openclaw' => 'openai'];
		$protocol = (string) ($spec['protocol'] ?? 'anthropic');
		if (($speaks[$provider] ?? null) !== $protocol) {
			throw new BindingRefused(
				"agent '{$agent->name}': provider '{$provider}' does not speak "
				. "backend '{$declared}'s wire protocol '{$protocol}'. The "
				. 'binding would send one protocol\'s requests to the other\'s '
				. 'endpoint; pick a primary whose adapter speaks it.'
			);
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

		// Gates 4 + 8 (record half) — shared with AgentLoader's fallback check.
		self::assertRecordCovers($agent->name, $agent->gdpr, $declared, $spec);
		$euOnly = (($agent->gdpr['transfers_outside_eu'] ?? null) === false)
			&& ((array) ($agent->gdpr['processors'] ?? []) !== []);

		// Gate 6 — the TIER WORD in the primary URI's tail, for both bindable
		// providers: `claude-sonnet` names it outright, and every Anthropic
		// API model id carries it (`anthropic-claude-opus-4-7`). Ruling 1
		// maps opus to null in the registry, so an opus-tier agent refuses
		// here REGARDLESS of which adapter would have served it — the
		// carve-out follows the tier, not the provider. A tail with no tier
		// word refuses too: a model the tiers cannot name cannot be remapped
		// by a tier table, and guessing would route it silently.
		//
		// `vision` (2026-09-20) joined the word list for the D1 invoice-vision
		// path: it names an INPUT CAPABILITY, not a cost/quality rung, but the
		// same tier mechanism carries it — a backend either maps `vision` in
		// its model_env or the agent refuses here, same as any other tier.
		$tail = substr($uri, (int) strpos($uri, '-') + 1);
		$tier = preg_match('/\b(haiku|sonnet|opus|vision)\b/', $tail, $m) ? $m[1] : $tail;
		$modelEnvByTier = (array) ($spec['model_env'] ?? []);
		if (!array_key_exists($tier, $modelEnvByTier) || $modelEnvByTier[$tier] === null) {
			throw new BindingRefused(
				"agent '{$agent->name}' (tier '{$tier}', from '{$uri}') "
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
			if ($euOnly) {
				// The no-degrade half of gate 8: the default backend is not
				// EU-resident, and this agent's record says the data does not
				// leave. Refusing IS the residency property — see the gate 8
				// comment above.
				throw new BindingRefused(
					"agent '{$agent->name}' declares transfers_outside_eu: "
					. "false and its backend '{$declared}' is not armed. "
					. 'Degrading to the default would ship the data outside '
					. 'the EU and falsify the record — arm the backend or do '
					. 'not run this agent.'
				);
			}
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

		// Gate 7 — a key, unless there is nobody to show it to.
		//
		// A LOCAL backend has no auth and inventing one would be a secret that
		// is not a secret: `auth_secret: <anything>` would have to resolve, so
		// the operator would paste a placeholder into credentials.yml and the
		// vault would carry a lie. `local: true` says the model runs on this
		// machine; the empty token is then the honest value, not a missing one.
		//
		// It is also the only backend that can satisfy gate 8's no-degrade
		// rule: an agent declaring `transfers_outside_eu: false` cannot route
		// to any cloud row here, and nothing leaves a machine that never opens
		// a socket. That falls out of the existing gates rather than needing a
		// new one.
		//
		// A local row MAY still name a secret when the on-host service itself
		// demands one (OpenClaw's gateway token, 2026-10-01): then it must resolve.
		$isLocal = ($spec['local'] ?? false) === true;
		$ref = (string) ($spec['auth_secret'] ?? '');
		$token = $ref === '' ? '' : (string) ($this->credentials->dereferenceRef($ref) ?? '');
		if ($token === '' && (!$isLocal || $ref !== '')) {
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
	 * Does the agent's own Article-30 record cover routing to this backend?
	 * Gate 4 (the processor is named) and gate 8's record half (an EU-only
	 * record never routes to a non-EU row). Static: the loader holds a
	 * declared fallback to it before any session exists.
	 *
	 * @param array<string, mixed> $gdpr
	 * @param array<string, mixed> $spec
	 */
	public static function assertRecordCovers(string $agentName, array $gdpr, string $declared, array $spec): void
	{
		// Gate 4 — the register is the INPUT to routing, never outrun by it.
		$match = (string) ($spec['processor_match'] ?? '');
		$named = false;
		foreach ((array) ($gdpr['processors'] ?? []) as $p) {
			if ($match !== '' && str_contains((string) (((array) $p)['name'] ?? ''), $match)) {
				$named = true;
				break;
			}
		}
		if (!$named) {
			throw new BindingRefused(
				"agent '{$agentName}' routes to '{$declared}' but its own "
				. "gdpr.processors never names '{$match}'. The Article-30 "
				. 'register would be complete, well-formed, and false — write '
				. 'the processor entry first.'
			);
		}

		// Gate 8 — NO-DEGRADE, derived from the register rather than a knob
		// (2026-08-16, the gov-ready half). An agent whose own Article-30
		// record declares `transfers_outside_eu: false` while naming
		// processors has committed its data to staying in the EU; that
		// commitment is the MECHANISM here, not a parallel setting:
		//   * routing it to a non-EU backend refuses — the record is false
		//     the moment the first prompt leaves, and running elsewhere
		//     instead would falsify it from the other side;
		//   * degrading to the (non-EU) default when the binding is disarmed
		//     refuses too, below — for every other agent disarmed means "the
		//     default serves", for this one it means "no run". EU residency
		//     that evaporates under a config flag is a claim, not a property.
		$euOnly = (($gdpr['transfers_outside_eu'] ?? null) === false)
			&& ((array) ($gdpr['processors'] ?? []) !== []);
		$backendIsEu = ((($spec['residency'] ?? []))['eu'] ?? false) === true;
		if ($euOnly && !$backendIsEu) {
			throw new BindingRefused(
				"agent '{$agentName}' declares transfers_outside_eu: false "
				. "but routes to '{$declared}', which is not EU-resident "
				. '(state/habitat/llm-backends.yml residency.eu). One of the two is '
				. 'wrong; refusing until they agree.'
			);
		}
	}

	/**
	 * @return array<string, mixed>
	 */
	public static function readRegistry(?string $path = null): array
	{
		if ($path === null) {
			$root = (getenv('NOS_REPO_ROOT') ?: '');
			$path = $root . '/state/habitat/llm-backends.yml';
			// Compat: a checkout older than this Wing still has the old path.
			// Drop after every host has run a `--tags wing` converge.
			if (!is_file($path)) {
				$path = $root . '/state/llm-backends.yml';
			}
		}
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
