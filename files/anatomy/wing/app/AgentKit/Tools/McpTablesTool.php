<?php

declare(strict_types=1);

namespace App\AgentKit\Tools;

use App\AgentKit\LLMClient\ToolSchema;
use GuzzleHttp\Client as HttpClient;
use GuzzleHttp\Exception\GuzzleException;

/**
 * The DataTables verb surface — one tiny, uniform door onto KEAP's
 * /agent/v1/tables/*, so a "dumber" agent can read, search, claim and write a
 * table row without ever learning a path, an HTTP method, or which columns are
 * git-owned vs table-owned. It answers "what open work is about the loop's WAL
 * races?" with the row, then lets the agent claim and patch it.
 *
 * Why a VERB surface and not McpKeapTool's method+path: the whole point of the
 * DataTables harness is that the agent names an INTENT (search-rows) and a few
 * typed fields, never a URL. The verb map below IS the write allowlist — an
 * agent can reach exactly these eight operations and nothing else, which is a
 * tighter surface than a path allowlist a caller could probe around.
 *
 * Read verbs ride the read-only KEAP token; write verbs ride read-write, the
 * same scope split McpKeapTool uses. Every write is upsert-shaped by the store
 * (patch-an-existing-id, insert-otherwise); `claim-row` is a cooperative,
 * advisory lease so two agents do not both edit one row.
 */
final class McpTablesTool implements ToolInterface
{
	private const MAX_RESPONSE_BYTES = 16_384;

	/** verb => plane. The plane picks the token; the map is the allowlist. */
	private const VERBS = [
		'list-tables' => 'read',
		'read-rows' => 'read',
		'get-row' => 'read',
		'search-rows' => 'read',
		'upsert-row' => 'write',
		'patch-field' => 'write',
		'claim-row' => 'write',
		'release-row' => 'write',
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
		$this->baseUrl = rtrim((string) ($baseUrl ?? getenv('KEAP_API_URL') ?: 'http://127.0.0.1:8091'), '/');
		$this->tokenRo = (string) ($tokenRo ?? getenv('KEAP_AGENT_TOKEN_RO') ?: '');
		$this->tokenRw = (string) ($tokenRw ?? getenv('KEAP_AGENT_TOKEN_RW') ?: '');
	}

	public function id(): string
	{
		return 'mcp-tables';
	}

	/** Reads and writes the corpus, so both KEAP planes — same as mcp-keap. */
	public function requiredScopes(): array
	{
		return ['mcp.tool_use', 'keap.read', 'keap.write'];
	}

	public function schema(): ToolSchema
	{
		$verbs = implode(', ', array_keys(self::VERBS));
		return new ToolSchema(
			name: 'mcp_tables',
			description: 'Work nOS DataTables (roadmap, apps, systems, …) through one small verb set. ' .
				'A row is addressed by its __id (returned by every read). Verbs: ' . $verbs . '. ' .
				'search-rows finds rows by MEANING and returns NOTHING below a confidence floor — an ' .
				'empty result is a real "no match", not the nearest wrong row. Writes are upsert-shaped ' .
				'(give __id to update, omit it to insert). claim-row takes a cooperative lease so two ' .
				'agents do not both edit one row; a claim on a row another agent holds is refused. ' .
				'Returns up to 16 KiB of the response verbatim.',
			inputSchema: [
				'type' => 'object',
				'required' => ['verb'],
				'properties' => [
					'verb' => ['type' => 'string', 'enum' => array_keys(self::VERBS)],
					'table' => ['type' => 'string', 'description' => 'Table slug, e.g. "roadmap". Required for every verb except list-tables.'],
					'id' => ['type' => 'string', 'description' => 'Row __id. Required for get-row, patch-field, claim-row, release-row; optional for upsert-row (present = update, absent = insert).'],
					'q' => ['type' => 'string', 'description' => 'Query text for search-rows.'],
					'limit' => ['type' => 'integer', 'description' => 'Max results for search-rows / read-rows (server caps at 50).'],
					'values' => ['type' => 'object', 'description' => 'Column key→value map for upsert-row.'],
					'field' => ['type' => 'string', 'description' => 'Single column key for patch-field.'],
					'value' => ['description' => 'New value for patch-field (any JSON type).'],
				],
			],
		);
	}

	public function execute(array $input, ToolContext $context): ToolResult
	{
		$verb = (string) ($input['verb'] ?? '');
		if (!isset(self::VERBS[$verb])) {
			return ToolResult::error('verb must be one of: ' . implode(', ', array_keys(self::VERBS)));
		}

		$table = trim((string) ($input['table'] ?? ''));
		if ($verb !== 'list-tables' && $table === '') {
			return ToolResult::error("verb '{$verb}' needs a `table`");
		}
		$id = trim((string) ($input['id'] ?? ''));

		$plane = self::VERBS[$verb];
		[$method, $path, $body, $err] = $this->route($verb, $table, $id, $input);
		if ($err !== null) {
			return ToolResult::error($err);
		}

		$token = $plane === 'write' ? $this->tokenRw : $this->tokenRo;
		if ($token === '') {
			$var = $plane === 'write' ? 'KEAP_AGENT_TOKEN_RW' : 'KEAP_AGENT_TOKEN_RO';
			return ToolResult::error("{$var} is not set — KEAP agent surface unreachable");
		}

		$opts = [
			'headers' => [
				'Accept' => 'application/json',
				'Authorization' => 'Bearer ' . $token,
				// KEAP prefixes attribution with "agent:" itself — send the bare
				// name (the lesson McpKeapTool records after "agent:agent:…").
				'X-Keap-Agent' => preg_replace('#^agent:#', '', (string) $context->actorId),
				'X-AgentKit-Session' => $context->sessionUuid,
				'X-AgentKit-Trace' => $context->traceId,
			],
			'timeout' => 10,
			'http_errors' => false,
		];
		if ($body !== null) {
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
			$payload = mb_strcut($payload, 0, self::MAX_RESPONSE_BYTES, 'UTF-8') . '…[truncated]';
		}

		return new ToolResult(
			content: "HTTP {$status}\n" . $payload,
			isError: $status >= 400,
			metadata: ['status' => $status, 'verb' => $verb, 'table' => $table],
		);
	}

	/**
	 * Verb → [method, path, body|null, error|null]. All input validation for a
	 * verb lives here; a missing field returns a fail-soft error the LLM can fix.
	 *
	 * @param array<string, mixed> $input
	 * @return array{0: string, 1: string, 2: array<string, mixed>|null, 3: string|null}
	 */
	private function route(string $verb, string $table, string $id, array $input): array
	{
		$t = rawurlencode($table);
		$rows = "/agent/v1/tables/{$t}/rows";
		$needId = fn(): ?string => $id === '' ? "verb '{$verb}' needs an `id`" : null;

		switch ($verb) {
			case 'list-tables':
				return ['GET', '/agent/v1/tables', null, null];

			case 'read-rows':
				$limit = (int) ($input['limit'] ?? 0);
				return ['GET', $rows . ($limit > 0 ? '?limit=' . $limit : ''), null, null];

			case 'get-row':
				return ['GET', $rows . '/' . rawurlencode($id), null, $needId()];

			case 'search-rows':
				$q = trim((string) ($input['q'] ?? ''));
				if ($q === '') {
					return ['GET', '', null, "verb 'search-rows' needs a `q`"];
				}
				$query = ['q' => $q];
				if ((int) ($input['limit'] ?? 0) > 0) {
					$query['limit'] = (string) (int) $input['limit'];
				}
				return ['GET', "/agent/v1/tables/{$t}/search?" . http_build_query($query), null, null];

			case 'upsert-row':
				$values = $input['values'] ?? null;
				if (!is_array($values) || $values === []) {
					return ['POST', $rows, null, "verb 'upsert-row' needs a non-empty `values` object"];
				}
				// __id is how the door routes a write to an existing row; absent
				// = insert. The agent passes it as `id`, not inside `values`.
				if ($id !== '') {
					$values['__id'] = $id;
				}
				return ['POST', $rows, $values, null];

			case 'patch-field':
				$field = trim((string) ($input['field'] ?? ''));
				if ($id === '' || $field === '') {
					return ['POST', $rows, null, "verb 'patch-field' needs an `id` and a `field`"];
				}
				// Upsert merge-semantics patch ONE cell: {__id, <field>: <value>}.
				return ['POST', $rows, ['__id' => $id, $field => $input['value'] ?? null], null];

			case 'claim-row':
				return ['POST', $rows . '/' . rawurlencode($id) . '/claim', null, $needId()];

			case 'release-row':
				return ['POST', $rows . '/' . rawurlencode($id) . '/release', null, $needId()];
		}

		return ['GET', '', null, "unknown verb '{$verb}'"]; // unreachable: guarded above
	}
}
