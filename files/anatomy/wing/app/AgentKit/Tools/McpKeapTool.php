<?php

declare(strict_types=1);

namespace App\AgentKit\Tools;

use App\AgentKit\LLMClient\ToolSchema;
use GuzzleHttp\Client as HttpClient;
use GuzzleHttp\Exception\GuzzleException;

/**
 * MCP-style wrapper around KEAP (the cortex) — the agent-facing knowledge
 * surface at /agent/v1/*. Same shape as McpWingTool but scope-split at the
 * KEAP token level: GETs ride the read-only token; the permitted writes ride
 * the read-write token. Every write is a PROPOSAL into the moderation queue —
 * captures, OKF objects, lint verdicts, promotions, and the taxonomy
 * propose/describe/brief ceremonies (see POST_ALLOWLIST). There is no approve
 * path. Anything else KEAP exposes for writing (embeddings upsert, lint run)
 * belongs to the keap-embed-sync / keap-lint Pulse jobs, not to an LLM tool.
 *
 * Why this tool exists at all: KEAP's loopback port is the ONLY agent path
 * to the knowledge corpus. The container sits alone with Traefik on the
 * SEC-02 gated_net (its /api surface trusts X-Authentik-* headers, so no
 * other container may share that network), which rules out mcpo/Open WebUI
 * reaching it container-to-container — host-side AgentKit is the intended
 * consumer.
 *
 * Notable endpoints (see /agent/v1/openapi.json for the full surface):
 *   GET  /agent/v1/taxonomy/search?q=      FTS over the 790-node taxonomy
 *   GET  /agent/v1/taxonomy/node/{id}      detail + curated notes + link
 *   GET  /agent/v1/search/semantic?q=      vector search (libSQL corpus)
 *   GET  /agent/v1/content/resolve?ref=    ref -> live nOS service URL
 *   GET  /agent/v1/objects                 list knowledge objects (index cards)
 *   POST /agent/v1/captures                submit a capture (review queue)
 *   POST /agent/v1/objects                 create a knowledge object; [[node-id]]
 *                                          refs in the body anchor it in the
 *                                          explorer's nebula layer
 */
final class McpKeapTool implements ToolInterface
{
	private const MAX_RESPONSE_BYTES = 16_384;

	/** The ONLY writable paths — widening this list is a doctrine change. */
	private const POST_ALLOWLIST = [
		'/agent/v1/captures',      // preserve a page into the review queue
		'/agent/v1/objects',       // create an OKF index card
		'/agent/v1/lint/verdict',  // librarian Layer-2 judgment on a lint finding
		'/agent/v1/promotions',    // PROPOSE capture->object (moderator decides)
		'/agent/v1/taxonomy/propose', // PROPOSE a new node (Track T; zone-governed)
		'/agent/v1/taxonomy/describe', // PROPOSE curated descriptions (K1; kind=desc, moderated)
		'/agent/v1/taxonomy/brief',   // PROPOSE node articles with vazby (kind=brief, moderated)
	];

	private string $baseUrl;
	private string $tokenRo;
	private string $tokenRw;

	public function __construct(
		private readonly HttpClient $http,
		?string $baseUrl = null,
		?string $tokenRo = null,
		?string $tokenRw = null,
	) {
		// Resolve at construct time so DI doesn't need parameter bindings.
		// Daemon mode reads the launchd plist environment block; CLI runs
		// export the same vars (pulse job env / operator shell).
		$this->baseUrl = rtrim((string) ($baseUrl ?? getenv('KEAP_API_URL') ?: 'http://127.0.0.1:8091'), '/');
		$this->tokenRo = (string) ($tokenRo ?? getenv('KEAP_AGENT_TOKEN_RO') ?: '');
		$this->tokenRw = (string) ($tokenRw ?? getenv('KEAP_AGENT_TOKEN_RW') ?: '');
	}

	public function id(): string
	{
		return 'mcp-keap';
	}

	public function requiredScopes(): array
	{
		return ['mcp.tool_use', 'keap.read'];
	}

	public function schema(): ToolSchema
	{
		// Derive the allowed-POST wording from the constant so the tool
		// description can never drift from the enforced allowlist again.
		$postPaths = implode(', ', self::POST_ALLOWLIST);
		return new ToolSchema(
			name: 'mcp_keap',
			description: 'Query the KEAP knowledge cortex via /agent/v1/*: taxonomy FTS + hybrid ' .
				'semantic search, node detail with curated notes, knowledge objects (index cards), ' .
				'content-ref resolution into live nOS services. Every POST is a PROPOSAL — a ' .
				'moderator decides; there is no approve path. POST is allowed ONLY to: ' . $postPaths .
				'. Returns up to 16 KiB of the response verbatim.',
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
						'description' => 'Path beginning with /agent/v1/. POST only to: ' . $postPaths . '.',
					],
					'body' => [
						'type' => 'object',
						'description' => 'JSON body (POST only). captures: {title, description?, url?, domain?, metadata?}. ' .
							'objects: {type, title, body?, resource?, tags?}. lint/verdict: {findingId, verdict, note}. ' .
							'promotions: {captureId, object, rationale}. taxonomy/propose: {parentId, name, description, rationale}. ' .
							'taxonomy/describe: {items:[{nodeId, descriptionEn, descriptionCs, rationale?}]}. ' .
							'taxonomy/brief: {items:[{nodeId, briefEn, briefCs, rationale?}]}.',
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
		if (!str_starts_with($path, '/agent/v1/')) {
			return ToolResult::error("path must start with /agent/v1/; got {$path}");
		}
		if ($method === 'POST' && !in_array($path, self::POST_ALLOWLIST, true)) {
			return ToolResult::error('POST is allowed only to: ' . implode(', ', self::POST_ALLOWLIST));
		}

		$token = $method === 'POST' ? $this->tokenRw : $this->tokenRo;
		if ($token === '') {
			$var = $method === 'POST' ? 'KEAP_AGENT_TOKEN_RW' : 'KEAP_AGENT_TOKEN_RO';
			return ToolResult::error("{$var} is not set — KEAP agent surface unreachable");
		}

		$opts = [
			'headers' => [
				'Accept' => 'application/json',
				'Authorization' => 'Bearer ' . $token,
				// KEAP attributes writes as user_id "agent:<name>".
				'X-Keap-Agent' => $context->actorId,
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
			$response = $this->http->request($method, $this->baseUrl . $path, $opts);
		} catch (GuzzleException $exc) {
			return ToolResult::error('KEAP API HTTP error: ' . $exc->getMessage());
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
