<?php

declare(strict_types=1);

namespace App\Presenters\Api;

use App\Model\AdvisoryRepository;

final class AdvisoriesPresenter extends BaseApiPresenter
{
	public function __construct(
		private AdvisoryRepository $repo,
	) {
	}

	public function actionDefault(?int $id = null): void
	{
		match ($this->getMethod()) {
			'GET' => $id ? $this->doGet($id) : $this->doList(),
			'POST' => $this->doCreate(),
			default => $this->sendError('Method not allowed', 405),
		};
	}

	private function doList(): never
	{
		$filters = array_filter([
			'date' => $this->getParameter('date'),
			'limit' => $this->getParameter('limit'),
		]);
		$advisories = $this->repo->list($filters);
		$this->sendSuccess(['advisories' => $advisories, 'total' => count($advisories)]);
	}

	private function doGet(int $id): never
	{
		$advisory = $this->repo->get($id);
		if (!$advisory) {
			$this->sendError('Advisory not found', 404);
		}
		$this->sendSuccess($advisory);
	}

	private function doCreate(): never
	{
		$body = $this->getJsonBody();
		if (empty($body['filename']) || empty($body['full_text'])) {
			$this->sendError('filename and full_text are required');
		}
		$id = $this->repo->create($body);
		$this->sendCreated(['id' => $id, 'filename' => $body['filename']]);
	}
}
