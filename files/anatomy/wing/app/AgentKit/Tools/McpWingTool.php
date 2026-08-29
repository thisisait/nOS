<?php

declare(strict_types=1);

namespace App\AgentKit\Tools;

use GuzzleHttp\Client as HttpClient;
use GuzzleHttp\Exception\GuzzleException;

/**
 * Shared transport for the two Wing MCP tools. Abstract: never registered.
 *
 * Until 2026-08-28 one tool carried GET and POST behind a single `wing.read`
 * scope, so every agent that could read the estate could also write to it —
 * a scope that does not name a verb cannot refuse it. Each subclass names
 * exactly one verb, and the write plane names its routes too.
 */
abstract class McpWingTool implements ToolInterface
{
	protected const BASE_URL = 'http://127.0.0.1:9000';
	protected const MAX_RESPONSE_BYTES = 16_384;

	private string $bearerToken;

	public function __construct(
		private readonly HttpClient $http,
		?string $bearerToken = null,
	) {
		// Resolve at construct time so DI doesn't need a parameter binding.
		//
		// NOS_AGENT_WING_TOKEN FIRST — it is the running agent's OWN principal,
		// so `events.actor_id` names the agent that ran. WING_API_TOKEN is the
		// operator's admin bearer, and tools/run-agent.sh exports the whole
		// daemon environment, which means a CLI run silently borrows it and
		// every event the agent writes is attributed to 'ansible-provisioned'.
		// The fallback stays so a pre-converge estate keeps working — but it
		// says so, because a wrong-but-plausible actor is the expensive kind.
		if ($bearerToken === null) {
			$bearerToken = getenv('NOS_AGENT_WING_TOKEN') ?: null;
			if ($bearerToken === null) {
				$bearerToken = getenv('WING_API_TOKEN') ?: '';
				error_log(
					'[mcp-wing] WARN: no NOS_AGENT_WING_TOKEN — falling back to the '
					. 'operator WING_API_TOKEN. Wing will attribute this run to that '
					. 'token, not to this agent.'
				);
			}
		}
		$this->bearerToken = (string) $bearerToken;
	}

	/** The one HTTP verb this tool's scope names. */
	abstract protected function verb(): string;

	/**
	 * Routes this tool may reach — exact match on the path with the query
	 * stripped. Empty means the whole /api/v1/ surface.
	 *
	 * @return array<int, string>
	 */
	protected function allowedPaths(): array
	{
		return [];
	}

	/** The live route table, derived from the router the request just missed. */
	private static function routes(): string
	{
		static $cached = null;
		if ($cached !== null) {
			return $cached;
		}
		$router = __DIR__ . '/../../Core/RouterFactory.php';
		if (!is_readable($router)) {
			// Fail soft and SAY so — a silently empty hint would read as
			// "there are no other routes", which is the worse wrong answer.
			return $cached = '  (route table unreadable at ' . $router . ')';
		}
		preg_match_all("/addRoute\('(api\/v1[^']*)'/", (string) file_get_contents($router), $m);
		$paths = array_unique($m[1] ?? []);
		sort($paths);
		return $cached = '  /' . implode("\n  /", $paths);
	}

	public function execute(array $input, ToolContext $context): ToolResult
	{
		$method = strtoupper((string) ($input['method'] ?? $this->verb()));
		$path = (string) ($input['path'] ?? '');
		$body = $input['body'] ?? null;

		if ($method !== $this->verb()) {
			return ToolResult::error(
				"{$this->id()} only does {$this->verb()}; got {$method}. Call the tool "
				. 'whose scope names that verb — this one cannot be talked into it.',
				['refused_reason' => 'verb_not_in_scope', 'method' => $method],
			);
		}
		if (!str_starts_with($path, '/api/v1/')) {
			return ToolResult::error("path must start with /api/v1/; got {$path}");
		}

		$route = explode('?', $path, 2)[0];
		$granted = $this->allowedPaths();
		if ($granted !== [] && !in_array($route, $granted, true)) {
			return ToolResult::error(
				"{$this->id()} is not granted {$route}. Granted: " . implode(', ', $granted),
				['refused_reason' => 'route_not_granted', 'path' => $route],
			);
		}

		$opts = [
			'headers' => [
				'Accept' => 'application/json',
				'Authorization' => 'Bearer ' . $this->bearerToken,
				'X-AgentKit-Session' => $context->sessionUuid,
				'X-AgentKit-Trace' => $context->traceId,
			],
			'timeout' => 10,
			'http_errors' => false,
		];
		if ($method === 'POST') {
			// Attribution is the TOOL's job, not the model's. An agent-authored
			// events POST that omits source / actor_action_id used to land as
			// an orphan row (event 377830, 2026-08-29: conductor_report with
			// every attribution column empty) and the promise that one
			// `SELECT WHERE actor_action_id=?` reconstructs a run broke for
			// exactly the reports that matter. Default — never overwrite —
			// from the context this call already carries.
			// Gate: test_agent_filed_events_carry_attribution.py.
			if ($route === '/api/v1/events' && is_array($body)) {
				if (($body['actor_action_id'] ?? '') === '') {
					$body['actor_action_id'] = $context->sessionUuid;
				}
				if (($body['actor_id'] ?? '') === '') {
					$body['actor_id'] = $context->actorId;
				}
				if (($body['source'] ?? '') === '') {
					// 'agent:nos-conductor' → 'conductor', the spelling the
					// pulse-run reports already use.
					$body['source'] = preg_replace('/^(agent:)?(nos-)?/', '', $context->actorId) ?: $context->actorId;
				}
			}
			// Wing signs the RAW body (EventsPresenter::checkHmac), so encode
			// once and send that exact string — Guzzle's `json` would re-encode.
			$raw = json_encode($body ?? new \stdClass);
			$ts = (string) time();
			$opts['body'] = $raw;
			$opts['headers']['Content-Type'] = 'application/json';
			$opts['headers']['X-Wing-Timestamp'] = $ts;
			$opts['headers']['X-Wing-Signature'] = hash_hmac(
				'sha256',
				$ts . '.' . $raw,
				(string) (getenv('WING_EVENTS_HMAC_SECRET') ?: ''),
			);
		}

		try {
			$response = $this->http->request($method, static::BASE_URL . $path, $opts);
		} catch (GuzzleException $exc) {
			return ToolResult::error('Wing API HTTP error: ' . $exc->getMessage());
		}

		$status = $response->getStatusCode();
		$payload = (string) $response->getBody();
		// mb_strcut, not substr: a byte cut mid-codepoint breaks UTF-8.
		if (strlen($payload) > static::MAX_RESPONSE_BYTES) {
			$payload = mb_strcut($payload, 0, static::MAX_RESPONSE_BYTES, 'UTF-8') . '…[truncated]';
		}

		// A 404 is the model guessing a plausible path out of this tool's prose
		// description — it invented /api/v1/systems and /api/v1/health, then gave
		// up (surveyor, 2026-08-28). Answer with the routes that exist, read from
		// the router rather than restated here, so the hint cannot drift from it.
		if ($status === 404) {
			$payload .= "\n\nThat path is not routed. Routes that exist:\n" . self::routes();
		}

		return new ToolResult(
			content: "HTTP {$status}\n" . $payload,
			isError: $status >= 400,
			metadata: ['status' => $status, 'method' => $method, 'path' => $path],
		);
	}
}
