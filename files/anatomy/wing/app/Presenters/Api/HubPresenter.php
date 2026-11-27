<?php

declare(strict_types=1);

namespace App\Presenters\Api;

use App\Model\HubCardRepository;
use App\Model\SystemRepository;

/**
 * GET /api/v1/hub/systems         — list all systems (flat, with filters) [PUBLIC]
 * GET /api/v1/hub/systems?tree=1  — tree (hierarchy with children) [PUBLIC]
 * GET /api/v1/hub/systems?listed=1 — the /hub tiles (face dock) [PUBLIC]
 * GET /api/v1/hub/systems/{id}    — single system detail [PUBLIC]
 * GET /api/v1/hub/health          — probe all systems with a URL [PUBLIC]
 * POST /api/v1/hub/systems        — upsert a system [BEARER required]
 *
 * GET routes are public — service metadata is non-sensitive and Nginx
 * gates browser access via Authentik.
 *
 * SEC-7 (2026-05-23): POST was ALSO public pre-this commit — any
 * client able to reach 127.0.0.1:9000 could forge registry rows
 * (subverting actionHealth's "URL must be in DB" SSRF guard) and write
 * any column via mass-assignment. Both holes closed:
 *   1. POST /systems hits requireTokenAuth: since 2026-11-27 declared, not
 *      overridden — `systems` is public for GET only ($publicMethods), which
 *      BaseApiPresenter::startup() and bin/export-openapi.php both read.
 *   2. SystemRepository::upsert whitelists WRITABLE_FIELDS — clients
 *      can't write health_status, audit columns, or unknown columns.
 */
final class HubPresenter extends BaseApiPresenter
{
	/**
	 * GET /health and GET /systems[/<id>] are public; any other method on
	 * them needs the bearer (BaseApiPresenter::startup, before the action).
	 * A non-GET to /health without a bearer is 401, not 405 (ruled 2026-11-15).
	 */
	protected array $publicActions = ['health', 'systems'];

	protected array $publicMethods = ['GET'];

	/** @inject */
	public SystemRepository $systems;

	/** @inject */
	public HubCardRepository $cards;

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
			// Bearer auth already enforced by startup() (this action
			// is NOT in $publicActions for non-GET methods).
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
		// ?listed=1 — what /hub lists (isListed + hub_card overlay), for the face
		// dock. The bare list stays the whole inventory (health, cortex svc:).
		if ($req->getQuery('listed')) {
			$data['systems'] = \App\Presenters\HubPresenter::listed(
				$data['systems'], $this->cards->bySlug(), \App\Presenters\HubPresenter::backendOnlySlugs());
			$data['total'] = count($data['systems']);
		}
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
			// Provenance: the git ref this Wing was deployed from (plist env,
			// stamped by pazny.wing at converge). estate-status reads git_ref
			// and compares it to the checkout HEAD — the answer to
			// `repo != running system` for this organ, previously unanswerable.
			'git_ref' => getenv('NOS_WING_DEPLOYED_REF') ?: 'unknown',
		]);
	}
}
