<?php

declare(strict_types=1);

namespace App\Presenters\Api;

use App\Model\ScanStateRepository;

final class ScanPresenter extends BaseApiPresenter
{
	public function __construct(
		private ScanStateRepository $repo,
	) {
	}

	public function actionState(): void
	{
		$this->requireMethod('GET');
		$this->sendSuccess($this->repo->getState());
	}

	public function actionCycles(): void
	{
		$this->requireMethod('GET');
		$limit = (int) ($this->getParameter('limit') ?? 10);
		$this->sendSuccess(['cycles' => $this->repo->getCycles($limit)]);
	}

	public function actionCycle(): void
	{
		$this->requireMethod('POST');
		$body = $this->getJsonBody();
		$cycleNumber = $this->repo->createCycle($body);
		$this->sendCreated(['cycle_number' => $cycleNumber]);
	}

	public function actionComponent(string $id): void
	{
		$this->requireMethod('PUT');
		$body = $this->getJsonBody();
		$this->repo->updateComponent($id, $body);
		$this->sendSuccess(['component_id' => $id, 'updated' => true]);
	}

	public function actionConfig(): void
	{
		$this->requireMethod('PUT');
		$body = $this->getJsonBody();
		$this->repo->updateConfig($body);
		$this->sendSuccess(['updated' => true]);
	}

	public function actionRotation(): void
	{
		$this->requireMethod('PUT');
		$body = $this->getJsonBody();
		$this->repo->setRotation($body['next_batch'] ?? []);
		$this->sendSuccess(['updated' => true]);
	}

	public function actionProbeComplete(string $name): void
	{
		$this->requireMethod('POST');
		$this->repo->completeProbe($name);
		$this->sendSuccess(['probe' => $name, 'completed' => true]);
	}
}
