<?php

declare(strict_types=1);

namespace App\AgentKit\Outcome;

use App\AgentKit\LLMClient\LLMClientInterface;
use App\AgentKit\LLMClient\Message;

/**
 * LLM-as-judge grader — FEEDBACK ONLY. It does not decide satisfaction; the
 * agent's declared gate set does (GateOracle). A separate LLM call evaluates
 * the artifact against the rubric in an isolated context window, and an agent
 * that declares no `model.grader` gets no call here at all.
 *
 * Output discipline: strict JSON
 *   {"result": "satisfied|needs_revision|failed", "feedback": "markdown bullets"}
 * run through the Q9 three-stage contract in OutputRepair — deterministic
 * shape repair, then ONE format-only re-ask, then UNPARSEABLE.
 */
final class Grader
{
	private const RESULT_SATISFIED       = 'satisfied';
	private const RESULT_NEEDS_REVISION  = 'needs_revision';
	private const RESULT_FAILED          = 'failed';

	private const SYSTEM_TEMPLATE = <<<MD
		You are an outcome grader. You evaluate the agent's most recent work
		against the rubric below. You CANNOT see the agent's reasoning, only
		the artifact + its conversation transcript.

		Return STRICT JSON, nothing else. Example:
		{"result": "needs_revision", "feedback": "- Missing 'Discount Rate' section\\n- Revenue projections only cover 3 years; rubric requires 5"}

		Allowed result values:
		- satisfied: every rubric criterion is met
		- needs_revision: at least one criterion is missing or wrong; feedback
		  must call out which ones
		- failed: rubric does not apply to the task at all (mismatch)

		Rubric:
		{{RUBRIC}}
		MD;

	public function __construct(
		private readonly LLMClientInterface $llm,
	) {
	}

	/**
	 * The ONLY construction path, so "no grader declared" cannot mean "grader
	 * on the proposer's own client". That fallback stood in Runner until
	 * 2026-08-29 and made every ungraded agent its own judge.
	 *
	 * Null in, null out, and the resolver is never called — a caller with no
	 * `model.grader` makes no grader call at all. The gate set is what says
	 * satisfied; the grader, when an agent declares one, only writes feedback.
	 *
	 * @param ?callable(string): LLMClientInterface $clientFor
	 */
	public static function forUri(?string $graderUri, callable $clientFor): ?self
	{
		return $graderUri === null ? null : new self($clientFor($graderUri));
	}

	/**
	 * @param string $taskDescription   from user.define_outcome
	 * @param string $transcript        markdown summary of what the agent did
	 * @return array{result: string, feedback: string, tokens_input: int, tokens_output: int, repaired: bool}
	 */
	public function grade(string $taskDescription, Rubric $rubric, string $transcript): array
	{
		$system = strtr(self::SYSTEM_TEMPLATE, ['{{RUBRIC}}' => $rubric->markdown]);

		$userMessage = "Task: {$taskDescription}\n\nAgent transcript:\n{$transcript}";

		$totalIn = 0;
		$totalOut = 0;
		$response = $this->llm->send($system, [Message::userText($userMessage)], [], 1024);
		$totalIn += $response->tokensInput;
		$totalOut += $response->tokensOutput;
		$text = trim($response->textOutput());

		// Q9: shape repair first (no model), then ONE format-only re-ask, then
		// UNPARSEABLE. The old shape was three full re-grades, each free to
		// reconsider the verdict while it was "fixing the format".
		$parsed = OutputRepair::parse($text, function (string $original) use (&$totalIn, &$totalOut): string {
			$retry = $this->llm->send(
				'You reformat. You do not evaluate, summarise or change wording.',
				[Message::userText(
					"The content below was meant to be strict JSON of the shape "
					. '{"result": "...", "feedback": "..."} and is not. Return the SAME '
					. "content as strict JSON — no markdown fences, no preamble, no "
					. "edits to the wording.\n\n" . $original
				)],
				[],
				1024,
			);
			$totalIn += $retry->tokensInput;
			$totalOut += $retry->tokensOutput;
			return trim($retry->textOutput());
		});
		$repaired = $parsed['status'] === OutputRepair::REPAIRED;

		if ($parsed['status'] === OutputRepair::UNPARSEABLE) {
			return [
				'result' => self::RESULT_FAILED,
				'feedback' => 'UNPARSEABLE: the grader returned no usable JSON after the '
					. 'shape parser and one format-only re-ask: ' . substr($text, 0, 500),
				'tokens_input' => $totalIn,
				'tokens_output' => $totalOut,
				'repaired' => false,
			];
		}

		$decoded = $parsed['value'] ?? [];
		$result = $decoded['result'] ?? '';
		if (!in_array($result, [self::RESULT_SATISFIED, self::RESULT_NEEDS_REVISION, self::RESULT_FAILED], true)) {
			// A bad enum is a CONTENT fault, not a shape one, so it gets no
			// re-ask: the second answer would be free to differ from the first.
			// The FEEDBACK still travels — measured 2026-08-27, a grader that
			// said "unsatisfied" instead of "needs_revision" had its whole
			// critique thrown away for one word outside the enum.
			return [
				'result' => self::RESULT_FAILED,
				'feedback' => trim((string) ($decoded['feedback'] ?? '')) . "\n\n"
					. '(grader returned result=' . var_export($result, true)
					. ', not one of satisfied|needs_revision|failed)',
				'tokens_input' => $totalIn,
				'tokens_output' => $totalOut,
				'repaired' => $repaired,
			];
		}
		return [
			'result' => $result,
			'feedback' => (string) ($decoded['feedback'] ?? ''),
			'tokens_input' => $totalIn,
			'tokens_output' => $totalOut,
			'repaired' => $repaired,
		];
	}
}
