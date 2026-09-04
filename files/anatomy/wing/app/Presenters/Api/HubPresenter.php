<?php

declare(strict_types=1);

namespace App\Presenters\Api;

use App\Model\SystemRepository;

/**
 * GET /api/v1/hub/systems         — list all systems (flat, with filters) [PUBLIC]
 * GET /api/v1/hub/systems?tree=1  — tree (hierarchy with children) [PUBLIC]
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
 *   1. `systems` removed from $publicActions — POST now hits
 *      requireTokenAuth via BaseApiPresenter::startup(). GETs are
 *      restored to "public" via the runtime branch below.
 *   2. SystemRepository::upsert whitelists WRITABLE_FIELDS — clients
 *      can't write health_status, audit columns, or unknown columns.
 */
final class HubPresenter extends BaseApiPresenter
{
	/**
	 * `health` stays public (read-only probe surface).
	 *
	 * `systems` is intentionally NOT in this list anymore — the action
	 * itself handles read-vs-write differently. GET paths short-circuit
	 * to public; POST hits requireTokenAuth via parent startup BEFORE
	 * the action runs (because we keep `systems` out of $publicActions).
	 */
	protected array $publicActions = ['health'];

	/** @inject */
	public SystemRepository $systems;

	public function startup(): void
	{
		// SEC-7: for GET on /systems, bypass requireTokenAuth (read is
		// public). For POST, fall through to BaseApiPresenter::startup
		// which runs requireTokenAuth. The action name `systems` is
		// not in $publicActions; the read-public behavior is recovered
		// by this method-aware override.
		$method = $this->getHttpRequest()->getMethod();
		if ($this->getAction() === 'systems' && $method === 'GET') {
			// Mirror BaseApiPresenter's content-type setting; skip the
			// token check entirely (read is public).
			$this->getHttpResponse()->setContentType('application/json', 'utf-8');
			\Nette\Application\UI\Presenter::startup();
			return;
		}
		parent::startup();
	}

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
			'git_ref' => getenv('NOS_ORGAN_DEPLOYED_REF') ?: 'unknown',
		]);
	}
}
