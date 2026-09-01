<?php

declare(strict_types=1);

namespace App\AgentKit\Tools;

use App\AgentKit\LLMClient\ToolSchema;
use GuzzleHttp\Client as HttpClient;
use GuzzleHttp\Exception\GuzzleException;

/**
 * One tool, one argument: a cortex-lang sentence.
 *
 * IT ADDS NO CAPABILITY, and that is the whole test. KEAP /agent/v1/validate
 * decides what is a program, CortexBindingGate decides whether the world still
 * matches, and the dispatch loop's `mutating` check — a THIRD, separate check
 * — decides what may run. None of it is re-implemented here, so none of it can
 * be re-implemented wrongly here. What an agent can cause through `exec` is,
 * by construction, the set POST /api/v1/cortex/execute grants ITS OWN token.
 *
 * WHY IT EXISTS: a model guessing REST paths invents them
 * (GET /api/v1/security/findings/open/count, 404, measured 2026-08-30). A
 * cortex-lang sentence that parses is one the grammar allows — there is no
 * endpoint to invent, only opcodes the registry hash-compares at boot.
 *
 * NOT a McpWingTool subclass, deliberately: that base appends the live route
 * table to a 404, and an enumerating error is the one thing this surface
 * refuses. Inheriting the transport would have meant inheriting that branch or
 * widening `private` to `protected` to dodge it — a base class opened up for
 * one caller. Fifteen lines of constructor are cheaper than that.
 *
 * `confirm` is CHECKED, never trusted — see execute().
 *
 * Gate: tests/anatomy/test_exec_adds_no_capability.py.
 */
final class ExecTool implements ToolInterface
{
	private const BASE_URL = 'http://127.0.0.1:9000';
	private const ROUTE = '/api/v1/cortex/execute';
	private const MAX_RESPONSE_BYTES = 16_384;

	private string $bearerToken;

	public function __construct(
		private readonly HttpClient $http,
		?string $bearerToken = null,
	) {
		// The agent's OWN principal, same resolution order as McpWingTool: the
		// executor reads cortex_verbs/namespaces/tenants off the presented
		// token, so borrowing the operator's bearer would not widen anything —
		// it carries no cortex axes and is refused at the door.
		$this->bearerToken = (string) ($bearerToken ?? (getenv('NOS_AGENT_WING_TOKEN') ?: ''));
	}

	public function id(): string
	{
		return 'exec';
	}

	/**
	 * Same axis as the cortex token, not a new one. The registry refuses the
	 * tool to an agent without the grant at session start, so an agent with no
	 * cortex capability never sees the description in its system prompt.
	 *
	 * @return array<int, string>
	 */
	public function requiredScopes(): array
	{
		return ['mcp.tool_use', 'cortex.exec'];
	}

	public function schema(): ToolSchema
	{
		return new ToolSchema(
			name: 'exec',
			description: 'Run one cortex-lang sentence against the estate\'s own ontology '
				. '(taxonomy, relations). Stages are piped with `|`. Prefer starting with '
				. '`resolve` to turn a fuzzy term into a real id rather than naming one '
				. 'from memory. Read verbs only. For estate operations that are not '
				. 'ontology-shaped — health, events, pulse jobs — use contract_search '
				. 'then mcp_wing_read.',
			inputSchema: [
				'type' => 'object',
				'required' => ['chain'],
				'properties' => [
					'chain' => [
						'type' => 'string',
						'description' => 'One cortex-lang sentence.',
					],
					'confirm' => [
						'type' => 'boolean',
						'description' => 'Assert that a mutating stage is intended. '
							. 'Asserting it does not grant it.',
					],
				],
			],
		);
	}

	public function execute(array $input, ToolContext $context): ToolResult
	{
		$chain = trim((string) ($input['chain'] ?? ''));
		if ($chain === '') {
			return ToolResult::error('exec needs a `chain` — one cortex-lang sentence.');
		}

		// CONFIRM NARROWS, IT NEVER WIDENS. A caller asserting `confirm:true`
		// asserts intent, not a grant, so it is refused here: P1 dispatches no
		// mutating verb, and a flag that could turn one on would be a
		// capability arriving as DATA. The flag stays in the schema so the day
		// a write verb ships a handler is not a breaking contract change.
		//
		// ponytail: refuse rather than forward `commit`. When mutating verbs
		// ship this becomes `'commit' => true` and CortexCapability::allowsVerb
		// stays the thing that decides — confirm necessary, never sufficient.
		if (($input['confirm'] ?? false) === true) {
			return ToolResult::error(
				'mutating execution is not available; `confirm` asserts intent and '
				. 'grants nothing. Re-send the chain without it.',
				['refused_reason' => 'confirm_refused'],
			);
		}

		// No `ast_binding`: the tool caches no AST between calls, so it has
		// nothing to prove freshness with and binding_drift is unreachable
		// from this path by construction. No `tenant`: the presenter defaults
		// it and the capability check owns it.
		$raw = json_encode(['source' => $chain, 'commit' => false]);

		try {
			$response = $this->http->request('POST', self::BASE_URL . self::ROUTE, [
				'headers' => [
					'Accept' => 'application/json',
					'Content-Type' => 'application/json',
					'Authorization' => 'Bearer ' . $this->bearerToken,
					'X-AgentKit-Session' => $context->sessionUuid,
					'X-AgentKit-Trace' => $context->traceId,
				],
				'body' => $raw,
				'timeout' => 30,
				'http_errors' => false,
			]);
		} catch (GuzzleException $exc) {
			return ToolResult::error('cortex executor HTTP error: ' . $exc->getMessage());
		}

		$status = $response->getStatusCode();
		$payload = (string) $response->getBody();
		if (strlen($payload) > self::MAX_RESPONSE_BYTES) {
			$payload = mb_strcut($payload, 0, self::MAX_RESPONSE_BYTES, 'UTF-8') . '…[truncated]';
		}

		// Verbatim, nothing appended. Not even on 404 — especially not on 404.
		return new ToolResult(
			content: "HTTP {$status}\n" . $payload,
			isError: $status >= 400,
			metadata: ['status' => $status, 'chain' => $chain],
		);
	}
}
