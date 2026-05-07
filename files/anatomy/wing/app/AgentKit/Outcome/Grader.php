<?php

declare(strict_types=1);

namespace App\AgentKit\Outcome;

use App\AgentKit\LLMClient\LLMClientInterface;
use App\AgentKit\LLMClient\Message;

/**
 * LLM-as-judge grader. Borrowed straight from Anthropic Managed Agents'
 * outcome model — a SEPARATE LLM call evaluates the agent's artifact
 * against the rubric, in an isolated context window so it can't be
 * influenced by the working agent's reasoning.
 *
 * Output discipline: the grader returns strict JSON
 *   {"result": "satisfied|needs_revision|failed", "feedback": "markdown bullets"}
 * — we re-prompt with a strong format reminder if parsing fails. After 2
 * format-failure attempts we treat the iteration as `failed` and move on.
 */
final class Grader
{
	private const RESULT_SATISFIED       = 'satisfied';
	private const RESULT_NEEDS_REVISION  = 'needs_revision';
	private const RESULT_FAILED          = 'failed';

	private const MAX_FORMAT_RETRIES = 2;

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
	 * @param string $taskDescription   from user.define_outcome
	 * @param string $transcript        markdown summary of what the agent did
	 * @return array{result: string, feedback: string, tokens_input: int, tokens_output: int}
	 */
	public function grade(string $taskDescription, Rubric $rubric, string $transcript): array
	{
		$system = strtr(self::SYSTEM_TEMPLATE, ['{{RUBRIC}}' => $rubric->markdown]);

		$userMessage = "Task: {$taskDescription}\n\nAgent transcript:\n{$transcript}";

		$totalIn = 0;
		$totalOut = 0;
		$lastFeedback = '';
		for ($attempt = 0; $attempt <= self::MAX_FORMAT_RETRIES; $attempt++) {
			$messages = [Message::userText($userMessage)];
			if ($attempt > 0) {
				$messages[] = Message::assistantText($lastFeedback);
				$messages[] = Message::userText(
					'Your previous reply was not strict JSON. Reply with ONLY ' .
					'{"result": "...", "feedback": "..."} — no markdown fences, no preamble.'
				);
			}
			$response = $this->llm->send($system, $messages, [], 1024);
			$totalIn += $response->tokensInput;
			$totalOut += $response->tokensOutput;
			$text = trim($response->textOutput());
			$lastFeedback = $text;
			$decoded = $this->parseStrictJson($text);
			if ($decoded === null) {
				continue;
			}
			$result = $decoded['result'] ?? '';
			$feedback = (string) ($decoded['feedback'] ?? '');
			if (in_array($result, [self::RESULT_SATISFIED, self::RESULT_NEEDS_REVISION, self::RESULT_FAILED], true)) {
				return [
					'result' => $result,
					'feedback' => $feedback,
					'tokens_input' => $totalIn,
					'tokens_output' => $totalOut,
				];
			}
		}

		// Format-retry budget exhausted
		return [
			'result' => self::RESULT_FAILED,
			'feedback' => 'grader returned non-conforming output after ' .
				(self::MAX_FORMAT_RETRIES + 1) . ' attempts: ' . substr($lastFeedback, 0, 500),
			'tokens_input' => $totalIn,
			'tokens_output' => $totalOut,
		];
	}

	/**
	 * @return array<string, mixed>|null
	 */
	private function parseStrictJson(string $text): ?array
	{
		// Strip optional ```json fences (defensive — graders sometimes wrap)
		$text = preg_replace('/^```(?:json)?\s*|\s*```$/m', '', $text) ?? $text;
		$text = trim($text);
		if ($text === '') {
			return null;
		}
		$decoded = json_decode($text, true);
		return is_array($decoded) ? $decoded : null;
	}
}
