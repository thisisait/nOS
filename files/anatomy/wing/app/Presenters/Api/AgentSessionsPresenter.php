<?php

declare(strict_types=1);

namespace App\Presenters\Api;

use App\Model\AgentSessionRepository;
use App\Model\EventRepository;

/**
 * Wing /api/v1/agent-sessions/<uuid> — single-session lineage as JSON.
 *
 * Auth: bearer token via BaseApiPresenter::requireTokenAuth(). The original
 * A14 implementation skipped DB validation (security review finding A14.1);
 * inheriting BaseApiPresenter aligns this presenter with all other Wing
 * API presenters.
 */
final class AgentSessionsPresenter extends BaseApiPresenter
{
	public function __construct(
		private AgentSessionRepository $sessions,
		// Autowired like EventsPresenter's; null only where a harness builds the presenter without it.
		private ?EventRepository $events = null,
	) {
		parent::__construct();
	}

	/** The newest *_report body a read carries, in bytes: what Iris hears of a run it started. */
	public const REPORT_CAP = 4096;

	protected array $bffActions = ['default'];

	protected array $thalamusReads = ['default'];

	public function actionDefault(string $uuid): void
	{
		$session = $this->sessions->findByUuid($uuid);
		// Not yours answers like absent, so a uuid's existence does not leak.
		$scope = $this->endUser?->scope();
		if ($session === null || ($scope !== null && $session['actor_id'] !== $scope)) {
			$this->sendError('not_found', 404);
		}
		$this->sendSuccess([
			'session' => $session,
			'threads' => $this->sessions->listThreadsForSession($uuid),
			'iterations' => $this->sessions->listIterations($uuid),
			'children' => $this->sessions->listChildren($uuid, $scope),
			'report' => $this->report($uuid),
		]);
	}

	/**
	 * The run's newest *_report event: {event_id, type, body (<= REPORT_CAP bytes), chars}, or null.
	 * body is result.report when it is a string, else the whole result_json.
	 *
	 * @return array<string, mixed>|null
	 */
	private function report(string $uuid): ?array
	{
		// ponytail: the newest 500 events of the run; a report buried under more is null (a type filter in SQL lifts it).
		foreach ($this->events?->query(['actor_action_id' => $uuid], 500)['items'] ?? [] as $e) {
			if (!str_ends_with((string) $e['type'], '_report')) {
				continue;
			}
			$body = is_string($e['result']['report'] ?? null) ? $e['result']['report'] : (string) ($e['result_json'] ?? '');
			return ['event_id' => (int) $e['id'], 'type' => $e['type'],
				'body' => mb_strcut($body, 0, self::REPORT_CAP, 'UTF-8'), 'chars' => mb_strlen($body, 'UTF-8')];
		}
		return null;
	}
}
