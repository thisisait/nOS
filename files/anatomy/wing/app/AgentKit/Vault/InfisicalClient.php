<?php

declare(strict_types=1);

namespace App\AgentKit\Vault;

/**
 * Thin wrapper around the Infisical CLI for resolving `infisical:/path`
 * secret_ref pointers into plaintext values.
 *
 * Security invariants (locked by tests/anatomy/test_agentkit_infisical_vault.py):
 *
 *  1. **Array-form proc_open only.** Same A14.1 lesson the BashReadOnlyTool
 *     was forced through: `proc_open(["binary", ...args], ...)` execve()s
 *     the binary directly. The string form delegates to `/bin/sh -c` and
 *     is exploitable via metacharacters in the path.
 *
 *  2. **Minimal env allowlist.** The child process inherits PATH/HOME/TZ
 *     and the explicit `INFISICAL_TOKEN` (universal-auth machine identity).
 *     Nothing else — FrankenPHP's parent env carries ANTHROPIC_API_KEY,
 *     WING_API_TOKEN, BONE_SECRET, and we do NOT propagate those to a
 *     spawned subprocess. Mirrors BashReadOnlyTool::minimalEnv() (A14.2).
 *
 *  3. **Path-shape validation.** The slash-prefixed path component (e.g.
 *     `/agents/anthropic-api`) is validated against `^/[A-Za-z0-9_/-]+$`
 *     BEFORE anything is passed to proc_open. A bad path is rejected with
 *     null AND the path is NOT echoed in the rejection log line.
 *
 *  4. **Plaintext never logged.** The resolved value lives in function
 *     locals only — error_log() lines describe the FAILURE shape (path
 *     malformed, CLI missing, exit non-zero), never the value or the
 *     INFISICAL_TOKEN.
 *
 *  5. **No disk caching.** The CredentialResolver caches at instance level
 *     for the session lifetime. This wrapper is stateless — every call
 *     re-invokes the CLI.
 *
 * The Infisical CLI is an OPTIONAL operator install. When the binary is
 * not on PATH, `fetch()` returns null + logs once so the caller (the
 * resolver) can fall back to the env-var deterministic-name path. This
 * is the documented graceful-degradation contract.
 *
 * Upstream CLI invocation:
 *   infisical secrets get <secret-name> --path <parent-path> --plain
 *
 * The single-key fetch returns the secret value on stdout with `--plain`
 * (no JSON envelope, no key=value framing). Non-zero exit signals
 * not-found / not-authorised / network problem; we do not distinguish
 * because all three resolve to "fall back to env" from the agent's POV.
 */
final class InfisicalClient
{
	/**
	 * Validates the path component of an `infisical:/path` secret_ref.
	 * Slash-prefixed; alnum + underscore + dash + interior slashes only.
	 * No `..`, no spaces, no shell metacharacters, no leading dot.
	 */
	private const PATH_PATTERN = '#^/[A-Za-z0-9_/-]+$#';

	private const MAX_RUNTIME_SECONDS = 10;
	private const MAX_OUTPUT_BYTES = 65536;

	/**
	 * Env vars forwarded to the spawned CLI process. Anything outside
	 * this list (including ANTHROPIC_API_KEY / WING_API_TOKEN /
	 * BONE_SECRET / WING_EVENTS_HMAC_SECRET / OPENCLAW_API_KEY) is
	 * dropped. Mirrors BashReadOnlyTool::minimalEnv() (A14.2).
	 */
	private const ENV_ALLOWLIST = [
		'PATH',
		'HOME',
		'LANG',
		'LC_ALL',
		'LC_CTYPE',
		'TZ',
		'PWD',
		'TMPDIR',
		// CLI-specific:
		'INFISICAL_TOKEN', // universal-auth machine identity
	];

	private static bool $cliMissingLogged = false;

	/**
	 * Fetch a single secret from Infisical via the CLI.
	 *
	 * @param string $path slash-prefixed path component from secret_ref,
	 *                     e.g. `/agents/anthropic-api`. The trailing
	 *                     segment is the secret NAME; the leading
	 *                     segments form the PARENT PATH passed to
	 *                     `--path`.
	 * @return string|null resolved value (function-local only) or null
	 *                     on any failure (path-malformed, CLI missing,
	 *                     non-zero exit, empty stdout, timeout).
	 */
	public function fetch(string $path): ?string
	{
		if (!self::isValidPath($path)) {
			// Do NOT echo the bad input — it could be attacker-controlled
			// (e.g. via a future Tier-2 manifest path field).
			error_log('[agentkit] infisical: rejected malformed secret_ref path');
			return null;
		}

		// Split `/parent/path/secret-name` into ('/parent/path', 'secret-name').
		$lastSlash = strrpos($path, '/');
		if ($lastSlash === false || $lastSlash === strlen($path) - 1) {
			error_log('[agentkit] infisical: secret_ref path missing secret name');
			return null;
		}
		$parentPath = $lastSlash === 0 ? '/' : substr($path, 0, $lastSlash);
		$secretName = substr($path, $lastSlash + 1);
		if ($secretName === '') {
			error_log('[agentkit] infisical: secret_ref path missing secret name');
			return null;
		}

		$binary = $this->locateBinary();
		if ($binary === null) {
			if (!self::$cliMissingLogged) {
				error_log('[agentkit] infisical CLI not on PATH; falling back to env');
				self::$cliMissingLogged = true;
			}
			return null;
		}

		$argv = [
			$binary,
			'secrets',
			'get',
			$secretName,
			'--path',
			$parentPath,
			'--plain',
			'--silent',
		];

		[$exit, $stdout] = $this->runCommand($argv);
		if ($exit !== 0) {
			// Don't echo $path or $secretName; treat as a "miss" and let
			// the caller fall back to env. The exit code is informative
			// without disclosing what was being queried.
			error_log('[agentkit] infisical: secrets-get exit=' . $exit . ' (caller falls back to env)');
			return null;
		}

		// Normalise — `--plain` still emits a trailing newline.
		$value = rtrim($stdout, "\r\n");
		return $value !== '' ? $value : null;
	}

	/**
	 * Path-shape gate. PUBLIC + STATIC so the test suite can pin the
	 * regex without instantiating the class or running PHP.
	 */
	public static function isValidPath(string $path): bool
	{
		if ($path === '' || strlen($path) > 256) {
			return false;
		}
		// Defence in depth — the regex already excludes these, but a future
		// edit that loosens the class would still fail here.
		if (str_contains($path, '..') || str_contains($path, "\0")) {
			return false;
		}
		return preg_match(self::PATH_PATTERN, $path) === 1;
	}

	/**
	 * Returns the absolute path to the `infisical` binary if it exists
	 * in one of the standard install locations, otherwise null. We do
	 * NOT shell out to `which` / `command -v` — that re-enters /bin/sh.
	 *
	 * Resolution order:
	 *   1. INFISICAL_BIN env var (operator escape hatch)
	 *   2. Homebrew Apple Silicon prefix
	 *   3. Homebrew Intel prefix
	 *   4. /usr/local/bin
	 *   5. /usr/bin
	 */
	private function locateBinary(): ?string
	{
		$override = getenv('INFISICAL_BIN');
		if (is_string($override) && $override !== '' && is_executable($override)) {
			return $override;
		}
		$candidates = [
			'/opt/homebrew/bin/infisical',
			'/usr/local/bin/infisical',
			'/usr/bin/infisical',
		];
		foreach ($candidates as $candidate) {
			if (is_executable($candidate)) {
				return $candidate;
			}
		}
		return null;
	}

	/**
	 * Invokes proc_open with the array form. Mirrors the BashReadOnlyTool
	 * shape exactly — pipes for stdout/stderr, minimal env, runtime cap,
	 * output-size cap.
	 *
	 * @param list<string> $argv
	 * @return array{0:int,1:string} [exitCode, stdout]
	 */
	private function runCommand(array $argv): array
	{
		$descriptors = [
			0 => ['pipe', 'r'],
			1 => ['pipe', 'w'],
			2 => ['pipe', 'w'],
		];
		$env = $this->minimalEnv();
		$proc = proc_open($argv, $descriptors, $pipes, null, $env);
		if (!is_resource($proc)) {
			return [-1, ''];
		}
		fclose($pipes[0]);
		stream_set_blocking($pipes[1], false);
		stream_set_blocking($pipes[2], false);

		$stdout = '';
		$started = microtime(true);
		while (true) {
			$status = proc_get_status($proc);
			$stdout .= (string) stream_get_contents($pipes[1]);
			// Drain stderr but do not retain it — Infisical CLI may
			// surface telemetry hints there that we don't need to log.
			stream_get_contents($pipes[2]);
			if (!$status['running']) {
				break;
			}
			if (microtime(true) - $started > self::MAX_RUNTIME_SECONDS) {
				proc_terminate($proc, 9);
				@fclose($pipes[1]);
				@fclose($pipes[2]);
				@proc_close($proc);
				return [-1, ''];
			}
			if (strlen($stdout) > self::MAX_OUTPUT_BYTES) {
				proc_terminate($proc, 9);
				@fclose($pipes[1]);
				@fclose($pipes[2]);
				@proc_close($proc);
				return [-1, ''];
			}
			usleep(50_000);
		}
		fclose($pipes[1]);
		fclose($pipes[2]);
		$exit = proc_close($proc);
		return [$exit, $stdout];
	}

	/**
	 * Minimal env passed to the spawned child. Everything outside
	 * ENV_ALLOWLIST (incl. ANTHROPIC_API_KEY / WING_API_TOKEN / BONE_SECRET)
	 * is dropped. Mirrors BashReadOnlyTool::minimalEnv() (A14.2).
	 *
	 * @return array<string,string>
	 */
	private function minimalEnv(): array
	{
		$env = [];
		foreach (self::ENV_ALLOWLIST as $name) {
			$value = getenv($name);
			if (is_string($value) && $value !== '') {
				$env[$name] = $value;
			}
		}
		// PATH must always exist or proc_open can't resolve relative
		// binaries. (We use absolute paths above, but defence in depth.)
		if (!isset($env['PATH'])) {
			$env['PATH'] = '/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin';
		}
		return $env;
	}
}
