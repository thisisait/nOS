<?php

declare(strict_types=1);

namespace App\AgentKit\Tools;

use App\AgentKit\LLMClient\ToolSchema;

/**
 * Read-only shell command. Three security layers:
 *
 *  1. **Structured input** (A14.1, 2026-05-07). The LLM provides
 *     `{verb: string, args: string[]}` rather than a free-form command
 *     string. Tokenisation is sidestepped entirely; each argument has a
 *     hard boundary, audit rows record args verbatim, and shell
 *     metacharacter filtering becomes unnecessary because no shell is
 *     ever invoked.
 *
 *  2. **Array-form proc_open** (PHP 7.4+ POSIX). Calling
 *     `proc_open(["verb", ...args], ...)` bypasses /bin/sh entirely —
 *     PHP exec()s the binary directly. The original implementation
 *     used the string form, which delegates to `/bin/sh -c`, allowing
 *     any number of injection paths (newlines, backslash continuations,
 *     verb-rich payloads).
 *
 *  3. **Hardened verb whitelist + per-verb argv guards**. Verbs that
 *     re-enter shell or arbitrary subprocesses are dropped:
 *     awk, find, sed, php, perl, python, ruby, node, env, sudo, ssh,
 *     xargs, bash, sh, docker, curl, vim, nano, emacs.
 *     Two verbs survive with strict argv guards because the conductor
 *     self-test needs them:
 *       git      — no `-c`, no `--exec-path`, no `--ssh-command`,
 *                   no `--upload-pack`/`--receive-pack`/`--upload-archive`
 *       sqlite3  — no dot-commands (`.shell`, `.system`, `.read`),
 *                   `-readonly` flag forced
 *
 * The previous claim "the agent cannot pivot from this tool into
 * arbitrary shell" was structurally false (security review finding
 * A14.1). It is now structurally true: there is no shell, and the
 * remaining verbs cannot exec subprocesses with their permitted argv.
 *
 * Output is truncated to 8 KiB; runtime cap 30s; exit code in metadata.
 */
final class BashReadOnlyTool implements ToolInterface
{
    /**
     * Verbs that NEVER touch this tool — each can reach a shell or
     * exec arbitrary subprocesses given any argv. If an agent really
     * needs one of these capabilities, a dedicated tool with explicit
     * scope + argv design is the answer.
     */
    private const FORBIDDEN_VERBS = [
        'awk', 'find', 'sed', 'php', 'perl', 'python', 'python3',
        'ruby', 'node', 'deno', 'env', 'sudo', 'ssh', 'scp', 'rsync',
        'xargs', 'bash', 'sh', 'zsh', 'fish', 'dash', 'ksh',
        'docker', 'docker-compose', 'curl', 'wget',
        'vim', 'vi', 'nano', 'emacs', 'less', 'more',
        'systemctl', 'launchctl', 'su',
    ];

    /**
     * Allowed verbs. Order matters only for documentation; the runtime
     * uses a flip-set lookup.
     */
    private const ALLOWED_VERBS = [
        // file inspection
        'ls', 'cat', 'head', 'tail', 'stat', 'file', 'realpath', 'tree',
        // text search / count
        'grep', 'rg', 'wc',
        // structured data
        'jq',
        // identity / time / sysinfo
        'date', 'echo', 'printf', 'pwd', 'uname', 'whoami', 'id',
        // gated by per-verb argv guard below
        'git', 'sqlite3',
    ];

    private const MAX_OUTPUT_BYTES = 8192;
    private const MAX_RUNTIME_SECONDS = 30;
    private const MAX_ARGS = 32;
    private const MAX_ARG_LENGTH = 1024;

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
            description: 'Run one read-only command directly via execve (no shell). ' .
                'Provide `verb` (one of the allowed binaries) and `args` (array of ' .
                'string arguments). Allowed verbs: ' . implode(', ', self::ALLOWED_VERBS) . '. ' .
                'Verbs `git` and `sqlite3` have additional argv guards (see metadata on rejected ' .
                'calls for the specific rule). For HTTP probes use mcp_wing or mcp_bone instead. ' .
                'Output > 8 KiB is truncated; runtime cap 30s.',
            inputSchema: [
                'type' => 'object',
                'required' => ['verb'],
                'properties' => [
                    'verb' => [
                        'type' => 'string',
                        'description' => 'One of: ' . implode(', ', self::ALLOWED_VERBS),
                    ],
                    'args' => [
                        'type' => 'array',
                        'description' => 'String arguments. Each becomes a separate argv slot; ' .
                            'no shell expansion. Max 32 args, each max 1024 chars.',
                        'items' => ['type' => 'string'],
                    ],
                ],
            ],
        );
    }

    public function execute(array $input, ToolContext $context): ToolResult
    {
        $verb = $input['verb'] ?? null;
        $args = $input['args'] ?? [];

        if (!is_string($verb) || $verb === '') {
            return ToolResult::error('verb is required and must be a non-empty string');
        }
        if (!is_array($args)) {
            return ToolResult::error('args must be an array of strings');
        }
        if (count($args) > self::MAX_ARGS) {
            return ToolResult::error('too many args (max ' . self::MAX_ARGS . ')');
        }
        foreach ($args as $i => $a) {
            if (!is_string($a)) {
                return ToolResult::error("args[{$i}] must be a string");
            }
            if (strlen($a) > self::MAX_ARG_LENGTH) {
                return ToolResult::error("args[{$i}] exceeds " . self::MAX_ARG_LENGTH . ' chars');
            }
            if (strpos($a, "\0") !== false) {
                return ToolResult::error("args[{$i}] contains null byte");
            }
        }

        // Defence in depth: even though args go to execve directly, refuse
        // verbs in the forbidden list. Catches typo/aliasing in the
        // ALLOWED_VERBS list.
        if (in_array($verb, self::FORBIDDEN_VERBS, true)) {
            return ToolResult::error(
                "verb '{$verb}' is forbidden (shell-reentrant or arbitrary-exec capable). " .
                'Use a dedicated MCP tool for that capability.'
            );
        }
        if (!in_array($verb, self::ALLOWED_VERBS, true)) {
            return ToolResult::error(
                "verb '{$verb}' not in allowlist. Allowed: " . implode(', ', self::ALLOWED_VERBS)
            );
        }

        // Per-verb argv guards — applied AFTER allowlist check.
        $guardError = $this->guardArgs($verb, $args);
        if ($guardError !== null) {
            return ToolResult::error($guardError);
        }

        // Array-form proc_open: PHP exec()s the binary directly,
        // /bin/sh is NEVER spawned. Confirmed PHP 7.4+ on POSIX.
        $argv = array_merge([$verb], $args);
        $descriptors = [
            0 => ['pipe', 'r'],
            1 => ['pipe', 'w'],
            2 => ['pipe', 'w'],
        ];
        $proc = proc_open($argv, $descriptors, $pipes);
        if (!is_resource($proc)) {
            return ToolResult::error('failed to spawn process for verb ' . $verb);
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
                @fclose($pipes[1]);
                @fclose($pipes[2]);
                @proc_close($proc);
                return ToolResult::error(
                    'command timed out after ' . self::MAX_RUNTIME_SECONDS . 's',
                    ['verb' => $verb, 'duration_s' => self::MAX_RUNTIME_SECONDS],
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
                "\n...[truncated; +" . (strlen($combined) - self::MAX_OUTPUT_BYTES) . ' bytes]';
        }
        if ($combined === '') {
            $combined = "(no output, exit {$exitCode})";
        }

        return new ToolResult(
            content: $combined,
            isError: $exitCode !== 0,
            metadata: [
                'verb' => $verb,
                'argc' => count($args),
                'exit_code' => $exitCode,
                'duration_ms' => $durationMs,
            ],
        );
    }

    /**
     * Per-verb argv allowlist. Returns null on success, error string on
     * rejection. The conductor's self-test only needs `git status / log`
     * and `sqlite3 -readonly` SELECT queries; everything beyond that is
     * blocked.
     *
     * @param array<int, string> $args
     */
    private function guardArgs(string $verb, array $args): ?string
    {
        if ($verb === 'git') {
            // Forbid flags that exec arbitrary commands or change git's
            // exec behavior.
            $forbiddenPrefixes = [
                '-c',                  // -c alias.x=!cmd, -c core.sshCommand=...
                '--exec-path',         // --exec-path=DIR overrides binary location
                '--ssh-command',
                '--upload-pack',
                '--receive-pack',
                '--upload-archive',
                '--config-env',
            ];
            foreach ($args as $i => $a) {
                foreach ($forbiddenPrefixes as $bad) {
                    if ($a === $bad || str_starts_with($a, $bad . '=')) {
                        return "git: arg #{$i} starts with forbidden flag '{$bad}' " .
                            '(security review A14.1 — exec-capable git flags blocked)';
                    }
                }
                // Block git aliases that start with `!` (shell-out aliases)
                if (str_starts_with($a, '!')) {
                    return "git: arg #{$i} starts with '!' (alias shell-out blocked)";
                }
            }
            return null;
        }

        if ($verb === 'sqlite3') {
            // Refuse dot-commands (.shell, .system, .read, .import, ...).
            // Force `-readonly` so the agent cannot mutate wing.db.
            $hasReadonly = false;
            foreach ($args as $i => $a) {
                if (str_starts_with($a, '.')) {
                    return "sqlite3: arg #{$i} starts with '.' (dot-commands blocked — " .
                        'covers .shell, .system, .read, .import; security review A14.1)';
                }
                if ($a === '-cmd' || $a === '--cmd') {
                    return "sqlite3: arg #{$i} is -cmd (sqlite3 dot-commands via -cmd blocked)";
                }
                if ($a === '-readonly' || $a === '--readonly') {
                    $hasReadonly = true;
                }
            }
            if (!$hasReadonly) {
                return "sqlite3: '-readonly' flag is required (no mutating queries from agents)";
            }
            return null;
        }

        return null;
    }
}
