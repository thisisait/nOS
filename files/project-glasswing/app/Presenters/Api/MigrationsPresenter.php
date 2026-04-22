<?php

declare(strict_types=1);

namespace App\Presenters\Api;

use App\Model\MigrationRepository;

/**
 * GET  /api/v1/migrations             — list { applied, pending } (via BoxAPI)
 * GET  /api/v1/migrations/<id>        — full record
 * POST /api/v1/migrations/<id>/preview
 * POST /api/v1/migrations/<id>/apply
 * POST /api/v1/migrations/<id>/rollback
 *
 * All proxy to BoxAPI. Bearer token required.
 */
final class MigrationsPresenter extends BaseApiPresenter
{
	public function __construct(
		private MigrationRepository $migrations,
	) {
	}

	public function actionDefault(?string $id = null): void
	{
		if ($id === null) {
			$this->requireMethod('GET');
			$this->sendSuccess([
				'pending' => $this->migrations->listPending(),
				'applied' => $this->migrations->listApplied(),
			]);
		}

		$this->requireMethod('GET');
		$rec = $this->migrations->get($id);
		if ($rec === null) {
			$this->sendError('Migration not found', 404);
		}
		$this->sendSuccess($rec);
	}

	public function actionPreview(string $id): void
	{
		$this->requireMethod('POST');
		$resp = $this->migrations->preview($id);
		$this->proxyBoxApi($resp);
	}

	public function actionApply(string $id): void
	{
		$this->requireMethod('POST');
		$body = $this->getJsonBody();
		$dryRun = !empty($body['dry_run']);
		$resp = $this->migrations->apply($id, $dryRun);
		$this->proxyBoxApi($resp);
	}

	public function actionRollback(string $id): void
	{
		$this->requireMethod('POST');
		$resp = $this->migrations->rollback($id);
		$this->proxyBoxApi($resp);
	}

	/** Pass through BoxAPI status + body to the client. */
	private function proxyBoxApi(array $resp): never
	{
		$status = (int) ($resp['status'] ?? 502);
		$body = $resp['body'] ?? ['error' => 'empty response from BoxAPI'];
		$this->getHttpResponse()->setCode($status);
		$this->sendJson(is_array($body) ? $body : ['body' => $body]);
	}
}
