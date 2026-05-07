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
		if ($method === 'POST' && $body !== null) {
			$opts['json'] = $body;
		}

		try {
			$response = $this->http->request($method, self::BASE_URL . $path, $opts);
		} catch (GuzzleException $exc) {
			return ToolResult::error('Wing API HTTP error: ' . $exc->getMessage());
		}

		$status = $response->getStatusCode();
		$payload = (string) $response->getBody();
		if (strlen($payload) > self::MAX_RESPONSE_BYTES) {
			$payload = substr($payload, 0, self::MAX_RESPONSE_BYTES) . '…[truncated]';
		}

		return new ToolResult(
			content: "HTTP {$status}\n" . $payload,
			isError: $status >= 400,
			metadata: ['status' => $status, 'method' => $method, 'path' => $path],
		);
	}
}
