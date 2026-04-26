<?php
/**
 * GDPR Article 30 register — REST API.
 *
 *   GET    /api/v1/gdpr/processing[/<id>]
 *   POST   /api/v1/gdpr/processing/<id>
 *   DELETE /api/v1/gdpr/processing/<id>
 *
 *   GET    /api/v1/gdpr/dsar[/<id>]
 *   POST   /api/v1/gdpr/dsar
 *
 *   GET    /api/v1/gdpr/breaches[/<id>]
 *   POST   /api/v1/gdpr/breaches
 *
 *   GET    /api/v1/gdpr/export.csv  → CSV dump of processing register
 *
 * Auth: requires Wing API token (BaseApiPresenter::startup) — same as other
 * /api/v1/ endpoints. Inspectors typically pull export.csv via curl with the
 * operator's token rather than coming through SSO.
 *
 * Track D (2026-04-26).
 */

declare(strict_types=1);

namespace App\Presenters\Api;

use App\Model\GdprRepository;

final class GdprPresenter extends BaseApiPresenter
{
    public function __construct(private GdprRepository $repo) {}

    // ── /api/v1/gdpr/processing ──────────────────────────────────────────

    public function actionProcessing(?string $id = null): void
    {
        $method = $this->getHttpRequest()->getMethod();
        if ($method === 'GET') {
            if ($id === null) {
                $this->sendSuccess(['processing' => $this->repo->listProcessing()]);
            }
            $row = $this->repo->getProcessing($id);
            if ($row === null) {
                $this->getHttpResponse()->setCode(404);
                $this->sendError('processing activity not found');
            }
            $this->sendSuccess($row);
        }
        if ($method === 'POST') {
            if ($id === null) {
                $this->sendError('id is required in URL for upsert');
            }
            $body = $this->getJsonBody();
            $this->repo->upsertProcessing($id, $body);
            $this->getHttpResponse()->setCode(204);
            $this->sendSuccess([]);
        }
        if ($method === 'DELETE') {
            if ($id === null) {
                $this->sendError('id is required in URL for delete');
            }
            $ok = $this->repo->deleteProcessing($id);
            $this->getHttpResponse()->setCode($ok ? 204 : 404);
            $this->sendSuccess([]);
        }
        $this->sendError('method not allowed', 405);
    }

    // ── /api/v1/gdpr/dsar ────────────────────────────────────────────────

    public function actionDsar(?string $id = null): void
    {
        $method = $this->getHttpRequest()->getMethod();
        if ($method === 'GET') {
            $status = $this->getHttpRequest()->getQuery('status');
            $this->sendSuccess(['dsar' => $this->repo->listDsar(is_string($status) ? $status : null)]);
        }
        if ($method === 'POST') {
            $body = $this->getJsonBody();
            foreach (['received_at', 'subject_email', 'request_type', 'status'] as $req) {
                if (empty($body[$req])) {
                    $this->sendError("missing required field: {$req}");
                }
            }
            $newId = $this->repo->recordDsar($body);
            $this->sendSuccess(['id' => $newId]);
        }
        $this->sendError('method not allowed', 405);
    }

    // ── /api/v1/gdpr/breaches ────────────────────────────────────────────

    public function actionBreaches(?string $id = null): void
    {
        $method = $this->getHttpRequest()->getMethod();
        if ($method === 'GET') {
            $this->sendSuccess(['breaches' => $this->repo->listBreaches()]);
        }
        if ($method === 'POST') {
            $body = $this->getJsonBody();
            foreach (['detected_at', 'nature', 'status'] as $req) {
                if (empty($body[$req])) {
                    $this->sendError("missing required field: {$req}");
                }
            }
            $newId = $this->repo->recordBreach($body);
            $this->sendSuccess(['id' => $newId]);
        }
        $this->sendError('method not allowed', 405);
    }

    // ── /api/v1/gdpr/export.csv ──────────────────────────────────────────

    public function actionExportCsv(): void
    {
        $this->getHttpResponse()->setContentType('text/csv', 'utf-8');
        $this->getHttpResponse()->setHeader(
            'Content-Disposition',
            'attachment; filename="nos-gdpr-processing-' . date('Y-m-d') . '.csv"'
        );
        $csv = $this->repo->exportProcessingCsv();
        $this->sendResponse(new \Nette\Application\Responses\TextResponse($csv));
    }
}
