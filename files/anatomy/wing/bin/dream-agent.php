<?php

declare(strict_types=1);

/**
 * Wing CLI: run an AgentKit Dreams (memory consolidation) cycle.
 *
 *   php bin/dream-agent.php --agent=NAME [--limit=50] [--store-limit=20] [--dry-run]
 *
 * Reads the LAST `limit` agent_sessions for the named agent + the current
 * agent_memory_stores entries, runs the agent's primary LLM under a strictly
 * read-only "dream" tool roster (NO bash, NO mcp_wing write endpoints), and
 * applies the LLM's deduplication decisions to the store.
 *
 * Exit codes:
 *   0  cycle completed (deltas applied, or no-op)
 *   1  dream error (agent not opted in, LLM call failed, parse error)
 *   2  configuration error (bad --agent name, agent.yml missing, etc.)
 *
 * Pulse can call this binary as the runner for `dream` jobs once the
 * scheduling block lands. Operator runs it directly during dev. Audit trail
 * is the same agent_sessions/events shape A14 already lays down — just with
 * trigger=dream marker and a dedicated session_uuid per cycle.
 */

require __DIR__ . '/../vendor/autoload.php';

use App\AgentKit\AgentLoadException;
use App\AgentKit\Memory\Dreamer;
use Nette\Bootstrap\Configurator;

$opts = parseArgs($argv);
if (empty($opts['agent'])) {
	fwrite(STDERR, "Usage: php bin/dream-agent.php --agent=NAME [--limit=50] [--store-limit=20] [--dry-run]\n");
	exit(2);
}

$agentName = (string) $opts['agent'];
$limit = isset($opts['limit']) ? (int) $opts['limit'] : Dreamer::DEFAULT_RECENT;
$storeLimit = isset($opts['store-limit']) ? (int) $opts['store-limit'] : Dreamer::DEFAULT_STORE_LIMIT;
$dryRun = array_key_exists('dry-run', $opts);

if ($limit < 1) {
	fwrite(STDERR, "--limit must be >= 1\n");
	exit(2);
}
if ($storeLimit < 1) {
	fwrite(STDERR, "--store-limit must be >= 1\n");
	exit(2);
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
	/** @var Dreamer $dreamer */
	$dreamer = $container->getByType(Dreamer::class);
	$result = $dreamer->dream(
		agentName: $agentName,
		sessionLimit: $limit,
		storeLimit: $storeLimit,
		dryRun: $dryRun,
	);
} catch (AgentLoadException $exc) {
	fwrite(STDERR, "agent.yml load error: {$exc->getMessage()}\n");
	exit(2);
} catch (\Throwable $exc) {
	fwrite(STDERR, "dream error: " . $exc::class . ": {$exc->getMessage()}\n");
	exit(1);
}

echo json_encode($result->toArray(), JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES) . "\n";
exit(0);

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
