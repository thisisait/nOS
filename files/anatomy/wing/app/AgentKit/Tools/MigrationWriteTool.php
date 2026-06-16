<?php

declare(strict_types=1);

namespace App\AgentKit\Tools;

use App\AgentKit\LLMClient\ToolSchema;

/**
 * Gated migration file-write tool (Q8/A1, 2026-06-16).
 *
 * The single security invariant — stated first, enforced everywhere:
 *
 *   The write tool writes ONLY into the working tree. It commits nothing,
 *   merges nothing, runs no `--tags`, touches no live cluster. The write
 *   surface is EXACTLY two targets — a migration YAML under
 *   `files/anatomy/migrations/` and `default.config.yml` — and nothing
 *   else is writable, ever. The same review-MR-then-operator-merge gate
 *   (GATE 2) that governs the CLI path governs this path UNCHANGED.
 *   AgentKit gains visibility (sessions/spans/dashboard), not reach.
 *
 * Mirrors BashReadOnlyTool's defensive structure: structured input
 * (`{path, content}`, never a free-form command), fail-soft (every refusal
 * returns ToolResult::error so the LLM self-corrects rather than crashing
 * the session), metadata-rich audit, and — critically — NO shell. There is
 * no proc_open/exec/shell_exec/system/passthru/popen anywhere; this is a
 * pure file write guarded by a regex + realpath containment, never a
 * command string.
 *
 * The escape-refusal gate (execute(), below) is the load-bearing security
 * logic. It is pinned structurally by
 * tests/anatomy/test_security_agentkit_filewrite.py.
 *
 * Repo-root injection: the migration dir + default.config.yml live in the
 * nOS playbook CHECKOUT, not the deployed Wing tree (~/wing/app/...). The
 * daemon cwd is unstable, so we never getcwd(); the constructor takes the
 * repo working-tree root, wired from NOS_REPO_ROOT (the Wing daemon plist
 * env + the flat migration-author Pulse env both export
 * NOS_REPO_ROOT={{ playbook_dir }}). Empty/missing → execute() fail-softs
 * (reason `repo_root`) rather than ever writing to the wrong place.
 */
final class MigrationWriteTool implements ToolInterface
{
    /** Migration YAML home, repo-relative. The ONLY writable subdir. */
    private const MIGRATIONS_SUBDIR = 'files/anatomy/migrations';

    /** The ONLY writable repo-root file. */
    private const CONFIG_BASENAME = 'default.config.yml';

    /** 256 KiB content cap — a migration YAML is small; refuse a runaway write. */
    private const MAX_CONTENT_BYTES = 256 * 1024;

    /**
     * Migration filename shape: <YYYY-MM-DD>-<slug>.yml, lowercase slug.
     * Matches the existing files/anatomy/migrations/<ISO-date>-<slug>.yml
     * convention (anatomy A1). Anchored — no path separators can sneak in.
     */
    private const MIGRATION_NAME_RE = '/^\d{4}-\d{2}-\d{2}-[a-z0-9][a-z0-9-]*\.yml$/';

    private string $repoRoot;

    public function __construct(string $repoRoot)
    {
        $this->repoRoot = $repoRoot;
    }

    public function id(): string
    {
        return 'migration-file-write';
    }

    /**
     * The scope-gate IS the structural admission control: the registry
     * refuses to load this tool unless the agent's audit.capability_scopes
     * cover `nos.migration.write` (already present on the migration-author
     * profile). No scope → the session never starts.
     *
     * @return array<int, string>
     */
    public function requiredScopes(): array
    {
        return ['nos.migration.write'];
    }

    public function schema(): ToolSchema
    {
        return new ToolSchema(
            name: 'migration_file_write',
            description: 'Write ONE file into the nOS working tree. Allowed targets are exactly two: ' .
                'a migration YAML at `files/anatomy/migrations/<YYYY-MM-DD>-<slug>.yml`, ' .
                'OR `default.config.yml` (for a `<service>_version` bump). ' .
                'Provide `path` (repo-relative; no `..`, no absolute, no nested subdir) and ' .
                '`content` (the FULL file content; the tool creates/overwrites atomically; max 256 KiB). ' .
                'Writes to the WORKING TREE ONLY — it commits nothing, makes nothing live; a human ' .
                'reviews + merges the resulting MR (GATE 2). Any path outside the two allowed targets ' .
                'is refused by design — that refusal is expected, self-correct the path.',
            inputSchema: [
                'type' => 'object',
                'required' => ['path', 'content'],
                'properties' => [
                    'path' => [
                        'type' => 'string',
                        'description' => 'Repo-relative path. Either ' .
                            'files/anatomy/migrations/<YYYY-MM-DD>-<slug>.yml OR default.config.yml. ' .
                            'No `..`, no leading `/`, no nested subdir.',
                    ],
                    'content' => [
                        'type' => 'string',
                        'description' => 'Full file content (the tool overwrites atomically). Max 256 KiB.',
                    ],
                ],
            ],
        );
    }

    /**
     * The escape-refusal gate. Each step fail-softs via ToolResult::error so
     * the LLM self-corrects; the `refused_reason` lands verbatim in the
     * agent_tool_result audit event (and the OTel span). NEVER throws to the
     * Runner — bad input is the agent's fault, not the platform's.
     *
     * @param array<string, mixed> $input
     */
    public function execute(array $input, ToolContext $context): ToolResult
    {
        $path = $input['path'] ?? null;
        $content = $input['content'] ?? null;

        // 1. Type / null-byte / size guards.
        if (!is_string($path) || $path === '') {
            return $this->refuse('path is required and must be a non-empty string', 'type', (string) $path);
        }
        if (!is_string($content)) {
            return $this->refuse('content is required and must be a string', 'type', $path);
        }
        if (strpos($path, "\0") !== false) {
            return $this->refuse('path contains a null byte', 'type', $path);
        }
        if (strlen($content) > self::MAX_CONTENT_BYTES) {
            return $this->refuse(
                'content exceeds ' . self::MAX_CONTENT_BYTES . ' bytes (256 KiB cap)',
                'size',
                $path,
            );
        }

        // 2. Repo-root sanity. A missing/empty NOS_REPO_ROOT must NEVER write
        //    to the wrong place — fail-soft, never silently guess a cwd.
        $root = realpath($this->repoRoot);
        if ($root === false || !is_dir($root)) {
            return $this->refuse(
                'repo working-tree root is unset or not a directory (NOS_REPO_ROOT). ' .
                'The write tool cannot resolve its allowlist — refusing.',
                'repo_root',
                $path,
            );
        }

        // 3. No absolute input.
        if (str_starts_with($path, '/')) {
            return $this->refuse('path must be repo-relative, not absolute', 'absolute', $path);
        }

        // 4. No traversal. Belt-and-suspenders with the realpath containment
        //    below; gives the LLM a clear, early error first.
        foreach (explode('/', $path) as $segment) {
            if ($segment === '..' || $segment === '.') {
                return $this->refuse(
                    "path segment '{$segment}' is not allowed (no traversal)",
                    'traversal',
                    $path,
                );
            }
        }

        // 5. Classify against the allowlist — EXACTLY two arms.
        $arm = null;
        $target = null;
        if ($path === self::CONFIG_BASENAME) {
            // Arm (b): the one writable repo-root file.
            $arm = 'config';
            $target = $root . '/' . self::CONFIG_BASENAME;
        } elseif (str_starts_with($path, self::MIGRATIONS_SUBDIR . '/')) {
            // Arm (a): a migration YAML, exactly one level deep, name-shaped.
            $rest = substr($path, strlen(self::MIGRATIONS_SUBDIR) + 1);
            if ($rest === '' || str_contains($rest, '/')) {
                return $this->refuse(
                    'migration path must be files/anatomy/migrations/<name>.yml ' .
                    '(no nested subdirectory)',
                    'allowlist',
                    $path,
                );
            }
            if (preg_match(self::MIGRATION_NAME_RE, $rest) !== 1) {
                return $this->refuse(
                    'migration filename must match <YYYY-MM-DD>-<slug>.yml ' .
                    '(lowercase slug, e.g. 2026-06-16-postgresql-16-to-17.yml)',
                    'allowlist',
                    $path,
                );
            }
            $arm = 'migration';
            $target = $root . '/' . $path;
        } else {
            return $this->refuse(
                'path is outside the allowlist. The ONLY writable targets are ' .
                "'" . self::MIGRATIONS_SUBDIR . "/<YYYY-MM-DD>-<slug>.yml' and " .
                "'" . self::CONFIG_BASENAME . "'.",
                'allowlist',
                $path,
            );
        }

        // 6. Realpath containment (symlink-escape refusal). The target file
        //    may not exist yet, so canonicalise the PARENT dir and assert it
        //    sits exactly inside the allowed location. This is the
        //    BashReadOnlyTool realpath idiom applied to the parent.
        $parentReal = realpath(dirname($target));
        if ($parentReal === false) {
            return $this->refuse(
                'cannot canonicalise the target parent directory (symlink/missing)',
                'symlink_escape',
                $path,
            );
        }

        if ($arm === 'config') {
            // default.config.yml must live directly in the repo root.
            if ($parentReal !== $root) {
                return $this->refuse(
                    'default.config.yml parent does not resolve to the repo root (symlink escape)',
                    'symlink_escape',
                    $path,
                );
            }
        } else {
            // The migrations dir itself must (a) resolve, (b) be inside the
            // repo root, and (c) BE the target's parent. (c) catches a
            // symlinked `migrations` dir pointing outside the tree.
            $migrationsReal = realpath($root . '/' . self::MIGRATIONS_SUBDIR);
            if ($migrationsReal === false) {
                return $this->refuse(
                    'the migrations directory does not resolve under the repo root',
                    'symlink_escape',
                    $path,
                );
            }
            if (!str_starts_with($migrationsReal . '/', $root . '/')) {
                return $this->refuse(
                    'the migrations directory resolves OUTSIDE the repo root (symlink escape)',
                    'symlink_escape',
                    $path,
                );
            }
            if ($parentReal !== $migrationsReal) {
                return $this->refuse(
                    'the target parent does not resolve to the migrations directory (symlink escape)',
                    'symlink_escape',
                    $path,
                );
            }
        }

        // If the target file ALREADY exists, re-assert it sits under the same
        // allowed parent — catches a pre-existing symlink FILE whose target is
        // elsewhere (a TOCTOU-resistant final check before the write).
        $existedBefore = file_exists($target);
        if ($existedBefore) {
            $targetReal = realpath($target);
            if ($targetReal === false || dirname($targetReal) !== $parentReal) {
                return $this->refuse(
                    'the existing target file resolves outside its allowed directory ' .
                    '(pre-existing symlink escape)',
                    'symlink_escape',
                    $path,
                );
            }
        }

        // 7. Atomic write: write to a temp sibling, then rename() into place.
        //    rename() is atomic on POSIX — no half-written YAML is ever
        //    observable to a concurrent reader / the playbook.
        $tmp = $target . '.tmp.' . bin2hex(random_bytes(6));
        $bytes = @file_put_contents($tmp, $content);
        if ($bytes === false) {
            return $this->refuse('failed to write the temporary file', 'write_failed', $path);
        }
        if (!@rename($tmp, $target)) {
            @unlink($tmp);
            return $this->refuse('failed to rename the temporary file into place', 'write_failed', $path);
        }

        // 8. Success result + metadata. NEVER put $content into metadata
        //    (audit-leak guard — the security gate asserts it never appears).
        //    The agent_tool_use event already echoes the input (path+content);
        //    acceptable here because the agent declares pii_classification:
        //    none and migration records carry no secrets (a DB name at most).
        return new ToolResult(
            content: "wrote {$path} ({$bytes} bytes)",
            isError: false,
            metadata: [
                'path_written' => $path,
                'bytes' => $bytes,
                'arm' => $arm,
                'created' => !$existedBefore,
            ],
        );
    }

    /**
     * Uniform fail-soft refusal. The reason lands verbatim in the
     * agent_tool_result audit event + the OTel span attributes.
     */
    private function refuse(string $message, string $reason, string $attemptedPath): ToolResult
    {
        return ToolResult::error(
            $message,
            [
                'refused_reason' => $reason,
                'attempted_path' => $attemptedPath,
            ],
        );
    }
}
