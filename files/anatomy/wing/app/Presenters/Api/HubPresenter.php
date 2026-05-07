<?php

declare(strict_types=1);

namespace App\Presenters\Api;

use App\Model\SystemRepository;

/**
 * GET /api/v1/hub/systems         — list all systems (flat, with filters)
 * GET /api/v1/hub/systems?tree=1  — tree (hierarchy with children)
 * GET /api/v1/hub/systems/{id}    — single system detail
 * GET /api/v1/hub/health          — probe all systems with a URL
 * POST /api/v1/hub/systems        — upsert a system
 *
 * Public routes (no Bearer token) — data is non-sensitive service metadata.
 * Nginx gates browser access via Authentik; API access is local-only.
 */
final class HubPresenter extends BaseApiPresenter
{
	protected array $publicActions = ['systems', 'health'];

	/** @inject */
	public SystemRepository $systems;

	public function actionSystems(?string $id = null): void
	{
		if ($id !== null) {
			$this->requireMethod('GET');
			$sys = $this->systems->get($id);
			if (!$sys) {
				$this->sendError('System not found', 404);
			}
			$this->sendSuccess($sys);
		}

		$method = $this->getMethod();
		if ($method === 'POST') {
			$body = $this->getJsonBody();
			if (empty($body['id'])) {
				$this->sendError('id is required');
			}
			$this->systems->upsert($body);
			$this->sendSuccess(['ok' => true, 'id' => $body['id']]);
		}

		// GET — list or tree
		$this->requireMethod('GET');
		$req = $this->getHttpRequest();

		if ($req->getQuery('tree')) {
			$this->sendSuccess(['systems' => $this->systems->tree()]);
		}

		$filters = [];
		foreach (['category', 'stack', 'priority', 'health', 'source', 'type'] as $key) {
			$val = $req->getQuery($key);
			if ($val !== null) {
				$filters[$key] = $val;
			}
		}

		$data = $this->systems->list($filters);
		$data['stats'] = $this->systems->stats();
		$this->sendSuccess($data);
	}

	public function actionHealth(): void
	{
		$this->requireMethod('GET');
		$url = $this->getHttpRequest()->getQuery('url');

		if (is_string($url) && $url !== '') {
			// Single probe — validate URL is in DB to prevent SSRF
			$found = false;
			foreach ($this->systems->list()['systems'] as $sys) {
				if (($sys['url'] ?? '') === $url || ($sys['ip_url'] ?? '') === $url || ($sys['domain_url'] ?? '') === $url) {
					$found = true;
					break;
				}
			}
			if (!$found) {
				$this->sendError('URL not registered', 400);
			}
			$result = $this->systems->probe($url);
			$this->sendSuccess(['url' => $url, 'health' => $result]);
		}

		// Probe all + persist
		$all = $this->systems->probeAll();
		$probes = [];
		foreach ($all as $sysId => $result) {
			$probes[] = [
				'id' => $sysId,
				'status' => $result['status'],
				'http_code' => $result['http_code'],
				'ms' => $result['ms'],
			];
		}
		$this->sendSuccess([
			'generated_at' => gmdate('c'),
			'probes' => $probes,
		]);
	}
}
