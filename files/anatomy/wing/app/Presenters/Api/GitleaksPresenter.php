<?php

declare(strict_types=1);

namespace App\Presenters\Api;

use App\Model\GitleaksRepository;

/**
 * GET  /api/v1/gitleaks_findings             — list findings
 *        query: ?rule_id, ?severity, ?scan_id, ?open_only=1, ?limit (default 200, max 500)
 * POST /api/v1/gitleaks_findings             — batch ingest from skill
 *        body: {scan_id: string, findings: [...]}
 * GET  /api/v1/gitleaks_findings/<id>        — single finding
 * POST /api/v1/gitleaks_findings/<id>/resolve — mark as resolved
 *        body: {resolved_by?: string}
 *
 * All actions require Bearer auth. The gitleaks skill script holds a
 * Wing API token minted for the gitleaks service account (write scope).
 * The Wing UI / conductor read via the operator's bearer token.
 *
 * Anatomy A7 (2026-05-06). First scheduled-job → Wing write-path consumer:
 * validates the plugin → Pulse subprocess → Wing ingest pipeline.
 */
final class GitleaksPresenter extends BaseApiPresenter
{
	public function __construct(
		private GitleaksRepository $gitleaks,
	) {
	}

	/**
	 * GET  /api/v1/gitleaks_findings       — list
	 * POST /api/v1/gitleaks_findings       — batch ingest
	 * GET  /api/v1/gitleaks_findings/<id>  — single finding
	 */
	public function actionDefault(?string $id = null): void
	{
		if ($id !== null) {
			$this->requireMethod('GET');
			$row = $this->gitleaks->getOne($id);
			if (!$row) {
				$this->sendError('Finding not found', 404);
			}
			$this->sendSuccess($row);
		}

		if ($this->getMethod() === 'POST') {
			$this->ingestBatch();
		}
		$this->requireMethod('GET');
		$this->listFindings();
	}

	/**
	 * POST /api/v1/gitleaks_findings/<id>/resolve
	 */
	public function actionResolve(string $id): void
	{
		$this->requireMethod('POST');
		$body = $this->getJsonBody();
		$ok   = $this->gitleaks->resolve($id, $body['resolved_by'] ?? null);
		if (!$ok) {
			$this->sendError('Finding not found or already resolved', 404);
		}
		$this->sendSuccess($this->gitleaks->getOne($id) ?? []);
	}

	private function listFindings(): void
	{
		$filters = [];
		foreach (['rule_id', 'severity', 'scan_id'] as $k) {
			$v = $this->getParameter($k);
			if ($v !== null && $v !== '') {
				$filters[$k] = $v;
			}
		}
		if ($this->getParameter('open_only')) {
			$filters['open_only'] = true;
		}
		$limit = min(500, max(1, (int) ($this->getParameter('limit') ?? 200)));
		$this->sendSuccess([
			'generated_at' => gmdate('c'),
			'findings'     => $this->gitleaks->listFindings($filters, $limit),
		]);
	}

	private function ingestBatch(): void
	{
		$body = $this->getJsonBody();
		if (empty($body['scan_id'])) {
			$this->sendError('scan_id is required');
		}
		if (!isset($body['findings']) || !is_array($body['findings'])) {
			$this->sendError('findings array is required');
		}
		$counts = $this->gitleaks->ingestBatch(
			(string) $body['scan_id'],
			$body['findings'],
		);
		$this->sendCreated([
			'accepted' => true,
			'scan_id'  => $body['scan_id'],
			'inserted' => $counts['inserted'],
			'skipped'  => $counts['skipped'],
		]);
	}
}
