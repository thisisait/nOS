<?php

declare(strict_types=1);

namespace App\AgentKit\Webhook;

use App\AgentKit\Agent;
use App\AgentKit\SubscriptionSpec;
use App\Model\AgentSubscriptionRepository;

/**
 * Per-agent webhook auto-fan-out registrar (post-A14).
 *
 * Walks an Agent's `subscribe:` block and registers each entry as a row in
 * agent_subscriptions whose URL points back at the Wing-internal operator-
 * trigger endpoint, scoped to that agent. WebhookDispatcher::fire() then
 * iterates the row at every event with a matching event_type, applies the
 * declared filter, and POSTs.
 *
 * Idempotency: registration is keyed on the rendered URL so a reconverge
 * (or a second run of AgentLoader::load()) does NOT add duplicate rows.
 *
 * Cutover note: the URL targets `POST /api/v1/agents/<name>/sessions`
 * which is the operator-trigger endpoint that the parallel B-UI worker
 * is landing in the same milestone batch. Until that endpoint exists,
 * WebhookDispatcher will get a non-2xx response on fire and the auto-
 * disable counter will tick. The dispatcher tolerates the 404 path
 * (logs + continues, retries 3 times before counting one failure) so
 * we don't crash the producing session — but operators running with
 * subscribe: blocks before the operator-trigger endpoint ships will
 * see auto-disable kick in eventually. Document the order-of-merge
 * in your release notes.
 *
 * `signing_secret` is provisioned per-row from random_bytes(32). Wing-
 * internal callers won't actually verify it (they trust the localhost
 * loopback), but the column is NOT NULL and the column carrying it is
 * the same shape external receivers expect, so we generate one anyway.
 */
final class SubscriptionRegistrar
{
	/**
	 * Sentinel substring that marks a subscription row as agent-owned.
	 * Used by isInternalAgentSubscription() so the dispatcher can tell
	 * an internal fan-out URL from an operator-registered external one
	 * even after the URL has been mutated.
	 *
	 * @internal
	 */
	public const INTERNAL_URL_MARKER = '/api/v1/agents/';

	public function __construct(
		private readonly AgentSubscriptionRepository $subscriptions,
		private readonly string $wingBaseUrl,
	) {
	}

	/**
	 * Idempotently register every subscribe: entry for an agent. Returns
	 * the row IDs (already-existing OR freshly-created) in input order.
	 *
	 * @return array<int, int>
	 */
	public function registerForAgent(Agent $agent): array
	{
		$ids = [];
		foreach ($agent->subscriptions as $spec) {
			$ids[] = $this->registerOne($agent->name, $spec);
		}
		return $ids;
	}

	/**
	 * Compose the Wing-internal operator-trigger URL for an agent. Pulled
	 * out of registerOne() so tests can pin the exact shape without a DB.
	 */
	public function urlForAgent(string $agentName): string
	{
		// Sanitise: agent name pattern is locked by AgentLoader::validateName,
		// so we can interpolate directly. The URL still goes through curl in
		// the dispatcher, which URL-encodes path segments on its own.
		return rtrim($this->wingBaseUrl, '/') . self::INTERNAL_URL_MARKER
			. $agentName . '/sessions';
	}

	/**
	 * URL convention: an agent-owned (internal) subscription embeds the
	 * operator-trigger endpoint shape. WebhookDispatcher uses this for
	 * the self-loop guard: if the upstream event was produced by the
	 * SAME agent the subscription targets, we refuse to fan out.
	 */
	public static function isInternalAgentSubscription(string $url): bool
	{
		return str_contains($url, self::INTERNAL_URL_MARKER);
	}

	/**
	 * Extract the agent name from an internal-fan-out URL. Returns null
	 * if the URL is not an internal subscription URL or the segment is
	 * malformed. Used by WebhookDispatcher's self-loop guard.
	 */
	public static function agentNameFromInternalUrl(string $url): ?string
	{
		if (!self::isInternalAgentSubscription($url)) {
			return null;
		}
		$pos = strpos($url, self::INTERNAL_URL_MARKER);
		if ($pos === false) {
			return null;
		}
		$tail = substr($url, $pos + strlen(self::INTERNAL_URL_MARKER));
		// Tail looks like `<name>/sessions` (or `<name>/sessions?query` etc.)
		$slash = strpos($tail, '/');
		if ($slash === false || $slash === 0) {
			return null;
		}
		return substr($tail, 0, $slash);
	}

	private function registerOne(string $agentName, SubscriptionSpec $spec): int
	{
		$url = $this->urlForAgent($agentName);
		$existing = $this->subscriptions->findIdByUrl($url);
		if ($existing !== null) {
			// Already registered. Idempotent — DO NOT overwrite event_types
			// or signing_secret. Operator may have re-keyed an existing
			// subscription, and re-running AgentLoader should not undo that.
			return $existing;
		}
		$secret = 'whsec_' . bin2hex(random_bytes(32));
		return $this->subscriptions->create($url, [$spec->eventType], $secret);
	}
}
