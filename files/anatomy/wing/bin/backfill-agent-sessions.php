<?php

declare(strict_types=1);

/**
 * backfill-agent-sessions.php — synthesize agent_sessions rows for historical
 * pulse / claude-CLI agent runs (W5-A1, 2026-05-26).
 *
 * The claude-CLI runtime (pulse-run-agent.sh) emits agent_run_start/end events
 * grouped by actor_action_id but never created agent_sessions rows, so past
 * runs are invisible in /agents. This replays those events through
 * AgentSessionRepository::syncFromAgentEvent (idempotent), so historical runs
 * appear as sessions. New runs are synced live by Api\EventsPresenter.
 *
 * Idempotent — safe to run on every deploy. Usage:
 *   php files/anatomy/wing/bin/backfill-agent-sessions.php
 */

require dirname(__DIR__) . '/vendor/autoload.php';

use App\Bootstrap\Booting;
use App\Model\AgentSessionRepository;
use App\Model\EventRepository;

$container = Booting::boot()->createContainer();
$sessions = $container->getByType(AgentSessionRepository::class);
$events = $container->getByType(EventRepository::class);

// Pull agent_run_* events oldest-first so start precedes end.
$rows = array_reverse($events->query(['type' => 'agent_run_start'], 500)['items']);
$rows = array_merge($rows, array_reverse($events->query(['type' => 'agent_run_end'], 500)['items']));
usort($rows, static fn($a, $b) => ($a['id'] ?? 0) <=> ($b['id'] ?? 0));

$synced = 0;
foreach ($rows as $ev) {
    $sessions->syncFromAgentEvent($ev);
    $synced++;
}

$total = $container->getByType(\Nette\Database\Explorer::class)
    ->table('agent_sessions')->count('*');

echo "backfill: replayed {$synced} agent_run_* events; agent_sessions now holds {$total} row(s).\n";
