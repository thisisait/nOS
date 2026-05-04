<?php

declare(strict_types=1);

namespace App\Presenters\Api;

use App\Model\ComponentRepository;

/**
 * Component registry CRUD — the canonical inventory of nOS services.
 *
 * GET  /api/v1/components        — list (filters: category, stack, priority)
 * GET  /api/v1/components/<id>   — single component detail
 * POST /api/v1/components        — create (id + name required)
 * PUT  /api/v1/components/<id>   — update fields on an existing component
 */
final class ComponentsPresenter extends BaseApiPresenter
{
	public function __construct(
		private ComponentRepository $repo,
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

	private function doList(): never
	{
		$filters = array_filter([
			'category' => $this->getParameter('category'),
			'stack' => $this->getParameter('stack'),
			'priority' => $this->getParameter('priority'),
		]);
		$components = $this->repo->list($filters);
		$this->sendSuccess(['components' => $components, 'total' => count($components)]);
	}

	private function doGet(string $id): never
	{
		$component = $this->repo->get($id);
		if (!$component) {
			$this->sendError('Component not found', 404);
		}
		$this->sendSuccess($component);
	}

	private function doCreate(): never
	{
		$body = $this->getJsonBody();
		if (empty($body['id']) || empty($body['name'])) {
			$this->sendError('id and name are required');
		}
		$this->repo->create($body);
		$this->sendCreated(['id' => $body['id']]);
	}

	private function doUpdate(string $id): never
	{
		$body = $this->getJsonBody();
		$this->repo->update($id, $body);
		$this->sendSuccess(['id' => $id, 'updated' => true]);
	}
}
