<?php

declare(strict_types=1);

namespace App\Presenters\Api;

use App\Model\EventRepository;
use App\Model\PulseRepository;

/**
 * POST /api/v1/admin/halt    — the emergency halt (every unpaused Pulse job)
 * POST /api/v1/admin/resume  — lift ONLY emergency halts; manual pauses stay
 * GET  /api/v1/admin/state   — is a halt active, and the job counts
 *
 * The same act as the /admin Latte page (AdminPresenter), reachable when the
 * face or Traefik is down: `nos halt` calls it over loopback :9000 with the
 * wing-halt bearer, which only the operator's shell holds (docs/nos-cli.md).
 */
final class AdminPresenter extends BaseApiPresenter
{
	protected array $operatorActions = ['halt', 'resume'];

	/** wing.halt carries these two verbs and no other operator decision. */
	protected array $operatorScopes = ['wing.operator', 'wing.halt'];

	public function __construct(
		private PulseRepository $pulse,
		private EventRepository $events,
	) {
	}

	public function actionHalt(): void
	{
		$this->requireMethod('POST');
		$actor = $this->requireActorId();
		$affected = $this->pulse->emergencyHaltAll($actor);
		$this->record('admin_emergency_halt', $actor, ['jobs_affected' => $affected]);
	}

	public function actionResume(): void
	{
		$this->requireMethod('POST');
		$actor = $this->requireActorId();
		$affected = $this->pulse->emergencyResumeAll();
		$this->record('admin_emergency_resume', $actor, ['jobs_unhalted' => $affected]);
	}

	public function actionState(): void
	{
		$this->requireMethod('GET');
		$this->sendSuccess([
			'halt_active' => $this->pulse->isEmergencyHaltActive(),
			'job_counts'  => $this->pulse->jobStateCounts(),
		]);
	}

	/** Same event types as the Latte page, so /admin lists both channels' acts. */
	private function record(string $type, string $actor, array $result): never
	{
		$actionId = bin2hex(random_bytes(8));
		$this->events->insert([
			'run_id'          => $type . '-' . $actionId,
			'type'            => $type,
			'source'          => 'wing-api',
			'actor_id'        => $actor,
			'actor_action_id' => $actionId,
			'result'          => $result + ['operator_username' => $actor],
		]);
		$this->sendSuccess(['actor_id' => $actor, 'actor_action_id' => $actionId, 'halt_active' => $this->pulse->isEmergencyHaltActive()] + $result);
	}
}
