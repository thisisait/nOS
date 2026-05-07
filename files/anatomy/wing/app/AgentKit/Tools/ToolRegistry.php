<?php

declare(strict_types=1);

namespace App\AgentKit\Tools;

use App\AgentKit\Agent;
use App\AgentKit\ToolSpec;

/**
 * Registry mapping agent.yml::tools[].id → ToolInterface implementation.
 *
 * The registry is built once per Wing process via container DI; the runner
 * asks for the subset declared in an agent's tools roster at session start.
 *
 * Capability-scope check: when an agent declares a tool, the registry
 * verifies that every scope the tool requires (Tool::requiredScopes()) is
 * present in agent.audit.capability_scopes. A mismatch raises immediately
 * — better to refuse to start the session than to discover mid-run that
 * the agent can't actually use what it declared.
 */
final class ToolRegistry
{
	/** @var array<string, ToolInterface> */
	private array $tools = [];

	public function register(ToolInterface $tool): void
	{
		$this->tools[$tool->id()] = $tool;
	}

	/**
	 * @return array<int, ToolInterface>
	 */
	public function forAgent(Agent $agent): array
	{
		$scopes = array_flip($agent->capabilityScopes);
		$out = [];
		foreach ($agent->tools as $spec) {
			/** @var ToolSpec $spec */
			$tool = $this->tools[$spec->id] ?? null;
			if ($tool === null) {
				throw new \RuntimeException(
					"Agent '{$agent->name}' declares unknown tool id '{$spec->id}'. " .
					'Register the implementation in App\AgentKit\Tools or remove it from agent.yml.'
				);
			}
			$missing = array_diff($tool->requiredScopes(), array_keys($scopes));
			if ($missing !== []) {
				throw new \RuntimeException(
					"Agent '{$agent->name}' tool '{$spec->id}' requires scopes [" .
					implode(', ', $missing) . '] which are not in audit.capability_scopes.'
				);
			}
			$out[] = $tool;
		}
		return $out;
	}

	public function get(string $id): ?ToolInterface
	{
		return $this->tools[$id] ?? null;
	}
}
