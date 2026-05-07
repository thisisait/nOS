<?php

declare(strict_types=1);

/**
 * Wing CLI: run an AgentKit agent end to end.
 *
 *   php bin/run-agent.php --agent=conductor [--prompt=...] [--vault=...] [--trigger=pulse] [--trigger-id=...] [--session-uuid=...]
 *
 * Exit codes:
 *   0  session ended idle / outcome satisfied
 *   1  session terminated with error
 *   2  configuration error (bad --agent name, agent.yml missing, etc.)
 *
 * Pulse calls this binary as the runner for `agent` jobs. Operator runs it
 * directly during dev. The Wing /api/v1/agents/<name>/sessions POST presenter
 * spawns it via proc_open array form, passing --session-uuid so the 202
 * response can hand back the UUID before the child has booted enough to
 * write its own row. The full lineage lands in agent_sessions / events /
 * Tempo regardless of caller.
 */

require __DIR__ . '/../vendor/autoload.php';

use App\AgentKit\AgentLoadException;
use App\AgentKit\Runner;
use Nette\Bootstrap\Configurator;

$opts = parseArgs($argv);
if (empty($opts['agent'])) {
	fwrite(STDERR, "Usage: php bin/run-agent.php --agent=NAME [--prompt=TEXT] [--vault=NAME] [--trigger=pulse|webhook|operator] [--trigger-id=ID] [--session-uuid=UUID]\n");
	exit(2);
}

// --session-uuid (optional). Operator-trigger HTTP surface generates the UUID
// up-front so it can return 202 with the UUID and let the UI poll
// /api/v1/agent-sessions/<uuid> immediately. Validate format defensively
// even though the only non-test caller is AgentsPresenter::actionSessions
// (which generates v4 itself) — the CLI is publicly callable.
if (!empty($opts['session-uuid'])) {
	if (!preg_match('/^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/', (string) $opts['session-uuid'])) {
		fwrite(STDERR, "--session-uuid must be a UUID (8-4-4-4-12 hex)\n");
		exit(2);
	}
}

$configurator = new Configurator();
$configurator->setTempDirectory(__DIR__ . '/../temp');
$configurator->addConfig(__DIR__ . '/../app/config/common.neon');
if (is_file(__DIR__ . '/../app/config/local.neon')) {
	$configurator->addConfig(__DIR__ . '/../app/config/local.neon');
}
$configurator->setDebugMode(false);

$container = $configurator->createContainer();

try {
	/** @var Runner $runner */
	$runner = $container->getByType(Runner::class);
	$result = $runner->run(
		agentName: (string) $opts['agent'],
		userPrompt: $opts['prompt'] ?? null,
		vaultName: $opts['vault'] ?? null,
		trigger: $opts['trigger'] ?? 'operator',
		triggerId: $opts['trigger-id'] ?? null,
		actorId: $opts['actor'] ?? null,
		sessionUuid: $opts['session-uuid'] ?? null,
	);
} catch (AgentLoadException $exc) {
	fwrite(STDERR, "agent.yml load error: {$exc->getMessage()}\n");
	exit(2);
} catch (\Throwable $exc) {
	fwrite(STDERR, "runtime error: " . $exc::class . ": {$exc->getMessage()}\n");
	exit(1);
}

$summary = [
	'session_uuid' => $result->sessionUuid,
	'trace_id' => $result->traceId,
	'status' => $result->status,
	'stop_reason' => $result->stopReason,
	'tokens' => ['input' => $result->tokensInput, 'output' => $result->tokensOutput],
	'error' => $result->error,
];
echo json_encode($summary, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES) . "\n";
exit($result->error === null ? 0 : 1);

/**
 * @return array<string, string>
 */
function parseArgs(array $argv): array
{
	$out = [];
	foreach ($argv as $arg) {
		if (str_starts_with($arg, '--')) {
			$kv = substr($arg, 2);
			if (str_contains($kv, '=')) {
				[$k, $v] = explode('=', $kv, 2);
				$out[$k] = $v;
			} else {
				$out[$kv] = '1';
			}
		}
	}
	return $out;
}
