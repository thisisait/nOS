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
	 *
	 * Security (2026-05-17): `resolved_by` is ALWAYS derived from the
	 * validated bearer-token identity via `$this->getActorId()`. Pre-this
	 * the endpoint accepted `$body['resolved_by']` — a client-supplied
	 * string with no cryptographic tie to the caller — which let any agent
	 * holding a Wing token resolve a finding under an arbitrary attribution
	 * (e.g. an LLM-driven remediator could write `resolved_by: 'operator'`
	 * and the audit trail would believe it). Surfaced by the SSO doctrine
	 * audit; same gate-pattern as AgentsPresenter::actionStart (A14.1).
	 *
	 * Defence in depth: if the caller sends `resolved_by` in the body, we
	 * REJECT the request rather than silently ignore — that way a future
	 * refactor can't flip back to body-trust without tripping this check.
	 */
	public function actionResolve(string $id): void
	{
		$this->requireMethod('POST');
		$body = $this->getJsonBody();
		if (isset($body['resolved_by'])) {
			$this->sendError(
				'resolved_by is not accepted in the request body — it is ' .
				'derived from the validated bearer token identity to prevent ' .
				'attribution spoofing',
				400,
			);
		}
		$actorId = $this->getActorId();
		if (!$actorId) {
			$this->sendError('actor_id unavailable — token validation drift', 500);
		}
		$ok = $this->gitleaks->resolve($id, $actorId);
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
