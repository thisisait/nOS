<?php

declare(strict_types=1);

namespace App\AgentKit;

/**
 * Parsed agent.yml — immutable value object.
 *
 * Loaded by AgentLoader from files/anatomy/agents/<name>/agent.yml. The
 * AgentKit runtime never mutates an Agent; a config update means re-loading
 * from disk, which produces a NEW Agent with bumped `version`. This mirrors
 * Anthropic Managed Agents' versioned-agent semantics — pin a specific
 * version at session start, the running session keeps that snapshot even
 * if the YAML on disk is changed mid-run.
 */
final class Agent
{
	/**
	 * @param string $name                   stable id matching directory name (lower+dashes)
	 * @param int    $version                bumped on every breaking change
	 * @param string $description            human description for /agents UI
	 * @param string $modelPrimaryUri        e.g. 'anthropic-claude-opus-4-7'
	 * @param ?string $modelFallbackUri      e.g. 'openclaw-qwen-coder-32b'
	 * @param ?string $systemPrompt          loaded from system_prompt_path or null
	 * @param array<int, ToolSpec> $tools
	 * @param string $multiagentType         'solo' | 'coordinator'
	 * @param array<int, RosterEntry> $roster non-empty iff multiagentType=coordinator
	 * @param int    $maxConcurrentThreads
	 * @param ?Outcome\Rubric $rubric        loaded from rubric_path or null
	 * @param int    $maxIterations          1..10, default 3
	 * @param array<int, string> $capabilityScopes
	 * @param string $piiClassification      'none' | 'low' | 'high'
	 * @param array<int, VaultRequirement> $requiredCredentials
	 * @param array<string, mixed> $metadata
	 * @param string $sourceDir              absolute path to agent's directory
	 */
	public function __construct(
		public readonly string $name,
		public readonly int $version,
		public readonly string $description,
		public readonly string $modelPrimaryUri,
		public readonly ?string $modelFallbackUri,
		public readonly ?string $systemPrompt,
		public readonly array $tools,
		public readonly string $multiagentType,
		public readonly array $roster,
		public readonly int $maxConcurrentThreads,
		public readonly ?Outcome\Rubric $rubric,
		public readonly int $maxIterations,
		public readonly array $capabilityScopes,
		public readonly string $piiClassification,
		public readonly array $requiredCredentials,
		public readonly array $metadata,
		public readonly string $sourceDir,
	) {
	}

	public function isCoordinator(): bool
	{
		return $this->multiagentType === 'coordinator';
	}

	public function hasOutcome(): bool
	{
		return $this->rubric !== null;
	}
}

/**
 * One declared tool reference. Tool implementations live in App\AgentKit\Tools\*
 * keyed on $id; ToolRegistry maps id→implementation at session start.
 */
final class ToolSpec
{
	/**
	 * @param array<string, mixed> $config
	 */
	public function __construct(
		public readonly string $id,
		public readonly array $config = [],
	) {
	}
}

/**
 * One coordinator-roster entry. `version` may be null to mean "use latest".
 */
final class RosterEntry
{
	public function __construct(
		public readonly string $name,
		public readonly ?int $version = null,
	) {
	}
}

/**
 * One required credential. `optional=true` means the session starts without
 * it but tools that need this scope will fail-soft.
 */
final class VaultRequirement
{
	public function __construct(
		public readonly string $scope,
		public readonly bool $optional = false,
	) {
	}
}
