<?php

declare(strict_types=1);

namespace App\Presenters;

use App\Model\AgentQuestionRepository;

/**
 * Wing /questions — the ledger of what agents asked and how it ended.
 *
 * READ-ONLY, deliberately. /inbox owns answering (POST + forward-auth identity
 * + resolve-once UPDATE); this page owns the account of it: who answered, via
 * which channel, and how many questions nobody answered in time. Two surfaces
 * that can both decide is two places to audit.
 *
 * Q15 — Wing is the ONLY answering channel. An approval channel is an
 * authentication surface, so ntfy actions and chat replies are out; the
 * `answered_via` column exists to make a non-wing answer visible if one ever
 * appears, not to invite one.
 *
 * THE NUMBER THIS PAGE EXISTS FOR is the expired count. An expired question is
 * the loop deciding without the operator, and it is invisible everywhere else:
 * nothing sweeps agent_questions, so an unanswered row still reads `open`.
 * countExpired() derives it at read time — a reader, not a marker.
 *
 * Tier-1 via the declarative $minAccessTier: the same rows /inbox gates, plus
 * the answering operators' identities.
 */
final class QuestionsPresenter extends BasePresenter
{
	protected string $activeTab = 'questions';

	/** Same rows /inbox gates — agent context and operator identities. */
	protected ?int $minAccessTier = 1;

	public function __construct(private AgentQuestionRepository $questions)
	{
	}

	public function renderDefault(): void
	{
		$rows = $this->questions->listRecent(200);
		$this->template->open = array_values(array_filter(
			$rows, static fn(array $r): bool => $r['status'] === 'open',
		));
		$this->template->resolved = array_values(array_filter(
			$rows, static fn(array $r): bool => $r['status'] !== 'open',
		));
		$this->template->expiredCount = $this->questions->countExpired();
		$this->template->shown = count($rows);
	}
}
