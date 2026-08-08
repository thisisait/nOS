<?php

declare(strict_types=1);

namespace App\Presenters\Api;

use App\Model\AgentQuestionRepository;
use App\Model\NotificationRepository;
use Nette\Http\IResponse;

/**
 * The agent inbox — the write half of the A9 notification spine.
 *
 * POST /api/v1/inbox/questions              — an agent asks; returns uuid + reply_token
 * GET  /api/v1/inbox/questions              — open questions (operator/UI)
 * GET  /api/v1/inbox/questions/<uuid>       — poll; the asking agent's blocking loop
 * POST /api/v1/inbox/questions/<uuid>/answer — answer it (resolve-once)
 * POST /api/v1/inbox/questions/<uuid>/cancel — the agent withdraws it
 *
 * WHY THE ANSWER PATH TAKES A TOKEN AND NOT A SESSION. The operator is in
 * Telegram at 23:00, not in a browser. `reply_token` is minted per question,
 * returned exactly once at ask time, stored only as a SHA-256, and carried to
 * the operator by the notification itself. It authorises answering ONE
 * question and nothing else.
 *
 * The two things this presenter refuses to do, both deliberate:
 *
 *   IT DOES NOT READ-THEN-WRITE. Every verdict comes from
 *   AgentQuestionRepository's conditional UPDATE. Two operators answering the
 *   same question from two channels in the same second is the normal case
 *   here, and a presenter that checked-then-acted would accept both.
 *
 *   IT DOES NOT REPORT A LOST RACE AS SUCCESS. The second answerer gets 409
 *   and the answer that won. A reply that silently evaporates is worse than
 *   one that is refused, because the operator believes they decided.
 *
 * Filed by the TechNosIdeas audits, 2026-08-08 (roadmap row `agents-inbox`).
 */
final class InboxPresenter extends BaseApiPresenter
{
	public function __construct(
		private AgentQuestionRepository $questions,
		private NotificationRepository $notifications,
	) {
	}

	/**
	 * POST /api/v1/inbox/questions
	 *   body: {agent_name, prompt, kind?, options?, severity?, session_uuid?,
	 *          ttl_seconds?, default_on_expiry?, context?}
	 * GET  /api/v1/inbox/questions[?agent=<name>]
	 */
	public function actionQuestions(?string $uuid = null): void
	{
		if ($uuid !== null) {
			$this->requireMethod('GET');
			$row = $this->questions->poll($uuid);
			if ($row === null) {
				$this->sendError('Question not found', IResponse::S404_NotFound);
			}
			$this->sendSuccess($this->questions->public($row));
		}

		if ($this->getHttpRequest()->getMethod() === 'GET') {
			$agent = $this->getHttpRequest()->getQuery('agent');
			$this->sendSuccess([
				'questions' => $this->questions->listOpen(
					is_string($agent) && $agent !== '' ? $agent : null
				),
			]);
		}

		$this->requireMethod('POST');
		$b = $this->getJsonBody();
		foreach (['agent_name', 'prompt'] as $required) {
			if (!isset($b[$required]) || trim((string) $b[$required]) === '') {
				$this->sendError("Missing required field: {$required}");
			}
		}

		try {
			$made = $this->questions->ask(
				agentName:       (string) $b['agent_name'],
				prompt:          (string) $b['prompt'],
				kind:            (string) ($b['kind'] ?? 'approval'),
				options:         isset($b['options']) && is_array($b['options']) ? $b['options'] : null,
				severity:        (string) ($b['severity'] ?? 'medium'),
				sessionUuid:     isset($b['session_uuid']) ? (string) $b['session_uuid'] : null,
				ttlSeconds:      isset($b['ttl_seconds']) ? (int) $b['ttl_seconds'] : null,
				defaultOnExpiry: isset($b['default_on_expiry']) ? (string) $b['default_on_expiry'] : null,
				context:         isset($b['context']) && is_array($b['context']) ? $b['context'] : null,
			);
		} catch (\InvalidArgumentException $e) {
			// The repository's argument checks are contract, not defence: each
			// one names a way an unanswerable question could be filed.
			$this->sendError($e->getMessage());
		}

		// The notification is not decoration — it is the ONLY copy of the reply
		// token that reaches a human, and a question nobody is told about sits
		// open until its deadline and then decides itself.
		//
		// A QUESTION IS NEVER QUIETER THAN `high`. The severity the agent
		// declares describes what it is asking ABOUT; the ask itself is always
		// something a human must see, and NotificationRepository's own default
		// map only reaches ntfy at high/critical. An `info` question routed
		// inbox-only would be one unread row in a web UI while a run blocks —
		// the exact failure the map's docblock records from the Pulse path.
		$severity = (string) ($b['severity'] ?? 'medium');
		$this->notifications->insert([
			'severity'        => in_array($severity, ['critical', 'high'], true) ? $severity : 'high',
			'title'           => 'Agent asks: ' . (string) $b['agent_name'],
			'body'            => (string) $b['prompt'],
			'origin_plugin'   => 'agent-inbox',
			'origin_agent'    => (string) $b['agent_name'],
			'actor_id'        => 'agent:' . (string) $b['agent_name'],
			'actor_action_id' => isset($b['session_uuid']) ? (string) $b['session_uuid'] : null,
			'metadata'        => [
				'question_uuid'    => $made['uuid'],
				'reply_token'      => $made['reply_token'],
				'kind'             => (string) ($b['kind'] ?? 'approval'),
				'options'          => $b['options'] ?? null,
				'asked_severity'   => $severity,
				'expires_at'       => isset($b['ttl_seconds'])
					? gmdate('Y-m-d\TH:i:s\Z', time() + (int) $b['ttl_seconds'])
					: null,
			],
		]);

		$this->sendCreated($made);
	}

	/**
	 * POST /api/v1/inbox/questions/<uuid>/answer
	 *   body: {reply_token, answer, answered_by?, via?}
	 */
	public function actionAnswer(string $uuid): void
	{
		$this->requireMethod('POST');
		$b = $this->getJsonBody();
		foreach (['reply_token', 'answer'] as $required) {
			if (!isset($b[$required]) || (string) $b[$required] === '') {
				$this->sendError("Missing required field: {$required}");
			}
		}

		$verdict = $this->questions->answer(
			uuid:        $uuid,
			replyToken:  (string) $b['reply_token'],
			answer:      (string) $b['answer'],
			answeredBy:  (string) ($b['answered_by'] ?? $this->getActorId() ?? 'unknown'),
			via:         (string) ($b['via'] ?? 'api'),
		);

		match ($verdict['result']) {
			AgentQuestionRepository::ANSWER_OK => $this->sendSuccess([
				'result'   => 'ok',
				'question' => $this->questions->public($verdict['question']),
			]),
			// 409, not 200: the caller decided something and their decision did
			// not take effect. Returning the winning answer lets a channel bot
			// say WHAT was decided instead of just "too late".
			AgentQuestionRepository::ANSWER_ALREADY => $this->sendError(
				'Already answered by ' . (string) ($verdict['question']['answered_by'] ?? '?')
				. ': ' . (string) ($verdict['question']['answer'] ?? ''),
				IResponse::S409_Conflict,
			),
			AgentQuestionRepository::ANSWER_EXPIRED => $this->sendError(
				'Deadline passed; the agent proceeded with: '
				. (string) ($verdict['question']['default_on_expiry'] ?? '(no default)'),
				IResponse::S409_Conflict,
			),
			default => $this->sendError('Question not found', IResponse::S404_NotFound),
		};
	}

	/** POST /api/v1/inbox/questions/<uuid>/cancel — body: {reason?} */
	public function actionCancel(string $uuid): void
	{
		$this->requireMethod('POST');
		$b = $this->getJsonBody();
		$ok = $this->questions->cancel($uuid, (string) ($b['reason'] ?? ''));
		if (!$ok) {
			$this->sendError('Not open (already answered, expired or unknown)', IResponse::S409_Conflict);
		}
		$this->sendSuccess(['result' => 'cancelled']);
	}
}
