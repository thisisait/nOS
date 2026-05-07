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

	public function __construct(
		private readonly HttpClient $http,
	) {
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
		$path = (string) ($input['path'] ?? '');
		if (!str_starts_with($path, '/api/')) {
			return ToolResult::error("path must start with /api/; got {$path}");
		}

		try {
			$response = $this->http->request('GET', self::BASE_URL . $path, [
				'headers' => [
					'Accept' => 'application/json',
					'X-AgentKit-Session' => $context->sessionUuid,
					'X-AgentKit-Trace' => $context->traceId,
				],
				'timeout' => 10,
				'http_errors' => false,
			]);
		} catch (GuzzleException $exc) {
			return ToolResult::error('Bone HTTP error: ' . $exc->getMessage());
		}

		$status = $response->getStatusCode();
		$payload = (string) $response->getBody();
		if (strlen($payload) > self::MAX_RESPONSE_BYTES) {
			$payload = substr($payload, 0, self::MAX_RESPONSE_BYTES) . '…[truncated]';
		}

		return new ToolResult(
			content: "HTTP {$status}\n" . $payload,
			isError: $status >= 400,
			metadata: ['status' => $status, 'path' => $path],
		);
	}
}
