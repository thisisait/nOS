<?php

declare(strict_types=1);

namespace App\AgentKit;

/**
 * OperatorTrigger — the single audited entry point that spawns an AgentKit
 * `bin/run-agent.php` runner as a non-blocking child (A3.1, 2026-06-16).
 *
 * Extracted verbatim from Api\AgentsPresenter::spawnRunner so BOTH the bearer
 * operator-trigger API (`POST /api/v1/agents/<name>/sessions`) AND the browser
 * Tier-1 "Promote to migration" button (UpgradesPresenter::actionPromoteToMigration,
 * A3.2) call the SAME spawn path — one place that:
 *
 *   - resolves the PHP CLI binary (FrankenPHP's embedded SAPI leaves PHP_BINARY
 *     empty, so proc_open threw "non-empty program name"; WING_PHP_BIN env →
 *     PHP_BINARY → brew/system php),
 *   - builds argv as a hard-bounded ARRAY (execve direct, never /bin/sh — the
 *     A14.1 shell-injection wall: argv slots have hard boundaries, no
 *     metacharacter has meaning, LLM/operator values reach the child verbatim),
 *   - generates the session UUID server-side up-front so the caller can hand it
 *     back immediately (the UI polls /api/v1/agent-sessions/<uuid>),
 *   - detaches stdio to /dev/null and does NOT proc_close (that would block on
 *     the child; the OS reaps via SIGCHLD).
 *
 * ACTOR IDENTITY (A3 doctrine): the spawned agent runs AS ITSELF. The caller
 * passes the agent's OWN actor id (e.g. 'nos-migration-author', its Authentik
 * client holding nos:migration:write) — never the operator who pressed the
 * button. The operator is captured separately as `triggered_by` in the
 * supervision event + the prompt. The agent's audit identity is its scope; the
 * operator is the supervisor. The API presenter still derives `actorId` from
 * the bearer token (its existing anti-spoof guard) and passes it here; the
 * button passes the agent's fixed client id. This service does not invent or
 * default an actor — the caller is responsible for the identity it spawns under.
 *
 * Fail-soft contract: on any structural failure (no PHP binary, proc_open
 * false) it throws OperatorTriggerException. The API presenter maps that to a
 * 500 sendError; the browser presenter maps it to a flash + redirect. Keeping
 * the failure as a typed exception (not a presenter-coupled sendError) is what
 * lets the one spawn body serve both surfaces.
 */
final class OperatorTrigger
{
	public function __construct(
		private AgentLoader $loader,
	) {
	}

	/**
	 * Spawn `php bin/run-agent.php --agent=<agent> --trigger=operator …` as a
	 * detached child. Returns the generated session UUID + child PID.
	 *
	 * @param array<string,string> $env Extra env exported to the child (e.g.
	 *        NOS_MIGRATION_SERVICE / NOS_MIGRATION_RECIPE_ID / NOS_TRIGGERED_BY
	 *        for the A3 button). Keys are validated to the env-name charset; the
	 *        child inherits the parent env merged with these.
	 *
	 * @return array{session_uuid:string, pid:?int}
	 *
	 * @throws OperatorTriggerException agent name unknown, no PHP binary, or
	 *         proc_open returned false.
	 */
	public function spawn(
		string $agent,
		string $actorId,
		?string $prompt = null,
		?string $vault = null,
		array $env = [],
	): array {
		// Validate the agent resolves on disk before spawning anything. Mirrors
		// the AgentsPresenter pre-spawn load() — catches a malformed name that
		// would otherwise reach argv and be rejected by the child only after a
		// ~500ms container boot.
		try {
			$this->loader->load($agent);
		} catch (AgentLoadException $exc) {
			throw new OperatorTriggerException("unknown agent '{$agent}': {$exc->getMessage()}", 404, $exc);
		}

		$sessionUuid = self::generateUuidV4();
		$wingRoot = dirname(__DIR__, 2); // app/AgentKit -> app -> wing root
		$runnerPath = $wingRoot . '/bin/run-agent.php';

		// PHP_BINARY is EMPTY under FrankenPHP's embedded SAPI (no CLI binary
		// backs the worker), so proc_open threw "First element must contain a
		// non-empty program name". Resolution order: explicit WING_PHP_BIN env
		// (the launchd plist pins it) → PHP_BINARY when non-empty (classic
		// FPM/CLI) → first executable brew/system php.
		$phpBin = getenv('WING_PHP_BIN') ?: (PHP_BINARY !== '' ? PHP_BINARY : null);
		if ($phpBin === null || !is_executable($phpBin)) {
			foreach (['/opt/homebrew/bin/php', '/usr/local/bin/php', '/usr/bin/php'] as $candidate) {
				if (is_executable($candidate)) {
					$phpBin = $candidate;
					break;
				}
			}
		}
		if ($phpBin === null || !is_executable($phpBin)) {
			throw new OperatorTriggerException('No PHP CLI binary found for the agent runner (set WING_PHP_BIN)', 500);
		}

		$argv = [
			$phpBin,
			$runnerPath,
			'--agent=' . $agent,
			'--trigger=operator',
			'--actor=' . $actorId,
			'--session-uuid=' . $sessionUuid,
		];
		if ($prompt !== null) {
			$argv[] = '--prompt=' . $prompt;
		}
		if ($vault !== null) {
			$argv[] = '--vault=' . $vault;
		}

		$descriptors = [
			0 => ['file', '/dev/null', 'r'],
			1 => ['file', '/dev/null', 'w'],
			2 => ['file', '/dev/null', 'w'],
		];

		// Merge the caller-supplied env onto the inherited parent env so the
		// child sees both the Wing daemon's bearer/HMAC/NOS_REPO_ROOT AND the
		// per-run NOS_MIGRATION_* keys. proc_open with a null env inherits the
		// parent; we pass an explicit merged array only when extras are given.
		// Env names are charset-validated (no '=' / NUL smuggling) — values
		// pass through verbatim (no shell, so no metacharacter meaning).
		$childEnv = null;
		if ($env !== []) {
			$childEnv = $this->mergedEnv($env);
		}

		$proc = proc_open($argv, $descriptors, $pipes, $wingRoot, $childEnv);
		if (!is_resource($proc)) {
			throw new OperatorTriggerException('Failed to spawn agent runner (proc_open returned false)', 500);
		}
		$status = proc_get_status($proc);
		// Intentionally detach: closing the process handle would block until the
		// child exits, defeating the non-blocking contract. The OS reaps via
		// SIGCHLD; we read the PID and let the handle fall out of scope.
		$pid = is_array($status) && isset($status['pid']) ? (int) $status['pid'] : null;

		return ['session_uuid' => $sessionUuid, 'pid' => $pid];
	}

	/**
	 * Inherited parent env + the caller's extras. Rejects malformed env names
	 * (anything outside [A-Za-z_][A-Za-z0-9_]*) so a crafted key cannot smuggle
	 * an '=' that splits into a second variable. Values are passed verbatim.
	 *
	 * @param array<string,string> $extra
	 * @return array<string,string>
	 */
	private function mergedEnv(array $extra): array
	{
		$base = getenv();
		if (!is_array($base)) {
			$base = [];
		}
		foreach ($extra as $k => $v) {
			if (!is_string($k) || preg_match('/^[A-Za-z_][A-Za-z0-9_]*$/', $k) !== 1) {
				// Skip a malformed env name rather than risk an '=' split.
				continue;
			}
			$base[$k] = (string) $v;
		}
		return $base;
	}

	/**
	 * RFC 4122 v4 UUID. Hand-rolled (random_bytes is core, no ramsey/uuid dep
	 * for one call site) — identical to the former AgentsPresenter helper.
	 */
	public static function generateUuidV4(): string
	{
		$data = random_bytes(16);
		$data[6] = chr((ord($data[6]) & 0x0f) | 0x40); // version 4
		$data[8] = chr((ord($data[8]) & 0x3f) | 0x80); // variant 10
		return vsprintf('%s%s-%s-%s-%s-%s%s%s', str_split(bin2hex($data), 4));
	}
}

/**
 * Thrown by OperatorTrigger::spawn on a structural failure. The integer code is
 * an HTTP-shaped hint (404 unknown agent, 500 no PHP binary / proc_open false)
 * so the bearer Api\AgentsPresenter can map it straight to sendError(); the
 * browser UpgradesPresenter ignores the code and renders a flash.
 */
final class OperatorTriggerException extends \RuntimeException
{
}
