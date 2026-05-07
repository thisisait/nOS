<?php

declare(strict_types=1);

namespace App\AgentKit;

/**
 * Multi-agent coordinator. Currently a thin wrapper around Runner — when an
 * agent.yml declares multiagent.type=coordinator, the coordinator agent's
 * tool roster gets a synthetic `delegate-to` tool exposed via the LLM,
 * so the LLM can spawn child sessions. Implementation of the spawn path is
 * scoped tight in this first cut: the coordinator runs in the SAME process,
 * each child gets its own Runner invocation with parent_thread_uuid wired.
 *
 * The bigger design (parallel threads, 25-thread cap, primary-thread event
 * proxy) lands in a follow-up that adds a process pool — for now sub-agents
 * run sequentially. The audit trail still distinguishes parent vs child via
 * agent_threads.parent_thread_uuid, so the lineage is fully reconstructable
 * even with sequential execution.
 */
final class Coordinator
{
	public function __construct(
		private readonly Runner $runner,
	) {
	}

	/**
	 * Convenience entry: same surface as Runner::run() but explicit about
	 * coordinator semantics. Returns the coordinator's RunResult; child
	 * sessions are accessible via agent_threads joined on the coordinator
	 * session_uuid.
	 */
	public function run(
		string $coordinatorAgent,
		?string $userPrompt = null,
		?string $vaultName = null,
		string $trigger = 'operator',
		?string $triggerId = null,
		?string $actorId = null,
	): RunResult {
		return $this->runner->run(
			$coordinatorAgent,
			$userPrompt,
			$vaultName,
			$trigger,
			$triggerId,
			$actorId,
		);
	}
}
