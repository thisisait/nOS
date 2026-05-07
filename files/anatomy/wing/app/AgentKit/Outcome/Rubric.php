<?php

declare(strict_types=1);

namespace App\AgentKit\Outcome;

/**
 * A markdown rubric loaded from agent.yml::outcomes.rubric_path.
 *
 * The grader passes the full markdown verbatim into its system prompt. We
 * keep the source path so the audit row can record which rubric file +
 * git revision was used (operators may evolve rubrics; reruns must be
 * reproducible against the snapshot the agent ran with).
 */
final class Rubric
{
	public function __construct(
		public readonly string $markdown,
		public readonly string $sourcePath,
	) {
	}
}
