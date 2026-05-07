<?php

declare(strict_types=1);

namespace App\AgentKit\Tools;

use App\AgentKit\LLMClient\ToolSchema;

/**
 * Contract for AgentKit tools. Tools are registered by id (matching the
 * agent.yml::tools[].id field). The runner instantiates each declared tool
 * once at session start, then calls execute() for every tool_use block
 * the LLM emits.
 *
 * Implementations must:
 *  - declare a schema() in vendor-neutral ToolSchema form
 *  - validate input from $input strictly — bad input is the agent's fault,
 *    not the platform's, but tools must still fail-soft (return is_error=true)
 *    so the LLM can self-correct rather than crashing the session
 *  - keep execute() side-effects scoped to the declared capability_scopes
 *    of the agent (enforced by the runner by checking the tool's required
 *    scopes against agent.audit.capability_scopes at instantiation time).
 */
interface ToolInterface
{
	public function id(): string;

	public function schema(): ToolSchema;

	/**
	 * Required Authentik / nOS capability scopes. Runner refuses to load the
	 * tool if the agent's audit.capability_scopes don't cover all of these.
	 *
	 * @return array<int, string>
	 */
	public function requiredScopes(): array;

	/**
	 * @param array<string, mixed> $input
	 * @return ToolResult
	 */
	public function execute(array $input, ToolContext $context): ToolResult;
}
