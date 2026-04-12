<?php

declare(strict_types=1);

namespace App\Presenters\Api;

use App\Model\RemediationRepository;

final class RemediationPresenter extends BaseApiPresenter
{
	public function __construct(
		private RemediationRepository $repo,
	) {
	}

	public function actionDefault(?string $id = null): void
	{
		match ($this->getMethod()) {
			'GET' => $id ? $this->doGet($id) : $this->doList(),
			'POST' => $this->doCreate(),
			'PUT' => $id ? $this->doUpdate($id) : $this->sendError('ID required for PUT'),
			default => $this->sendError('Method not allowed', 405),
		};
	}

	public function actionBulkStatus(): void
	{
		$this->requireMethod('PUT');
		$body = $this->getJsonBody();
		if (empty($body['ids']) || empty($body['status'])) {
			$this->sendError('ids and status are required');
		}
		$count = $this->repo->bulkUpdateStatus(
			$body['ids'],
			$body['status'],
			$body['resolved_by'] ?? null,
		);
		$this->sendSuccess(['updated' => $count]);
	}

	public function actionNextId(): void
	{
		$this->requireMethod('GET');
		$this->sendSuccess(['next_id' => $this->repo->getNextId()]);
	}

	private function doList(): never
	{
		$filters = array_filter([
			'status' => $this->getParameter('status'),
			'severity' => $this->getParameter('severity'),
			'component' => $this->getParameter('component'),
			'limit' => $this->getParameter('limit'),
		]);
		$result = $this->repo->list($filters);
		$this->sendSuccess($result);
	}

	private function doGet(string $id): never
	{
		$item = $this->repo->get($id);
		if (!$item) {
			$this->sendError('Remediation item not found', 404);
		}
		$this->sendSuccess($item);
	}

	private function doCreate(): never
	{
		$body = $this->getJsonBody();
		if (empty($body['severity'])) {
			$this->sendError('severity is required');
		}
		try {
			$id = $this->repo->create($body);
			$this->sendCreated(['id' => $id]);
		} catch (\RuntimeException $e) {
			if (str_contains(strtolower($e->getMessage()), 'duplicate')) {
				$this->sendError($e->getMessage(), 409);
			}
			throw $e;
		}
	}

	private function doUpdate(string $id): never
	{
		$body = $this->getJsonBody();
		$this->repo->update($id, $body);
		$this->sendSuccess(['id' => $id, 'updated' => true]);
	}
}
