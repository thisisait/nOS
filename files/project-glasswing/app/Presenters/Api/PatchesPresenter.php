<?php

declare(strict_types=1);

namespace App\Presenters\Api;

use App\Model\PatchRepository;

/**
 * GET  /api/v1/patches                       — list patches (filter: status, component_id, limit)
 * GET  /api/v1/patches/<id>                  — single patch detail
 * POST /api/v1/patches                       — create patch
 * PUT  /api/v1/patches/<id>                  — update patch
 * POST /api/v1/patches/<id>/plan             — BoxAPI dry-run (ansible --tags apply-patches --check)
 * POST /api/v1/patches/<id>/apply            — BoxAPI apply (ansible --tags apply-patches)
 * GET  /api/v1/patches/<id>/events           — events emitted during this patch's runs
 * GET  /api/v1/patches/history               — local patches_applied mirror (?patch_id=, ?component_id=, ?limit=)
 *
 * Mirrors UpgradesPresenter. The nested `api/v1/pentest/patches[/<id>]` route
 * on PentestPresenter remains for backward compatibility; new clients should
 * use this first-class presenter.
 */
final class PatchesPresenter extends BaseApiPresenter
{
	public function __construct(
		private PatchRepository $patches,
	) {
	}

	public function actionDefault(?string $id = null): void
	{
		match ($this->getMethod()) {
			'GET'  => $id ? $this->doGetOne($id) : $this->doList(),
			'POST' => $this->doCreate(),
			'PUT'  => $id ? $this->doUpdate($id) : $this->sendError('ID required for PUT'),
			default => $this->sendError('Method not allowed', 405),
		};
	}

	public function actionPlan(string $id): void
	{
		$this->requireMethod('POST');
		if ($this->patches->getById($id) === null) {
			$this->sendError('Patch not found', 404);
		}
		$this->proxyBoxApi($this->patches->plan($id));
	}

	public function actionApply(string $id): void
	{
		$this->requireMethod('POST');
		if ($this->patches->getById($id) === null) {
			$this->sendError('Patch not found', 404);
		}
		$this->proxyBoxApi($this->patches->apply($id));
	}

	public function actionEvents(string $id): void
	{
		$this->requireMethod('GET');
		$this->sendSuccess(['items' => $this->patches->getEventsFor($id)]);
	}

	public function actionHistory(): void
	{
		$this->requireMethod('GET');
		$patchId     = $this->getParameter('patch_id');
		$componentId = $this->getParameter('component_id');
		$limit       = (int) ($this->getParameter('limit') ?? 50);
		$this->sendSuccess([
			'items' => $this->patches->history(
				is_string($patchId)     && $patchId     !== '' ? $patchId     : null,
				is_string($componentId) && $componentId !== '' ? $componentId : null,
				max(1, min(500, $limit)),
			),
		]);
	}

	private function doList(): never
	{
		$filter = [];
		foreach (['status', 'component_id', 'limit'] as $key) {
			$v = $this->getParameter($key);
			if (is_string($v) && $v !== '') {
				$filter[$key] = $v;
			} elseif (is_int($v)) {
				$filter[$key] = $v;
			}
		}
		$this->sendSuccess(['patches' => $this->patches->list($filter)]);
	}

	private function doGetOne(string $id): never
	{
		$row = $this->patches->getById($id);
		if ($row === null) {
			$this->sendError('Patch not found', 404);
		}
		$this->sendSuccess($row);
	}

	private function doCreate(): never
	{
		$body = $this->getJsonBody();
		$this->patches->create($body);
		$this->sendCreated(['id' => $body['id'] ?? 'auto']);
	}

	private function doUpdate(string $id): never
	{
		$body = $this->getJsonBody();
		if ($this->patches->getById($id) === null) {
			$this->sendError('Patch not found', 404);
		}
		$this->patches->update($id, $body);
		$this->sendSuccess(['id' => $id, 'updated' => true]);
	}

	/**
	 * Pass a BoxAPI response through verbatim: preserve status, shape the body
	 * as JSON. Mirrors UpgradesPresenter::proxyBoxApi.
	 *
	 * @param array{status:int,body:mixed} $resp
	 */
	private function proxyBoxApi(array $resp): never
	{
		$status = (int) ($resp['status'] ?? 502);
		$body   = $resp['body'] ?? ['error' => 'empty response from BoxAPI'];
		$this->getHttpResponse()->setCode($status);
		$this->sendJson(is_array($body) ? $body : ['body' => $body]);
	}
}
