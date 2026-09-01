<?php

declare(strict_types=1);

namespace App\Presenters;

use App\Model\AgentQuestionRepository;
use App\Model\EventRepository;
use App\Model\GitleaksRepository;
use App\Model\NotificationRepository;

/**
 * Wing /inbox — operator attention queue.
 *
 * A9 (2026-05-16) promoted this from a read-only gitleaks/conductor snapshot
 * to the **primary notification surface**. Three sections:
 *
 *   1. Notifications — unread rows from wing.db.notifications. POST mark-read.
 *   2. Secret Findings — unresolved gitleaks_findings (legacy A8.c section).
 *   3. Conductor Runs — recent conductor events (legacy A8.c section).
 *
 * The notifications section is severity-filtered + mark-read-clickable; the
 * other two are read-only deep-links retained because they predate the
 * notifications table and continue to surface useful state that hasn't
 * been promoted to notifications yet.
 *
 * Mark-read is POST-only to prevent CSRF-style accidental reads.
 *
 * 2026-08-08 — SECTION 0: AGENT QUESTIONS, and a tier gate arrives with it.
 *
 * A run that has stopped to ask something is the most urgent thing this page
 * can show: until someone answers, an agent is blocked and, if the question
 * carried a deadline, it will shortly decide for itself. So questions render
 * ABOVE notifications.
 *
 * `$minAccessTier = 1` — this page previously had NO tier gate, which was right
 * when it only showed things. It now DECIDES things: an answer here can
 * authorise an agent to act, which is exactly what A11's `/approvals` gates
 * with `requireSuperAdmin()`. The queue is a little less visible than it was;
 * an approval button that anyone forward-authed could press is worse.
 *
 * Answering takes NO reply token. The token exists for callers with no session
 * — the operator in Telegram at 23:00. Here the Authentik identity is the
 * stronger authorisation: it names a person and cannot be lifted out of a
 * notification. See AgentQuestionRepository::answerAsOperator().
 */
final class InboxPresenter extends BasePresenter
{
	protected string $activeTab = 'inbox';

	/** Answering can authorise an agent action; that is a Tier-1 decision. */
	protected ?int $minAccessTier = 1;

	public function __construct(
		private NotificationRepository $notifications,
		private GitleaksRepository $gitleaks,
		private EventRepository $events,
		private AgentQuestionRepository $questions,
	) {
	}

	/**
	 * `$ref` is an AgentKit session uuid, arriving from a caddy-sessions row in
	 * the face (`inboxHref()` in files/anatomy/face/src/lib/tables/view.ts).
	 *
	 * It NARROWS NOTHING. The queue still shows every open question, because a
	 * deep-link that hid the others would make "nobody is waiting" a function of
	 * which link you followed. What it does is mark the rows this turn asked and
	 * SAY SO WHEN THERE ARE NONE — a ref that matches nothing is the common
	 * case (the question was already answered, or the turn asked nothing), and
	 * a page that looked identical either way is what makes a deep-link feel
	 * broken. Shipped 2026-09-01: the link existed for a day pointing at a
	 * parameter this method did not take, and Nette dropped it silently.
	 */
	public function renderDefault(?string $severity = null, bool $unreadOnly = true, ?string $ref = null): void
	{
		$filters = ['unread_only' => $unreadOnly];
		if ($severity !== null && $severity !== '') {
			$filters['severity'] = $severity;
		}
		$notificationRows = $this->notifications->query($filters, 200);
		$unreadCount      = $this->notifications->countUnread();
		// Retired rows are excluded from the unread list. Counting them here is
		// what keeps that from being a silent delete (countSuperseded had no
		// caller until 2026-09-01, so 66 rows were hidden with nothing saying so).
		$supersededCount  = $this->notifications->countSuperseded();

		$findings = $this->gitleaks->listFindings(['open_only' => true], 200);

		$conductorEvents = $this->events->query(
			['source' => 'conductor'],
			20,
		)['items'] ?? [];

		$this->template->notifications     = $notificationRows['items'];
		$this->template->notificationTotal = $notificationRows['total'];
		$this->template->unreadCount       = $unreadCount;
		$this->template->supersededCount   = $supersededCount;
		$this->template->severityFilter    = $severity;
		$this->template->unreadOnly        = $unreadOnly;
		$this->template->findings          = $findings;
		$this->template->conductorEvents   = $conductorEvents;
		$this->template->findingCount      = count($findings);

		// Open questions first — a blocked run is more urgent than an unread
		// message. listOpen() already excludes rows past their deadline, so
		// nothing here can be answered into a decision the agent has moved past.
		$questions = $this->questions->listOpen();
		$this->template->questions = $questions;
		$ref = ($ref !== null && trim($ref) !== '') ? trim($ref) : null;
		$this->template->ref = $ref;
		$this->template->refMatches = $ref === null ? 0 : count(array_filter(
			$questions,
			static fn(array $q): bool => ($q['session_uuid'] ?? null) === $ref,
		));
	}

	/**
	 * Legacy /approvals → /inbox (A11 retired 2026-08-08). Permanent, so
	 * anything still holding the old URL learns the successor. The tier gate
	 * runs first (startup()), which matches A11's requireSuperAdmin: a caller
	 * who could not see /approvals cannot use this redirect to probe /inbox.
	 */
	public function actionApprovals(): void
	{
		$this->redirectPermanent('Inbox:default');
	}

	public function actionMarkRead(string $uuid): void
	{
		$this->requirePostMethod();
		$this->notifications->markRead($uuid);
		$this->redirect('Inbox:default');
	}

	/**
	 * POST an answer to an agent's question.
	 *
	 * The outcome is flashed rather than swallowed, INCLUDING the two ways of
	 * losing: someone answered first, or the deadline passed while the page was
	 * open. Both are ordinary — this queue is meant to be read on a phone and
	 * acted on later — and an operator who is told nothing will believe they
	 * decided. A11's equivalent path posts an HMAC-signed event, discards the
	 * curl result and returns silently on a missing secret; that is the failure
	 * mode this method exists not to repeat.
	 */
	public function actionAnswer(string $uuid, string $answer = ''): void
	{
		$this->requirePostMethod();
		$operator = (string) ($this->getHttpRequest()->getHeader('X-Authentik-Username') ?: '');
		if ($operator === '') {
			// No identity, no decision. "who approved this" must name someone,
			// and forward-auth is the only thing that can say.
			$this->flashMessage('Cannot record an answer without an authenticated identity.', 'error');
			$this->redirect('Inbox:default');
		}

		$answer = trim($answer !== '' ? $answer : (string) $this->getHttpRequest()->getPost('answer'));
		if ($answer === '') {
			$this->flashMessage('An empty answer is not an answer.', 'error');
			$this->redirect('Inbox:default');
		}

		$verdict = $this->questions->answerAsOperator($uuid, $answer, $operator);
		$q = $verdict['question'];

		match ($verdict['result']) {
			AgentQuestionRepository::ANSWER_OK => $this->flashMessage(
				'Answered: ' . $answer, 'success'),
			AgentQuestionRepository::ANSWER_ALREADY => $this->flashMessage(
				'Already answered by ' . (string) ($q['answered_by'] ?? '?')
				. ': ' . (string) ($q['answer'] ?? ''), 'warning'),
			AgentQuestionRepository::ANSWER_EXPIRED => $this->flashMessage(
				'Too late — the deadline passed and the agent proceeded with: '
				. (string) ($q['default_on_expiry'] ?? '(no default)'), 'warning'),
			default => $this->flashMessage('No such question.', 'error'),
		};

		$this->redirect('Inbox:default');
	}
}
