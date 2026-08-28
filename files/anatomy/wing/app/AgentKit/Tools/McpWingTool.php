<?php

declare(strict_types=1);

namespace App\AgentKit\Tools;

use App\AgentKit\LLMClient\ToolSchema;
use GuzzleHttp\Client as HttpClient;
use GuzzleHttp\Exception\GuzzleException;

/**
 * MCP-style wrapper around Wing's REST API. Exposes a single tool the LLM
 * can call to issue GET/POST requests to /api/v1/* endpoints. Authorization
 * is via the agent's session bearer token (resolved from vault, scope=mcp-wing
 * or fallback wing-internal token at runtime).
 *
 * The tool is intentionally narrow: only Wing's own /api/v1/* surface, only
 * via the loopback URL. Anything broader belongs in a separate tool with
 * its own scope.
 */
final class McpWingTool implements ToolInterface
{
	private const BASE_URL = 'http://127.0.0.1:9000';
	private const MAX_RESPONSE_BYTES = 16_384;

	private string $bearerToken;

	public function __construct(
		private readonly HttpClient $http,
		?string $bearerToken = null,
	) {
		// Resolve at construct time so DI doesn't need a parameter binding.
		// CLI runs export WING_API_TOKEN directly; daemon mode picks it up from
		// the launchd plist environment block.
		$this->bearerToken = (string) ($bearerToken ?? getenv('WING_API_TOKEN') ?: '');
	}

	public function id(): string
	{
		return 'mcp-wing';
	}

	public function requiredScopes(): array
	{
		return ['mcp.tool_use', 'wing.read'];
	}

	public function schema(): ToolSchema
	{
		return new ToolSchema(
			name: 'mcp_wing',
			description: 'Issue a GET or POST against Wing /api/v1/*. Use for health probes, ' .
				'event queries, pulse-job lookups, system listings. Path must start with /api/v1/. ' .
				'Returns up to 16 KiB of the JSON response body verbatim.',
			inputSchema: [
				'type' => 'object',
				'required' => ['method', 'path'],
				'properties' => [
					'method' => [
						'type' => 'string',
						'enum' => ['GET', 'POST'],
					],
					'path' => [
						'type' => 'string',
						'description' => 'Path beginning with /api/v1/.',
					],
					'body' => [
						'type' => 'object',
						'description' => 'JSON body (POST only).',
					],
				],
			],
		);
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
		$method = strtoupper((string) ($input['method'] ?? 'GET'));
		$path = (string) ($input['path'] ?? '');
		$body = $input['body'] ?? null;

		if (!in_array($method, ['GET', 'POST'], true)) {
			return ToolResult::error("method must be GET or POST; got {$method}");
		}
		if (!str_starts_with($path, '/api/v1/')) {
			return ToolResult::error("path must start with /api/v1/; got {$path}");
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
			$response = $this->http->request($method, self::BASE_URL . $path, $opts);
		} catch (GuzzleException $exc) {
			return ToolResult::error('Wing API HTTP error: ' . $exc->getMessage());
		}

		$status = $response->getStatusCode();
		$payload = (string) $response->getBody();
		// mb_strcut, not substr: a byte cut mid-codepoint breaks UTF-8.
		if (strlen($payload) > self::MAX_RESPONSE_BYTES) {
			$payload = mb_strcut($payload, 0, self::MAX_RESPONSE_BYTES, 'UTF-8') . '…[truncated]';
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
