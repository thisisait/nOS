<?php

declare(strict_types=1);

namespace App\AgentKit\Tools;

use App\AgentKit\LLMClient\ToolSchema;

/**
 * The loop engine's proposing plane, and only that.
 *
 * WHY THIS EXISTS. `tools/loop-propose.py` was moved onto AgentKit on
 * 2026-08-29 for good reasons — the old spawn was `claude --print
 * --permission-mode bypassPermissions`, which gave the loop's entry the
 * operator's identity, no session row, no ceiling and no binding. The runner
 * moved; the CAPABILITY did not. `.claude/plugins/nos-loop/skills/propose/`
 * instructs the agent to `curl` the engine, `curl` is on `BashReadOnlyTool`'s
 * banned list, and `McpBoneTool` says of itself "it has no write plane". So the
 * proposer could be spawned and could not propose: measured the same day, with
 * `loop:propose` exiting 1 and buying nothing.
 *
 * It shells to `nos-loop`, the estate's own thin client, rather than speaking
 * HTTP: that client already resolves the per-verb token
 * (`BONE_LOOP_*_TOKEN`, else `~/.nos/secrets.yml`), and a second implementation
 * of the same auth is a second thing to be wrong. `GateOracle` reaches the
 * engine the same way.
 *
 * CONSTRAINT A AT THE TOOL LEVEL. The subcommand allowlist below carries
 * `propose` and refuses `judge`. That is not tidiness: in a self-improvement
 * loop the verdict is the reward signal for the next modification, so a
 * proposer that can reach its own verdict does not merely lie — it optimises
 * against the lie. `forget` is refused for the same reason one layer along: it
 * lifts a retry block, which is the loop's memory of having failed.
 */
final class McpLoopTool implements ToolInterface
{
	/** What a proposer may run. `judge` and `forget` are absent BY DESIGN. */
	private const ALLOWED = ['weaknesses', 'budget', 'propose', 'history'];

	/** Refused by name, so the refusal can say why rather than "unknown". */
	private const REFUSED = [
		'judge' => 'the proposer may not reach its own verdict (constraint A)',
		'judge-status' => 'the proposer may not read its own verdict (constraint A)',
		'forget' => 'lifting a retry block is the operator\'s act, not the proposer\'s',
	];

	private const MAX_RESPONSE_BYTES = 16_384;

	/**
	 * @param ?callable(array<int,string>): array{exit:int,stdout:string,stderr:string} $spawn
	 *        Replaces the PROCESS for tests, never the allowlist — the refusal
	 *        below is computed before anything is spawned.
	 */
	public function __construct(
		private readonly mixed $spawn = null,
	) {
	}

	public function id(): string
	{
		return 'mcp-loop';
	}

	public function requiredScopes(): array
	{
		return ['mcp.tool_use', 'loop.propose'];
	}

	public function schema(): ToolSchema
	{
		return new ToolSchema(
			name: 'mcp_loop',
			description: 'Talk to the nOS loop engine through `nos-loop`. Subcommands: '
				. implode(', ', self::ALLOWED) . '. Read the budget before proposing; '
				. 'record the proposal BEFORE editing anything. `judge` is refused — the '
				. 'proposer does not reach its own verdict.',
			inputSchema: [
				'type' => 'object',
				'required' => ['subcommand'],
				'properties' => [
					'subcommand' => ['type' => 'string', 'enum' => self::ALLOWED],
					'args' => [
						'type' => 'array',
						'items' => ['type' => 'string'],
						'description' => 'Flags for the subcommand, e.g. '
							. '["--weakness","rem:REM-1","--gate-set","live"].',
					],
				],
			],
		);
	}

	public function execute(array $input, ToolContext $context): ToolResult
	{
		$sub = (string) ($input['subcommand'] ?? '');
		if (isset(self::REFUSED[$sub])) {
			return ToolResult::error(
				"mcp-loop refuses `{$sub}`: " . self::REFUSED[$sub],
				['refused_reason' => 'subcommand_not_in_scope', 'subcommand' => $sub],
			);
		}
		if (!in_array($sub, self::ALLOWED, true)) {
			return ToolResult::error(
				"mcp-loop subcommand must be one of " . implode(', ', self::ALLOWED)
				. "; got " . ($sub === '' ? '(none)' : $sub),
				['refused_reason' => 'subcommand_not_in_scope', 'subcommand' => $sub],
			);
		}

		$args = [];
		foreach ((array) ($input['args'] ?? []) as $a) {
			if (!is_string($a)) {
				return ToolResult::error('args must be strings');
			}
			$args[] = $a;
		}

		// The session is stamped HERE, not asked of the model. A proposal that
		// names a session the model chose names whatever the model chose;
		// stamping it from the context is what makes the ledger join a fact.
		if ($sub === 'propose' && !in_array('--session-uuid', $args, true)) {
			$args[] = '--session-uuid';
			$args[] = $context->sessionUuid;
		}
		// AND THE AUTHOR, for exactly the same reason and one field over.
		//
		// `nos-loop propose` defaults --proposer-id to "operator:$USER" — the
		// right default for a human at a terminal, and a false statement for
		// every agent run, because this tool never sent the flag. Measured
		// 2026-08-31: the proposal filed by the unattended nightly job at
		// 01:33 is recorded as `operator:pazny`. The operator was asleep.
		//
		// That is not a cosmetic mis-stamp. The loop's whole safety story is
		// that a proposal can be traced to what authored it and what it cost;
		// an agent's work wearing the operator's name defeats the audit at the
		// first question it will ever be asked. Stamped from the context like
		// the session above — never asked of the model, which could name
		// anyone.
		if ($sub === 'propose' && !in_array('--proposer-id', $args, true)) {
			$args[] = '--proposer-id';
			$args[] = $context->actorId;
		}

		$argv = array_merge(['nos-loop', $sub], $args);
		$done = $this->run($argv);
		$out = trim($done['stdout'] . ($done['stderr'] !== '' ? "\n" . $done['stderr'] : ''));
		if (strlen($out) > self::MAX_RESPONSE_BYTES) {
			$out = mb_strcut($out, 0, self::MAX_RESPONSE_BYTES, 'UTF-8') . '…[truncated]';
		}

		return new ToolResult(
			content: "exit {$done['exit']}\n" . $out,
			isError: $done['exit'] !== 0,
			metadata: ['exit' => $done['exit'], 'subcommand' => $sub],
		);
	}

	/** @param array<int,string> $argv */
	private function run(array $argv): array
	{
		if (is_callable($this->spawn)) {
			return ($this->spawn)($argv);
		}
		$cmd = implode(' ', array_map('escapeshellarg', $argv));
		$proc = proc_open($cmd, [1 => ['pipe', 'w'], 2 => ['pipe', 'w']], $pipes);
		if (!is_resource($proc)) {
			return ['exit' => 127, 'stdout' => '', 'stderr' => 'could not spawn nos-loop'];
		}
		$stdout = (string) stream_get_contents($pipes[1]);
		$stderr = (string) stream_get_contents($pipes[2]);
		fclose($pipes[1]);
		fclose($pipes[2]);
		return ['exit' => proc_close($proc), 'stdout' => $stdout, 'stderr' => $stderr];
	}
}
