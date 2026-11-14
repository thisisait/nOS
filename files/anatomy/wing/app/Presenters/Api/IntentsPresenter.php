<?php

declare(strict_types=1);

namespace App\Presenters\Api;

use App\Model\IntentRepository;
use App\Model\TokenRepository;
use Nette\Http\IResponse;

/**
 * The medulla's door to intents (row wing-apply-through-medulla). Only a token holding
 * wing.intents reaches it, and that token reaches nothing else (BaseApiPresenter).
 *
 * GET  /api/v1/intents/due              — unpicked intents, oldest first
 * POST /api/v1/intents/<uuid>/pick      — Wing stamps picked_at once; 409 if already picked
 * POST /api/v1/intents/<uuid>/outcome   — {rc, summary}: Wing records the outcome once, emits intent_executed
 */
final class IntentsPresenter extends BaseApiPresenter
{
	private const UUID = '/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/';

	protected array $intentActions = ['due', 'pick', 'outcome'];

	public function __construct(private IntentRepository $intents)
	{
	}

	public function startup(): void
	{
		parent::startup();
		if (!TokenRepository::grants($this->validatedToken['scopes'] ?? null, 'wing.intents')) {
			$this->sendError('intents are the medulla\'s: this needs the wing.intents scope', IResponse::S403_Forbidden);
		}
	}

	public function actionDue(): void
	{
		$this->requireMethod('GET');
		$this->sendSuccess(['intents' => $this->intents->due()]);
	}

	public function actionPick(string $uuid): void
	{
		$this->requireMethod('POST');
		$this->requireUuid($uuid);
		if (!$this->intents->pick($uuid, (string) $this->getActorId())) {
			$this->sendError('intent not found or already picked', IResponse::S409_Conflict);
		}
		$this->sendSuccess(['uuid' => $uuid, 'picked' => true]);
	}

	public function actionOutcome(string $uuid): void
	{
		$this->requireMethod('POST');
		$this->requireUuid($uuid);
		$body = $this->getJsonBody();
		$rc = $body['rc'] ?? null;
		$summary = $body['summary'] ?? '';
		if (!is_int($rc) || $rc < 0 || $rc > 255 || !is_string($summary)) {
			$this->sendError('outcome takes {rc: 0-255, summary: string}', IResponse::S400_BadRequest);
		}
		if (!$this->intents->outcome($uuid, (string) $this->getActorId(), $rc, $summary)) {
			$this->sendError('intent not picked by you, or its outcome is already recorded', IResponse::S409_Conflict);
		}
		$this->sendSuccess(['uuid' => $uuid, 'recorded' => true]);
	}

	private function requireUuid(string $uuid): void
	{
		if (preg_match(self::UUID, $uuid) !== 1) {
			$this->sendError('not an intent uuid', IResponse::S400_BadRequest);
		}
	}
}
