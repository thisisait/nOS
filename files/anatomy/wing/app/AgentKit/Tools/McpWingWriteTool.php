<?php

declare(strict_types=1);

namespace App\AgentKit\Tools;

use App\AgentKit\LLMClient\ToolSchema;

/**
 * The write plane: POST, scope `wing.write`, and only the routes an agent was
 * measured calling. The grant is traceable —
 * docs/plans/rsi-research/artifacts/wing-write-grants.json holds every POST any
 * agent ever made through the un-split tool, and the span that measurement
 * covers, so nobody has to trust that this list is the right one.
 */
final class McpWingWriteTool extends McpWingTool
{
	/**
	 * Grandfathered from measured use, not from what looks reasonable. Both
	 * agents that ever wrote called this one route, so the per-agent grant and
	 * this list are the same list; a second route belongs here only once an
	 * operator decides to add it, never because a prompt asks for it.
	 */
	private const GRANTED_ROUTES = ['/api/v1/events'];

	public function id(): string
	{
		return 'mcp-wing-write';
	}

	public function requiredScopes(): array
	{
		return ['mcp.tool_use', 'wing.write'];
	}

	protected function verb(): string
	{
		return 'POST';
	}

	protected function allowedPaths(): array
	{
		return self::GRANTED_ROUTES;
	}

	public function schema(): ToolSchema
	{
		return new ToolSchema(
			name: 'mcp_wing_write',
			description: 'POST to a granted Wing route. Granted: ' .
				implode(', ', self::GRANTED_ROUTES) . '. Use it to file your report as an ' .
				'event. Any other path is refused — ask the operator rather than retrying.',
			inputSchema: [
				'type' => 'object',
				'required' => ['path', 'body'],
				'properties' => [
					'method' => [
						'type' => 'string',
						'enum' => ['POST'],
					],
					'path' => [
						'type' => 'string',
						'enum' => self::GRANTED_ROUTES,
					],
					'body' => [
						'type' => 'object',
						'description' => 'JSON body.',
					],
				],
			],
		);
	}
}
