<?php

declare(strict_types=1);

namespace App\AgentKit\Tools;

use App\AgentKit\LLMClient\ToolSchema;
use GuzzleHttp\Client as HttpClient;
use GuzzleHttp\Exception\GuzzleException;

/**
 * MCP-style wrapper around Bone (FastAPI) — local agent gateway. Identical
 * shape to McpWingTool but targets Bone's /api/* surface (events ingest +
 * health). Scope: bone.read + mcp.tool_use.
 */
final class McpBoneTool implements ToolInterface
{
	private const BASE_URL = 'http://127.0.0.1:8099';
	private const MAX_RESPONSE_BYTES = 16_384;

	private readonly string $bearerToken;


	public function __construct(
		private readonly HttpClient $http,
		?string $bearerToken = null,
	) {
		// The agent's OWN Authentik token, minted per --agent by
		// tools/run-agent.sh (the CLI path has always exported this spelling).
		// Without it this tool sent NO Authorization header at all and every
		// Bone endpoint behind require_scope() answered 401 — measured on the
		// first bound night, docs/plans/rsi-research/07-first-bound-night.md §4.
		// Absent is announced, never silent: a 401 that looks like a broken
		// endpoint costs a whole ceremony to diagnose.
		if ($bearerToken === null) {
			$bearerToken = getenv('NOS_AUTHENTIK_TOKEN') ?: '';
			if ($bearerToken === '') {
				error_log(
					'[mcp-bone] WARN: no NOS_AUTHENTIK_TOKEN — this run presents no '
					. 'principal to Bone, so every scoped endpoint will answer 401.'
				);
			}
		}
		$this->bearerToken = $bearerToken;
	}

	public function id(): string
	{
		return 'mcp-bone';
	}

	public function requiredScopes(): array
	{
		return ['mcp.tool_use', 'bone.read'];
	}

	public function schema(): ToolSchema
	{
		return new ToolSchema(
			name: 'mcp_bone',
			description: 'Issue a GET against Bone /api/*. Read-only — Bone ingest happens ' .
				'via wing /api/v1/events HMAC, not this tool. Returns up to 16 KiB of body.',
			inputSchema: [
				'type' => 'object',
				'required' => ['path'],
				'properties' => [
					'path' => [
						'type' => 'string',
						'description' => 'Path beginning with /api/.',
					],
				],
			],
		);
	}

	public function execute(array $input, ToolContext $context): ToolResult
	{
		// A `method` this tool does not do was silently served as a GET and
		// answered HTTP 200 — the model asked to write and was told it worked.
		$method = strtoupper((string) ($input['method'] ?? 'GET'));
		if ($method !== 'GET') {
			return ToolResult::error(
				"mcp-bone only does GET; got {$method}. It has no write plane.",
				['refused_reason' => 'verb_not_in_scope', 'method' => $method],
			);
		}

		$path = (string) ($input['path'] ?? '');
		if (!str_starts_with($path, '/api/')) {
			return ToolResult::error("path must start with /api/; got {$path}");
		}

		try {
			$headers = [
				'Accept' => 'application/json',
				'X-AgentKit-Session' => $context->sessionUuid,
				'X-AgentKit-Trace' => $context->traceId,
			];
			if ($this->bearerToken !== '') {
				$headers['Authorization'] = 'Bearer ' . $this->bearerToken;
			}
			$response = $this->http->request('GET', self::BASE_URL . $path, [
				'headers' => $headers,
				'timeout' => 10,
				'http_errors' => false,
			]);
		} catch (GuzzleException $exc) {
			return ToolResult::error('Bone HTTP error: ' . $exc->getMessage());
		}

		$status = $response->getStatusCode();
		$payload = (string) $response->getBody();
		// mb_strcut, not substr: a byte cut mid-codepoint breaks UTF-8.
		if (strlen($payload) > self::MAX_RESPONSE_BYTES) {
			$payload = mb_strcut($payload, 0, self::MAX_RESPONSE_BYTES, 'UTF-8') . '…[truncated]';
		}

		return new ToolResult(
			content: "HTTP {$status}\n" . $payload,
			isError: $status >= 400,
			metadata: ['status' => $status, 'path' => $path],
		);
	}
}
