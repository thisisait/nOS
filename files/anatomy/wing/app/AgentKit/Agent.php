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
	 * @param array<int, SubscriptionSpec> $subscriptions  per-agent webhook fan-out
	 * @param array<string, mixed> $metadata
	 * @param string $sourceDir              absolute path to agent's directory
	 * @param ?string $backendName           `model.backend` — backend binding name
	 *        into state/llm-backends.yml; null = the default backend. Resolved
	 *        (and possibly refused) by LLMClient\BindingResolver, per ruling 1.
	 * @param array<string, mixed> $gdpr     the agent's Article-30 record
	 *        (feat 57168ff8). Carried on the value object because the binding
	 *        resolver READS it — a routing the register does not declare is a
	 *        compliance defect, and the check must see the same file the
	 *        register generator sweeps.
	 */
	public function __construct(
		public readonly string $name,
		public readonly int $version,
		public readonly string $description,
		public readonly string $modelPrimaryUri,
		public readonly ?string $modelFallbackUri,
		/** Optional separate model for the outcome Grader; null = share the agent's. */
		public readonly ?string $modelGraderUri,
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
		public readonly array $subscriptions,
		public readonly array $metadata,
		public readonly string $sourceDir,
		public readonly ?string $backendName = null,
		/**
		 * Per-agent output cap for ONE model call.
		 *
		 * 4096 was the interface default and the only value anything ever
		 * passed. Measured 2026-08-16: the librarian's taxonomy-brief batch
		 * writes ten briefs of 300-12000 characters each and stopped at
		 * `stop_reason: max_tokens` mid-sentence, so it never reached the
		 * POST that is the point of the ceremony. A reading ceremony and a
		 * WRITING ceremony do not want the same budget, and the agent is
		 * the level that knows which it is.
		 */
		public readonly int $maxOutputTokens = 4096,
		public readonly array $gdpr = [],
		/**
		 * `outcomes.gateset` — the named gate set in state/judge-sets.yml whose
		 * exit code decides whether this agent's run is satisfied. Required
		 * wherever an outcome loop exists: an outcome with no oracle is a model
		 * marking its own work.
		 */
		public readonly ?string $gateset = null,
		/**
		 * `outcomes.deliverable` — the event type this ceremony must have
		 * FILED before its gate set may certify it.
		 *
		 * Measured 2026-08-29, session 53de6409: the surveyor passed both
		 * judges and was `outcome_satisfied` having posted nothing at all.
		 * The gate set judges the TREE (nos-smoke, cortex-corpus-diff); it has
		 * no opinion about whether the agent did its own work, and a prose
		 * report in a transcript is not an artifact anyone can check.
		 *
		 * Null means the ceremony's deliverable is the tree itself (a writer
		 * whose gate set reads what it wrote). Naming a type here says: the
		 * work is an artifact, and it must EXIST, keyed to this session.
		 */
		public readonly ?string $deliverableEvent = null,
		/**
		 * 'loop' (tool-use / outcome, the default) or 'one_shot': bind, ONE
		 * call, validate the emitted chain against $oneShotSchema, record.
		 * The ops plane measures small local models, and a loop measures the
		 * harness as much as the model.
		 */
		public readonly string $mode = 'loop',
		/** Decoded one_shot.schema_path — the shape the single answer must have. */
		public readonly array $oneShotSchema = [],
	) {
	}

	public function isOneShot(): bool
	{
		return $this->mode === 'one_shot';
	}

	public function isCoordinator(): bool
	{
		return $this->multiagentType === 'coordinator';
	}

	/**
	 * An outcome exists when an ORACLE exists. Was `rubric !== null`, which
	 * made the loop turn on a document the graded model could also read.
	 */
	public function hasOutcome(): bool
	{
		return $this->gateset !== null;
	}

	public function hasGrader(): bool
	{
		return $this->modelGraderUri !== null;
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

/**
 * One subscribe: entry. Declares that the owning agent wants to be re-run
 * whenever an event of $eventType is dispatched whose payload exactly
 * matches every (key, value) pair in $filter. SubscriptionRegistrar maps
 * each spec onto a row in agent_subscriptions; WebhookDispatcher applies
 * the filter at fire-time and refuses self-loops by inspecting payload.
 *
 * `filter` uses **exact-string equality only** — no regex, no glob, no
 * eval. Locked by tests/anatomy/test_agentkit_webhook_fanout.py.
 */
final class SubscriptionSpec
{
	/**
	 * @param array<string, string> $filter  payload-field => expected-value
	 */
	public function __construct(
		public readonly string $eventType,
		public readonly array $filter = [],
		public readonly string $triggerArg = 'prompt',
	) {
	}
}
