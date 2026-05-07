<?php

declare(strict_types=1);

namespace App\AgentKit\Tools;

use App\AgentKit\LLMClient\ToolSchema;

/**
 * Read-only shell command. Whitelisted commands only — the agent cannot
 * pivot from this tool into arbitrary shell. The whitelist sits in code
 * rather than config because it's a security boundary; adding a verb is a
 * deliberate code change reviewed in PR.
 *
 * Output is truncated to 8 KiB to keep the LLM context small. Stdout +
 * stderr are concatenated (LLM doesn't care about the file-descriptor
 * distinction). Exit code is exposed via metadata so the audit trail can
 * filter on it.
 */
final class BashReadOnlyTool implements ToolInterface
{
	private const ALLOWED_COMMANDS = [
		'ls', 'cat', 'head', 'tail', 'grep', 'rg', 'find',
		'wc', 'stat', 'file', 'realpath', 'tree',
		'git', 'docker', 'sqlite3', 'jq', 'awk', 'sed',
		'php', 'curl', 'date', 'echo', 'printf', 'pwd',
		'uname', 'whoami', 'id',
	];

	private const MAX_OUTPUT_BYTES = 8192;
	private const MAX_RUNTIME_SECONDS = 30;

	public function id(): string
	{
		return 'bash-read-only';
	}

	public function requiredScopes(): array
	{
		return ['bash.read'];
	}

	public function schema(): ToolSchema
	{
		return new ToolSchema(
			name: 'bash_read_only',
			description: 'Run a single read-only shell command. ' .
				'Allowed verbs: ' . implode(', ', self::ALLOWED_COMMANDS) . '. ' .
				'Pipes and redirections are blocked; chain commands via xargs ' .
				'or call this tool multiple times. Output > 8KiB is truncated.',
			inputSchema: [
				'type' => 'object',
				'required' => ['command'],
				'properties' => [
					'command' => [
						'type' => 'string',
						'description' => 'The shell command to execute, including arguments.',
					],
				],
			],
		);
	}

	public function execute(array $input, ToolContext $context): ToolResult
	{
		$command = (string) ($input['command'] ?? '');
		if ($command === '') {
			return ToolResult::error('command is required');
		}

		// Block shell metacharacters that enable pivoting / writes.
		foreach (['|', '>', '<', '`', '$(', '&&', '||', ';'] as $forbidden) {
			if (str_contains($command, $forbidden)) {
				return ToolResult::error(
					"command contains forbidden token '{$forbidden}' — bash-read-only " .
					'forbids piping, redirection, command substitution, and chaining. ' .
					'Issue separate tool calls instead.'
				);
			}
		}

		$verb = strtok($command, " \t");
		if ($verb === false || !in_array($verb, self::ALLOWED_COMMANDS, true)) {
			return ToolResult::error(
				"command verb '{$verb}' is not allowed. Allowed: " .
				implode(', ', self::ALLOWED_COMMANDS)
			);
		}

		$descriptors = [
			0 => ['pipe', 'r'],
			1 => ['pipe', 'w'],
			2 => ['pipe', 'w'],
		];
		$proc = proc_open($command, $descriptors, $pipes);
		if (!is_resource($proc)) {
			return ToolResult::error('failed to spawn process');
		}
		fclose($pipes[0]);

		$stdout = '';
		$stderr = '';
		$started = microtime(true);

		stream_set_blocking($pipes[1], false);
		stream_set_blocking($pipes[2], false);

		while (true) {
			$status = proc_get_status($proc);
			$stdout .= (string) stream_get_contents($pipes[1]);
			$stderr .= (string) stream_get_contents($pipes[2]);
			if (!$status['running']) {
				break;
			}
			if (microtime(true) - $started > self::MAX_RUNTIME_SECONDS) {
				proc_terminate($proc, 9);
				return ToolResult::error(
					"command timed out after " . self::MAX_RUNTIME_SECONDS . 's',
					['command' => $command, 'duration_s' => self::MAX_RUNTIME_SECONDS],
				);
			}
			usleep(50_000);
		}

		fclose($pipes[1]);
		fclose($pipes[2]);
		$exitCode = proc_close($proc);
		$durationMs = (int) ((microtime(true) - $started) * 1000);

		$combined = $stdout . ($stderr !== '' ? "\n[stderr]\n" . $stderr : '');
		if (strlen($combined) > self::MAX_OUTPUT_BYTES) {
			$combined = substr($combined, 0, self::MAX_OUTPUT_BYTES) .
				"\n…[truncated; +" . (strlen($combined) - self::MAX_OUTPUT_BYTES) . ' bytes]';
		}
		if ($combined === '') {
			$combined = "(no output, exit {$exitCode})";
		}

		return new ToolResult(
			content: $combined,
			isError: $exitCode !== 0,
			metadata: [
				'command' => $command,
				'exit_code' => $exitCode,
				'duration_ms' => $durationMs,
			],
		);
	}
}
