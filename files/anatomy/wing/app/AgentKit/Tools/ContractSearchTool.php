<?php

declare(strict_types=1);

namespace App\AgentKit\Tools;

use App\AgentKit\LLMClient\ToolSchema;
use App\AgentKit\StaticIndex;

/**
 * Find the endpoint that already exists, instead of inventing one.
 *
 * Measured 2026-08-30: `jeff`, asked how many security findings are open,
 * called a made-up GET /api/v1/security/findings/open/count and 404'd. The
 * real one — GET /api/v1/remediation — was already described, with its query
 * parameters, in files/anatomy/skills/contracts/wing.openapi.yml, which no
 * tool and no prompt ever read. This tool is the missing half in front of
 * mcp-wing-read: find the path, then call it.
 *
 * THE LINE, and it is the whole reason this tool is safe to hand out with no
 * data scope: it returns ONLY static strings that are already sitting in two
 * committed, auto-generated contract files. It executes no request, opens no
 * database, holds no bearer token, and can never return a row, an id or a
 * count. Searching it answers "what verb and path would ask that question",
 * never "what do you have" — so it is not the enumeration oracle that
 * 02-cortex-lang refuses at namespace granularity. A future version that
 * wants to short-circuit to the live number is a DIFFERENT tool with a
 * scope gate of its own, not a quiet addition here.
 * Gate: tests/anatomy/test_contract_search_is_read_only.py.
 */
final class ContractSearchTool implements ToolInterface
{
	/** Repo-relative home of the auto-generated contracts. */
	private const CONTRACTS_SUBDIR = 'files/anatomy/skills/contracts';

	private const SURFACES = [
		'wing' => 'wing.openapi.yml',
		'bone' => 'bone.openapi.yml',
	];

	/** Five ranked rows is a decision; 117 rows is a dump the model must re-solve. */
	private const LIMIT = 5;

	/**
	 * Below this fraction of the query's weighted words, say nothing matched.
	 * A near-miss offered confidently is how the 404 happened in the first
	 * place — the refusal has to be a real outcome, not a floor of zero.
	 */
	private const FLOOR = 0.34;

	private ?StaticIndex $index = null;

	/**
	 * The contracts live in the playbook CHECKOUT, not the deployed Wing tree.
	 * Same injection as MigrationWriteTool: NOS_REPO_ROOT via %nosRepoRoot%,
	 * never getcwd() — the daemon's cwd is not stable.
	 */
	public function __construct(private readonly string $repoRoot)
	{
	}

	public function id(): string
	{
		return 'contract-search';
	}

	/**
	 * No wing.read, no bone.read, no data scope of any kind — deliberately.
	 * This list is the machine-readable half of THE LINE above, and the gate
	 * asserts it stays this short.
	 *
	 * @return array<int, string>
	 */
	public function requiredScopes(): array
	{
		return ['mcp.tool_use'];
	}

	public function schema(): ToolSchema
	{
		return new ToolSchema(
			name: 'contract_search',
			description: 'Search nOS\'s own OpenAPI contracts (Wing + Bone) for an operation '
				. 'matching a plain-language request, in any language. Returns up to '
				. self::LIMIT . ' candidates — method, path and summary, nothing else. '
				. 'Call this BEFORE guessing an endpoint, then call the path with '
				. 'mcp_wing_read. If it reports no confident match, do NOT invent a path.',
			inputSchema: [
				'type' => 'object',
				'required' => ['query'],
				'properties' => [
					'query' => [
						'type' => 'string',
						'description' => 'What you are trying to do, plain language, any language.',
					],
				],
			],
		);
	}

	public function execute(array $input, ToolContext $context): ToolResult
	{
		$query = trim((string) ($input['query'] ?? ''));
		if ($query === '') {
			return ToolResult::error('contract_search needs a `query` — say what you are trying to do.');
		}

		try {
			$index = $this->index();
		} catch (\Throwable $exc) {
			// Fail SOFT and say which file: a silently empty result would read
			// as "no such endpoint exists", the worse wrong answer.
			return ToolResult::error(
				'contract_search could not read the contracts: ' . $exc->getMessage(),
				['refused_reason' => 'contracts_unreadable'],
			);
		}

		$hits = $index->search($query, self::LIMIT, self::FLOOR);
		if ($hits === []) {
			return ToolResult::ok(
				'no confident match — do not guess a path; ask the operator, or use '
				. 'mcp_wing_read on a path you can justify from a doc.',
				['query' => $query, 'hits' => 0],
			);
		}

		$lines = array_map(
			static fn(array $hit): string => $hit['source'] . '  ' . $hit['label'],
			$hits,
		);
		return ToolResult::ok(
			"Candidate operations, best first. These are copied verbatim from the\n"
			. "committed contract; nothing here was executed.\n\n" . implode("\n", $lines),
			['query' => $query, 'hits' => count($hits)],
		);
	}

	private function index(): StaticIndex
	{
		if ($this->index !== null) {
			return $this->index;
		}
		if ($this->repoRoot === '') {
			throw new \RuntimeException('NOS_REPO_ROOT is not set, so the contract files cannot be located.');
		}
		$entries = [];
		foreach (self::SURFACES as $source => $basename) {
			$file = $this->repoRoot . '/' . self::CONTRACTS_SUBDIR . '/' . $basename;
			if (!is_readable($file)) {
				throw new \RuntimeException("missing or unreadable: {$file}");
			}
			$entries = array_merge($entries, StaticIndex::openApi($file, $source));
		}
		return $this->index = new StaticIndex($entries);
	}
}
