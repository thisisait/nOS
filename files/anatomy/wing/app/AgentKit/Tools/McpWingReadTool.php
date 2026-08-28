<?php

declare(strict_types=1);

namespace App\AgentKit\Tools;

use App\AgentKit\LLMClient\ToolSchema;

/**
 * The read plane of Wing's /api/v1 surface: GET, scope `wing.read`, the whole
 * route table. A POST through here is refused by the base class, whatever the
 * model asks for.
 */
final class McpWingReadTool extends McpWingTool
{
	public function id(): string
	{
		return 'mcp-wing-read';
	}

	public function requiredScopes(): array
	{
		return ['mcp.tool_use', 'wing.read'];
	}

	protected function verb(): string
	{
		return 'GET';
	}

	public function schema(): ToolSchema
	{
		return new ToolSchema(
			name: 'mcp_wing_read',
			description: 'GET a Wing /api/v1/* path. Use for health probes, event queries, ' .
				'pulse-job lookups, system listings. Path must start with /api/v1/. ' .
				'Returns up to 16 KiB of the JSON response body verbatim. This tool cannot ' .
				'write — writing is mcp_wing_write, a separate tool with its own scope.',
			inputSchema: [
				'type' => 'object',
				'required' => ['path'],
				'properties' => [
					'method' => [
						'type' => 'string',
						'enum' => ['GET'],
					],
					'path' => [
						'type' => 'string',
						'description' => 'Path beginning with /api/v1/.',
					],
				],
			],
		);
	}
}
