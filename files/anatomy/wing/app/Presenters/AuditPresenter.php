<?php

declare(strict_types=1);

namespace App\Presenters;

use App\Model\EventRepository;

/**
 * Wing /audit — actor-attributed event browser (Anatomy A10.c / X.1.c, 2026-05-08).
 *
 * Sister view to /inbox. Where /inbox surfaces "unresolved things needing
 * attention", /audit surfaces "who-did-what across the platform". Filters:
 *
 *   - actor:           specific Authentik client_id (e.g. ?actor=conductor
 *                      shows the conductor agent's full audit trail).
 *   - action:          specific actor_action_id (UUID) — drill into one
 *                      logical action's event sequence (start + finish).
 *   - type:            event type filter (e.g. agent_run_end).
 *   - source:          channel filter (callback / operator / agent:<n>).
 *   - since:           ISO-8601 lower bound on ts.
 *
 * Pre-A10 events have actor_id NULL — they show up in the "uncategorised"
 * bucket. A10 forward-looking attribution: every conductor / Wing UI /
 * plugin write after the migration carries actor_id.
 *
 * Read-only view. Mutations live elsewhere (Pulse for triggering agent
 * runs, GitleaksPresenter::resolve for finding mark-resolved). The
 * /audit view is the authoritative "what happened, when, by whom"
 * surface — Phase 5 ceremony pass criterion uses it to verify the
 * conductor self-test produced the expected actor-tagged rows.
 */
final class AuditPresenter extends BasePresenter
{
	protected string $activeTab = 'audit';

	private const RESULT_LIMIT = 200;

	public function __construct(
		private EventRepository $events,
	) {
	}

	public function renderDefault(
		?string $actor = null,
		?string $action = null,
		?string $type = null,
		?string $source = null,
		?string $since = null,
	): void {
		$filters = array_filter([
			'actor_id'        => $actor,
			'actor_action_id' => $action,
			'type'            => $type,
			'source'          => $source,
			'since'           => $since,
		]);

		$result = $this->events->query($filters, self::RESULT_LIMIT);
		$items = $result['items'] ?? [];

		// Aggregate per-actor counts (small set, computed inline so the
		// view can render facet badges without a second query). Empty
		// actor_id rows roll into the synthetic '<unattributed>' bucket
		// — pre-A10 events that were never tagged.
		$actorCounts = [];
		foreach ($items as $row) {
			$key = $row['actor_id'] ?? null;
			if ($key === null || $key === '') {
				$key = '<unattributed>';
			}
			$actorCounts[$key] = ($actorCounts[$key] ?? 0) + 1;
		}
		ksort($actorCounts);

		$this->template->items        = $items;
		$this->template->total        = $result['total'] ?? count($items);
		$this->template->limit        = self::RESULT_LIMIT;
		$this->template->actorCounts  = $actorCounts;
		$this->template->filters      = $filters;
		$this->template->activeFilter = [
			'actor'  => $actor,
			'action' => $action,
			'type'   => $type,
			'source' => $source,
			'since'  => $since,
		];
	}
}
