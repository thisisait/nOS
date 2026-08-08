<?php

declare(strict_types=1);

namespace App\Model;

use Nette\Database\Explorer;

/**
 * Persistence for agent_questions — the write half of the A9 notification
 * spine. See the table's own comment in db/schema-extensions.sql for why it
 * exists; this class exists to make its three properties impossible to get
 * wrong from a caller.
 *
 * The one rule that governs every method here: NEVER read-then-write. Two
 * operators answering the same question from two channels within the same
 * second is the normal case for this table. Every state transition is a single
 * conditional UPDATE whose WHERE clause carries the precondition, and the
 * affected-row count is the verdict.
 */
/**
 * ── HOW THIS RELATES TO A11 `/approvals` (decided 2026-08-08) ────────────────
 *
 * A11 stores agent-action approvals as `events` rows — `agent_approval_request`
 * paired with `agent_approval_decision` on `actor_action_id` — and
 * `test_approval_queue_event_backed.py` forbids a dedicated table, on the
 * correct ground that events are the single source of truth for audit and a
 * side table would duplicate lineage. That gate also names its own trigger for
 * revisiting: "when a SECOND surface programmatically gates on approvals".
 * `agents-inbox` is that surface, so the deferral has come due.
 *
 * THE SPLIT THAT RESOLVES IT, and it is not a compromise:
 *
 *   events          the LINEAGE. Append-only, never edited, never deleted.
 *                   Every ask and every answer emits one. This is what audit,
 *                   the judges and SERE read.
 *   agent_questions the RESOLUTION. Exactly one row per question, holding the
 *                   fact of whether it is still open.
 *
 * An append-only log CANNOT enforce resolve-once — that is not an opinion about
 * style, it is what append-only means. A11 shows the consequence: two operators
 * clicking Approve at the same moment both append a decision event, and
 * `listPendingApprovals` merely filters out anything that has *a* decision. If
 * one approved and one rejected, the queue reads "decided" and which one won is
 * whichever the reader happens to see first. Nothing detects it.
 *
 * So the table is not a second copy of the lineage. It holds the ONE fact the
 * lineage structurally cannot: is this still open, and who closed it. The events
 * are emitted BY this class, from inside the same transaction-shaped path that
 * decides the answer, so the two cannot drift — which is the risk the A11 gate
 * was actually protecting against.
 *
 * An approval is therefore a question with `kind='approval'`. There is nothing
 * to migrate: measured 2026-08-08, the live estate holds ZERO
 * `agent_approval_*` events, so A11's surface has never once been used.
 */
final class AgentQuestionRepository
{
	/** Answer accepted. */
	public const ANSWER_OK = 'ok';
	/** Someone else got there first — their answer stands. */
	public const ANSWER_ALREADY = 'already_answered';
	/** The deadline passed; the agent has already moved on. */
	public const ANSWER_EXPIRED = 'expired';
	/** No such question, or the reply token does not match. */
	public const ANSWER_UNKNOWN = 'unknown';

	private const KINDS = ['approval', 'question', 'choice'];

	public function __construct(
		private Explorer $db,
		private EventRepository $events,
		private NotificationRepository $notifications,
	) {
	}

	/**
	 * Emit the lineage row for a question transition.
	 *
	 * IN-PROCESS, not an HMAC-signed POST to /api/v1/events. A11's
	 * `ApprovalsPresenter::postDecision` takes the HTTP path and then does
	 * `curl_exec($ch);` — discarding the result — with an earlier
	 * `if ($secret === '') { return; }`. So an operator's decision could be
	 * dropped in two different silent ways, and on 2026-08-08 the estate spent
	 * an unknown period with `wing_events_hmac_secret` holding a RETIRED key,
	 * under which every such POST 401'd. Nothing would have said so.
	 *
	 * Writing through the repository removes the signature, the network hop and
	 * both silences: an insert either happens or throws.
	 *
	 * `actor_action_id` is the question uuid, so one
	 * `SELECT ... WHERE actor_action_id=?` reconstructs ask → answer, which is
	 * the A10 lineage contract the rest of the estate already reads.
	 *
	 * @param array<string, mixed> $result
	 */
	private function emit(string $type, string $uuid, string $actorId, array $result): void
	{
		$this->events->insert([
			'ts'              => gmdate('c'),
			'type'            => $type,
			'run_id'          => 'question-' . $uuid,
			'source'          => 'wing',
			'actor_id'        => $actorId,
			'actor_action_id' => $uuid,
			'acted_at'        => gmdate('c'),
			'result'          => $result,
		]);
	}

	/**
	 * File a question. Returns [uuid, reply_token] — the token is returned in
	 * PLAINTEXT exactly once, here, and only its SHA-256 is stored. A caller
	 * that loses it cannot recover it, which is the point: the notification
	 * that carries it to the operator is the only other copy.
	 *
	 * @param array<int, string>|null  $options
	 * @param array<string, mixed>|null $context
	 * @return array{uuid: string, reply_token: string}
	 */
	public function ask(
		string $agentName,
		string $prompt,
		string $kind = 'approval',
		?array $options = null,
		string $severity = 'medium',
		?string $sessionUuid = null,
		?int $ttlSeconds = null,
		?string $defaultOnExpiry = null,
		?array $context = null,
	): array {
		if (!in_array($kind, self::KINDS, true)) {
			throw new \InvalidArgumentException("unknown question kind: {$kind}");
		}
		if (trim($prompt) === '') {
			throw new \InvalidArgumentException('a question with no prompt cannot be answered');
		}
		// A `choice` with no options is a free-text question wearing a label
		// the UI would render as buttons that do not exist.
		if ($kind === 'choice' && (!$options || count($options) < 2)) {
			throw new \InvalidArgumentException('kind=choice requires at least two options');
		}
		// An expiry with no stated default is a silent decision: the run ends
		// up doing SOMETHING when nobody answers, and nothing recorded what.
		if ($ttlSeconds !== null && $defaultOnExpiry === null) {
			throw new \InvalidArgumentException(
				'a question with a deadline must state default_on_expiry — '
				. 'otherwise the timeout picks an outcome nobody wrote down');
		}

		$uuid  = $this->uuid4();
		$token = bin2hex(random_bytes(32));
		$expiresAt = $ttlSeconds !== null
			? gmdate('Y-m-d\TH:i:s\Z', time() + $ttlSeconds)
			: null;

		$this->db->table('agent_questions')->insert([
			'uuid'              => $uuid,
			'session_uuid'      => $sessionUuid,
			'agent_name'        => $agentName,
			'kind'              => $kind,
			'prompt'            => $prompt,
			'context_json'      => $context !== null ? json_encode($context, JSON_UNESCAPED_UNICODE) : null,
			'options_json'      => $options !== null ? json_encode(array_values($options), JSON_UNESCAPED_UNICODE) : null,
			'severity'          => $severity,
			'reply_token_sha'   => hash('sha256', $token),
			'status'            => 'open',
			'expires_at'        => $expiresAt,
			'default_on_expiry' => $defaultOnExpiry,
			'actor_id'          => 'agent:' . $agentName,
			'actor_action_id'   => $sessionUuid,
		]);

		// An `approval` emits A11's own event type, so every audit query keyed
		// on it keeps working unchanged now that /approvals itself is retired.
		// Other kinds get their own type.
		$this->emit(
			$kind === 'approval' ? 'agent_approval_request' : 'agent_question_asked',
			$uuid,
			'agent:' . $agentName,
			[
				'kind'       => $kind,
				'prompt'     => $prompt,
				'severity'   => $severity,
				'options'    => $options,
				'expires_at' => $expiresAt,
				// NO reply_token. Events are read by /timeline, by the judges and
				// by SERE; the lineage must be safe to read widely, which is the
				// same rule that keeps credentials out of notifications.
			],
		);

		// THE NOTIFICATION IS INSERTED HERE, NOT AT A CALL SITE. Until
		// 2026-08-08 it lived in Api\InboxPresenter only, which meant the
		// flagship path — AskOperatorTool, which talks to this repository
		// directly so the token never rides an HTTP response — filed questions
		// NOBODY WAS TOLD ABOUT. A question with a deadline then decides
		// itself, and nothing said a human was never asked. Same argument as
		// emit() above: what must not drift from the ask lives with the ask.
		//
		// WHAT IT CARRIES: that a question exists, and where to answer it.
		// `click_url` becomes ntfy's `Click` header (deliver_ntfy reads
		// metadata.click_url), pointing at /inbox — the reader authenticates
		// THERE (Authentik forward-auth, Tier-1: answering authorises an
		// agent). NEVER the reply token, in the URL or anywhere else in this
		// row: notifications.metadata_json is returned verbatim by
		// GET /api/v1/notifications to any bearer caller, including any agent
		// holding mcp-wing — that leak shipped once and was caught by
		// adversarial review hours later. Empty WING_PUBLIC_URL → null →
		// no Click header, never a fabricated URL.
		//
		// A QUESTION IS NEVER QUIETER THAN `high`. The severity the agent
		// declares describes what it is asking ABOUT; the ask itself is always
		// something a human must see, and NotificationRepository's default
		// channel map only reaches ntfy at high/critical. An `info` question
		// routed inbox-only would be one unread row in a web UI while a run
		// blocks.
		$publicUrl = rtrim((string) (getenv('WING_PUBLIC_URL') ?: ''), '/');
		$this->notifications->insert([
			'severity'        => in_array($severity, ['critical', 'high'], true) ? $severity : 'high',
			'title'           => 'Agent asks: ' . $agentName,
			'body'            => $prompt,
			'origin_plugin'   => 'agent-inbox',
			'origin_agent'    => $agentName,
			'actor_id'        => 'agent:' . $agentName,
			'actor_action_id' => $sessionUuid,
			'metadata'        => [
				'question_uuid'  => $uuid,
				'kind'           => $kind,
				'options'        => $options,
				'asked_severity' => $severity,
				'expires_at'     => $expiresAt,
				'click_url'      => $publicUrl !== '' ? $publicUrl . '/inbox' : null,
			],
		]);

		return ['uuid' => $uuid, 'reply_token' => $token];
	}

	/**
	 * Answer a question. THE resolve-once path.
	 *
	 * One UPDATE carries every precondition — still open, not past its
	 * deadline, token matches — so two simultaneous callers cannot both
	 * succeed regardless of how the database schedules them. The loser learns
	 * WHY it lost from a follow-up read, which is safe precisely because the
	 * write already happened or already failed.
	 *
	 * @return array{result: string, question: array<string,mixed>|null}
	 */
	public function answer(
		string $uuid,
		string $replyToken,
		string $answer,
		string $answeredBy,
		string $via = 'api',
	): array {
		$now = gmdate('Y-m-d\TH:i:s\Z');

		$affected = $this->db->table('agent_questions')
			->where('uuid', $uuid)
			->where('reply_token_sha', hash('sha256', $replyToken))
			->where('status', 'open')
			// SQL-side deadline: a sweeper would leave a window in which a
			// question is expired in fact and open in the table.
			->where('expires_at IS NULL OR expires_at > ?', $now)
			->update([
				'answer'       => $answer,
				'answered_by'  => $answeredBy,
				'answered_via' => $via,
				'answered_at'  => $now,
				'status'       => 'answered',
				'updated_at'   => $now,
			]);

		if ($affected === 1) {
			$row = $this->find($uuid);
			// Emitted only on the WINNING write. The conditional UPDATE above is
			// what makes that meaningful: a loser never reaches this line, so the
			// lineage carries exactly one decision per question — which is the
			// property A11's append-only path cannot offer, because there every
			// caller appends and the last one to be read wins.
			$this->emit(
				($row['kind'] ?? '') === 'approval'
					? 'agent_approval_decision'
					: 'agent_question_answered',
				$uuid,
				$answeredBy,
				[
					'verdict'           => $answer,
					'operator_username' => $answeredBy,
					'via'               => $via,
					'kind'              => $row['kind'] ?? null,
					'waited_seconds'    => isset($row['created_at'])
						? max(0, strtotime($now) - strtotime((string) $row['created_at']))
						: null,
				],
			);
			return ['result' => self::ANSWER_OK, 'question' => $row];
		}

		// Nothing moved. Say which of the three reasons it was — "it did not
		// work" sends the operator to guess, and the row already knows.
		$row = $this->find($uuid);
		if ($row === null || !hash_equals(
			(string) $row['reply_token_sha'], hash('sha256', $replyToken))) {
			// Same answer for "no such question" and "wrong token", on purpose:
			// distinguishing them turns this endpoint into an oracle for
			// enumerating question ids.
			return ['result' => self::ANSWER_UNKNOWN, 'question' => null];
		}
		if ($row['status'] === 'answered') {
			return ['result' => self::ANSWER_ALREADY, 'question' => $row];
		}
		return ['result' => self::ANSWER_EXPIRED, 'question' => $row];
	}

	/**
	 * Answer as an authenticated operator, with no reply token.
	 *
	 * WHY THIS EXISTS SEPARATELY. The reply token authorises a caller who has no
	 * session — the operator in Telegram at 23:00. Inside Wing the Authentik
	 * forward-auth session IS the authorisation, and it is the stronger of the
	 * two: it names a person, carries their groups, and cannot be lifted out of
	 * a notification. Demanding a token there would mean either showing it in
	 * the UI (a credential on a screen, defeating the point) or storing it
	 * un-hashed (defeating it harder).
	 *
	 * THE RISK THIS METHOD CARRIES, stated because the signature hides it: it
	 * skips the only check that stops an arbitrary caller answering. It is safe
	 * ONLY while every call site is behind an RBAC gate. `InboxPresenter` sets
	 * `$minAccessTier = 1` for exactly this reason, and
	 * `test_only_a_gated_presenter_answers_without_a_token.py` refuses any new
	 * caller that is not similarly gated. Do not call it from an API presenter
	 * that authenticates with a bearer token — a service token is not a person,
	 * and "who approved this" must name someone.
	 *
	 * Everything else — resolve-once, the deadline in the WHERE clause, the
	 * single decision event on the winning write — is identical, because it is
	 * the same UPDATE.
	 *
	 * @return array{result: string, question: array<string,mixed>|null}
	 */
	public function answerAsOperator(
		string $uuid,
		string $answer,
		string $operator,
	): array {
		$now = gmdate('Y-m-d\TH:i:s\Z');

		$affected = $this->db->table('agent_questions')
			->where('uuid', $uuid)
			->where('status', 'open')
			->where('expires_at IS NULL OR expires_at > ?', $now)
			->update([
				'answer'       => $answer,
				'answered_by'  => $operator,
				'answered_via' => 'wing',
				'answered_at'  => $now,
				'status'       => 'answered',
				'updated_at'   => $now,
			]);

		if ($affected === 1) {
			$row = $this->find($uuid);
			$this->emit(
				($row['kind'] ?? '') === 'approval'
					? 'agent_approval_decision'
					: 'agent_question_answered',
				$uuid,
				$operator,
				[
					'verdict'           => $answer,
					'operator_username' => $operator,
					'via'               => 'wing',
					'kind'              => $row['kind'] ?? null,
					'waited_seconds'    => isset($row['created_at'])
						? max(0, strtotime($now) - strtotime((string) $row['created_at']))
						: null,
				],
			);
			return ['result' => self::ANSWER_OK, 'question' => $row];
		}

		$row = $this->find($uuid);
		if ($row === null) {
			return ['result' => self::ANSWER_UNKNOWN, 'question' => null];
		}
		return [
			'result'   => $row['status'] === 'answered' ? self::ANSWER_ALREADY : self::ANSWER_EXPIRED,
			'question' => $row,
		];
	}

	/**
	 * What the asking agent polls. Returns the row plus a resolved verdict:
	 * an open question past its deadline reports `expired` WITHOUT waiting for
	 * anything to sweep it, and carries the default the asker declared.
	 *
	 * @return array<string, mixed>|null
	 */
	public function poll(string $uuid): ?array
	{
		$row = $this->find($uuid);
		if ($row === null) {
			return null;
		}
		if ($row['status'] === 'open' && $this->isPastDeadline($row)) {
			$row['status'] = 'expired';
			$row['answer'] = $row['default_on_expiry'];
			$row['expired_by_deadline'] = true;
		}
		return $row;
	}

	/**
	 * Open questions, newest last so a reader answers the oldest first.
	 * Past-deadline rows are excluded — they are not open, whatever the column
	 * says, and offering them to an operator invites an answer nobody reads.
	 *
	 * @return array<int, array<string, mixed>>
	 */
	public function listOpen(?string $agentName = null, int $limit = 100): array
	{
		$q = $this->db->table('agent_questions')
			->where('status', 'open')
			->order('created_at ASC')
			->limit($limit);
		if ($agentName !== null) {
			$q->where('agent_name', $agentName);
		}
		$out = [];
		foreach ($q->fetchAll() as $row) {
			$r = $this->hydrate($row);
			if (!$this->isPastDeadline($r)) {
				$out[] = $this->public($r);
			}
		}
		return $out;
	}

	/**
	 * Badge count: open questions not past their deadline. The WHERE mirrors
	 * listOpen()'s deadline exclusion exactly, so the number on the nav tab
	 * can never disagree with the rows on the page. (Successor of the A11
	 * badge, which counted unpaired agent_approval_request events.)
	 */
	public function countOpen(): int
	{
		return $this->db->table('agent_questions')
			->where('status', 'open')
			->where('expires_at IS NULL OR expires_at > ?', gmdate('Y-m-d\TH:i:s\Z'))
			->count('*');
	}

	/** Withdraw a question the agent no longer needs answered. */
	public function cancel(string $uuid, string $reason = ''): bool
	{
		return $this->db->table('agent_questions')
			->where('uuid', $uuid)
			->where('status', 'open')
			->update([
				'status'      => 'cancelled',
				'answer'      => $reason !== '' ? $reason : null,
				'updated_at'  => gmdate('Y-m-d\TH:i:s\Z'),
			]) === 1;
	}

	/**
	 * Strip the token hash. Every path that hands a row to a caller goes
	 * through here — a credential does not leave this class, not even hashed.
	 *
	 * @param array<string, mixed> $row
	 * @return array<string, mixed>
	 */
	public function public(array $row): array
	{
		unset($row['reply_token_sha']);
		return $row;
	}

	/** @return array<string, mixed>|null */
	private function find(string $uuid): ?array
	{
		$row = $this->db->table('agent_questions')->where('uuid', $uuid)->fetch();
		return $row === null ? null : $this->hydrate($row);
	}

	/** @return array<string, mixed> */
	private function hydrate(mixed $row): array
	{
		return (array) $row->toArray();
	}

	/** @param array<string, mixed> $row */
	private function isPastDeadline(array $row): bool
	{
		$exp = $row['expires_at'] ?? null;
		return is_string($exp) && $exp !== '' && $exp <= gmdate('Y-m-d\TH:i:s\Z');
	}

	private function uuid4(): string
	{
		$b = random_bytes(16);
		$b[6] = chr((ord($b[6]) & 0x0f) | 0x40);
		$b[8] = chr((ord($b[8]) & 0x3f) | 0x80);
		return vsprintf('%s%s-%s-%s-%s-%s%s%s', str_split(bin2hex($b), 4));
	}
}
