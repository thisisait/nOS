<?php

declare(strict_types=1);

namespace App\AgentKit\Tools;

use App\AgentKit\LLMClient\ToolSchema;
use App\Model\AgentQuestionRepository;

/**
 * `ask_operator` — the agent-facing half of the inbox (roadmap `agents-inbox`).
 *
 * Until this existed, an unattended run that reached a decision it was not
 * authorised to make had two options: guess, or die. A9 notification fanout is
 * one-way. This tool is the return path.
 *
 * ── THE SECURITY PROPERTY, which is the whole reason this is a tool and not a
 * ── thin wrapper over `mcp_wing`
 *
 * The reply token NEVER reaches the model. `AgentQuestionRepository::ask()`
 * returns it exactly once; the presenter hands it to the notification, which
 * carries it to a human. If the token appeared in a ToolResult, the LLM would
 * hold the credential that authorises answering its own question — and an
 * agent that can approve itself has not been gated, it has been decorated.
 *
 * That is also why this tool talks to the repository directly rather than
 * POSTing to /api/v1/inbox/questions through `mcp_wing`: the HTTP response
 * legitimately contains the token, and any agent with `mcp_wing` could call
 * that endpoint and read it. `mcp_wing` is GET/POST over the whole /api/v1
 * surface, so this is not hypothetical — see the open question at the end.
 *
 * ── WHY IT DOES NOT BLOCK FOR LONG
 *
 * execute() is synchronous inside the LLM loop, and a Pulse-triggered session
 * carries `max_runtime_s` (default 300) after which the daemon SIGKILLs it.
 * A tool that blocked for an hour would not suspend the run — it would get the
 * run killed, losing the session, its context and its audit trail, while the
 * question sat open with nobody aware the asker was gone.
 *
 * So the wait is short and bounded, and an unanswered question is reported as
 * PENDING with its uuid. The agent is expected to end the turn and be resumed;
 * the question outlives the process that asked it, which is the point of
 * putting it in a table.
 *
 * ── PENDING IS NOT NO
 *
 * The one misreading that would make this tool dangerous is an LLM treating
 * "nobody answered yet" as permission, or as refusal. Both are wrong and both
 * are plausible completions. The result text says so in words, every time.
 */
final class AskOperatorTool implements ToolInterface
{
	/** Long enough that an operator who is right there can answer; short
	 *  enough to stay well inside a default 300 s Pulse runtime budget. */
	private const MAX_WAIT_SECONDS = 90;
	private const POLL_INTERVAL_SECONDS = 2;

	public function __construct(
		private readonly AgentQuestionRepository $questions,
	) {
	}

	public function id(): string
	{
		return 'ask-operator';
	}

	public function requiredScopes(): array
	{
		return ['mcp.tool_use', 'inbox.ask'];
	}

	public function schema(): ToolSchema
	{
		return new ToolSchema(
			name: 'ask_operator',
			description:
				'Ask the operator a question and wait briefly for an answer. Use when you have '
				. 'reached a decision you are not authorised to make on your own — applying a '
				. 'change, choosing between options with different risk, or acting on something '
				. 'ambiguous. The question reaches the operator wherever they are. '
				. 'IMPORTANT: if the result says PENDING, nobody has answered yet. That is '
				. 'neither approval nor refusal. Do not proceed as if you had an answer; report '
				. 'the question id and stop. If you set ttl_seconds you MUST set '
				. 'default_on_expiry, because a deadline with no stated default silently picks '
				. 'an outcome nobody wrote down.',
			inputSchema: [
				'type' => 'object',
				'required' => ['prompt'],
				'properties' => [
					'prompt' => [
						'type' => 'string',
						'description' => 'The question, in one or two sentences. State what you '
							. 'will do with each possible answer.',
					],
					'kind' => [
						'type' => 'string',
						'enum' => ['approval', 'question', 'choice'],
						'description' => 'approval = yes/no; choice = pick one of options; '
							. 'question = free text.',
					],
					'options' => [
						'type' => 'array',
						'items' => ['type' => 'string'],
						'description' => 'Required when kind=choice. At least two.',
					],
					'severity' => [
						'type' => 'string',
						'enum' => ['critical', 'high', 'medium', 'low', 'info'],
						'description' => 'How serious the SUBJECT is. The asking itself always '
							. 'notifies at high or above.',
					],
					'ttl_seconds' => [
						'type' => 'integer',
						'description' => 'Deadline. Requires default_on_expiry.',
					],
					'default_on_expiry' => [
						'type' => 'string',
						'description' => 'What you will assume if nobody answers before the '
							. 'deadline. Required with ttl_seconds.',
					],
					'wait_seconds' => [
						'type' => 'integer',
						'description' => 'How long to wait inline, 0-' . self::MAX_WAIT_SECONDS
							. '. Default 0. Longer waits do not suspend the run — they get it '
							. 'killed by the runtime cap.',
					],
					'context' => [
						'type' => 'object',
						'description' => 'What you were doing. Shown to the operator; never executed.',
					],
				],
			],
		);
	}

	public function execute(array $input, ToolContext $context): ToolResult
	{
		$prompt = trim((string) ($input['prompt'] ?? ''));
		if ($prompt === '') {
			return ToolResult::error('prompt is required — a question with no text cannot be answered.');
		}

		$agentName = str_starts_with($context->actorId, 'agent:')
			? substr($context->actorId, strlen('agent:'))
			: $context->actorId;

		try {
			$made = $this->questions->ask(
				agentName:       $agentName,
				prompt:          $prompt,
				kind:            (string) ($input['kind'] ?? 'approval'),
				options:         isset($input['options']) && is_array($input['options'])
					? array_map('strval', $input['options'])
					: null,
				severity:        (string) ($input['severity'] ?? 'medium'),
				sessionUuid:     $context->sessionUuid,
				ttlSeconds:      isset($input['ttl_seconds']) ? (int) $input['ttl_seconds'] : null,
				defaultOnExpiry: isset($input['default_on_expiry'])
					? (string) $input['default_on_expiry'] : null,
				context:         isset($input['context']) && is_array($input['context'])
					? $input['context'] : null,
			);
		} catch (\InvalidArgumentException $e) {
			// Fail SOFT: the contract violations ask() enforces are things the
			// model can fix and retry (a choice with one option, a ttl with no
			// default). Crashing the session would spend a run on a typo.
			return ToolResult::error('Question refused: ' . $e->getMessage());
		}

		$uuid = $made['uuid'];
		// $made['reply_token'] is deliberately DROPPED here and never read
		// again. See this class's docblock: an agent holding its own reply
		// token can approve itself. Pinned by
		// tests/anatomy/test_an_agent_cannot_answer_itself.py.
		unset($made);

		$wait = max(0, min(self::MAX_WAIT_SECONDS, (int) ($input['wait_seconds'] ?? 0)));
		$deadline = time() + $wait;
		do {
			$row = $this->questions->poll($uuid);
			if ($row === null) {
				return ToolResult::error("Question {$uuid} vanished after being filed.");
			}
			if ($row['status'] === 'answered') {
				return ToolResult::ok(
					"ANSWERED by " . (string) ($row['answered_by'] ?? 'operator')
					. " via " . (string) ($row['answered_via'] ?? '?') . ":\n"
					. (string) $row['answer'],
					['question_uuid' => $uuid, 'status' => 'answered'],
				);
			}
			if ($row['status'] === 'expired') {
				return ToolResult::ok(
					"EXPIRED — nobody answered before the deadline. You declared that in this "
					. "case you would assume: " . (string) ($row['answer'] ?? '(no default)')
					. ". Proceed on that basis and say in your report that it was a timeout, "
					. "not a decision.",
					['question_uuid' => $uuid, 'status' => 'expired'],
				);
			}
			if ($row['status'] === 'cancelled') {
				return ToolResult::ok("CANCELLED.", ['question_uuid' => $uuid, 'status' => 'cancelled']);
			}
			if (time() >= $deadline) {
				break;
			}
			sleep(self::POLL_INTERVAL_SECONDS);
		} while (true);

		return ToolResult::ok(
			"PENDING — the operator has been notified and has not answered yet. "
			. "This is NOT approval and NOT refusal. Do not act as though you had an answer. "
			. "End your turn, report that you are blocked, and quote this question id so the "
			. "run can be resumed once it is answered.\nquestion id: {$uuid}",
			['question_uuid' => $uuid, 'status' => 'pending'],
		);
	}
}
