<?php

declare(strict_types=1);

namespace App\Presenters\Api;

use App\Model\EventRepository;
use App\Model\PulseRepository;

/**
 * POST /api/v1/admin/halt    — the emergency halt (every unpaused Pulse job)
 * POST /api/v1/admin/resume  — lift ONLY emergency halts; manual pauses stay
 * POST /api/v1/admin/setting — the record of a setting the medulla set (record-only)
 * GET  /api/v1/admin/state   — is a halt active, and the job counts
 *
 * The same act as the /admin Latte page (AdminPresenter), reachable when the
 * face or Traefik is down: `nos halt` calls it over loopback :9000 with the
 * wing-halt bearer, which only the operator's shell holds (docs/nos-cli.md).
 */
final class AdminPresenter extends BaseApiPresenter
{
	protected array $operatorActions = ['halt', 'resume', 'setting'];

	/** wing.halt carries the halt, the resume and the record of a setting the medulla set; no other operator decision. */
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
		$this->record('admin_emergency_halt', $actor, ['jobs_affected' => $affected], $this->claimedBy());
	}

	/**
	 * The person the caller acted for ({"by"} from the medulla's kernel identity or the shell's $USER).
	 * A name the bearer vouches for, not an auth: actor_id stays the bearer. Bad shape = not named.
	 */
	private function claimedBy(): ?string
	{
		$by = $this->getJsonBody()['by'] ?? null;
		return is_string($by) && preg_match('/^[A-Za-z0-9._-]{1,64}$/', $by) ? $by : null;
	}

	public function actionResume(): void
	{
		$this->requireMethod('POST');
		$actor = $this->requireActorId();
		$affected = $this->pulse->emergencyResumeAll();
		$this->record('admin_emergency_resume', $actor, ['jobs_unhalted' => $affected], $this->claimedBy());
	}

	/**
	 * POST /api/v1/admin/setting — record a setting the medulla changed (state/genome/settings.yml).
	 * Record-only: the medulla's store is the set-point; this writes the event and nothing else.
	 */
	public function actionSetting(): void
	{
		$this->requireMethod('POST');
		$actor = $this->requireActorId();
		$body = $this->getJsonBody();
		$key = $body['key'] ?? null;
		$change = $body['change'] ?? null;
		if (!is_string($key) || !preg_match('/^[a-z_]+(\.[a-z_]+)*$/', $key) || strlen($key) > 64
			|| !is_array($change) || $change === [] || array_is_list($change)) {
			$this->sendError('a setting is {key, change}: a dotted lowercase key and an object of entries');
		}
		$this->record('admin_setting_set', $actor, ['key' => $key, 'change' => $change], $this->claimedBy());
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
	private function record(string $type, string $actor, array $result, ?string $by = null): never
	{
		$result += $by !== null ? ['operator_username' => $by, 'vouched_by' => $actor] : [];
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
