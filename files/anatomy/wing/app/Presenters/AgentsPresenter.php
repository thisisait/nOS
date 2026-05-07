<?php

declare(strict_types=1);

namespace App\Presenters;

use App\AgentKit\AgentLoader;
use App\AgentKit\AgentLoadException;
use App\Model\AgentSessionRepository;
use App\Model\AgentVaultRepository;

/**
 * Wing /agents — agent catalog + session lineage browser (A14, 2026-05-07).
 *
 * Four views:
 *   /agents                       — list of all agents on disk + recent sessions
 *   /agents/<name>                — agent detail (config + last 50 sessions)
 *   /agents/<name>/sessions/<id>  — single session deep-dive (threads, iterations, OTel link)
 *   POST /agents/<name>/start     — operator-trigger spawn (form POST from
 *                                   detail.latte). Internally proxies the
 *                                   bearer-protected API endpoint
 *                                   /api/v1/agents/<name>/sessions; the
 *                                   actor_id derivation + proc_open array
 *                                   spawn live in Api\AgentsPresenter so
 *                                   there is exactly one canonical trigger
 *                                   surface. Form POST goes through the
 *                                   server here so the bearer token never
 *                                   touches browser HTML — see actionStart
 *                                   for the cURL forward to /api/v1/...
 *
 * The bearer-token's name remains the `actor_id` recorded by the API on
 * the agent_sessions row (per A14 follow-up doctrine — bearer-token name
 * is the credential identity, recorded in agent_sessions.actor_id).
 */
final class AgentsPresenter extends BasePresenter
{
	protected string $activeTab = 'agents';

	public function __construct(
		private AgentLoader $loader,
		private AgentSessionRepository $sessions,
		private AgentVaultRepository $vaults,
	) {
	}

	/**
	 * Tier-1 RBAC gate (BasePresenter::requireSuperAdmin). Mirrors
	 * AdminPresenter / ApprovalsPresenter — every action on this presenter
	 * (read AND write) requires nos-providers membership. actionStart is
	 * particularly sensitive: it forwards a server-side cURL with the
	 * daemon's WING_API_TOKEN to the bearer-protected API endpoint, so a
	 * caller who reaches it gains agent-runner authority under daemon
	 * credentials. Authentik forward-auth already gates wing.<tld> to
	 * Tier-1 (default.config.yml::authentik_app_tiers wing: 1) — this
	 * gate is the in-Wing defence-in-depth layer per A13.7 doctrine.
	 *
	 * Pinned by tests/anatomy/test_security_presenter_gates.py.
	 */
	public function startup(): void
	{
		parent::startup();
		$this->requireSuperAdmin();
	}

	public function renderDefault(): void
	{
		$this->template->agents = $this->buildCatalog();
		$this->template->recent = $this->sessions->listRecent(20);
	}

	public function renderDetail(string $name): void
	{
		try {
			$agent = $this->loader->load($name);
		} catch (AgentLoadException $exc) {
			$this->error("Agent '{$name}' not loadable: " . $exc->getMessage(), 404);
			return;
		}
		$this->template->agent = $agent;
		$this->template->sessions = $this->sessions->listRecent(50, $name);
		$this->template->vaultsAvailable = $this->vaults->listVaults();
	}

	public function renderSession(string $name, string $id): void
	{
		$session = $this->sessions->findByUuid($id);
		if ($session === null || $session['agent_name'] !== $name) {
			$this->error("Session {$id} not found for agent {$name}", 404);
			return;
		}
		$this->template->session = $session;
		$this->template->threads = $this->sessions->listThreadsForSession($id);
		$this->template->iterations = $this->sessions->listIterations($id);
		// Tempo deep-link — operator clicks to see the full trace.
		$this->template->tempoUrl = sprintf(
			'/grafana/explore?left=%s',
			urlencode(json_encode([
				'datasource' => 'tempo',
				'queries' => [['query' => $session['trace_id']]],
			]) ?: ''),
		);
	}

	/**
	 * POST /agents/<name>/start — operator-trigger spawn from detail.latte.
	 *
	 * The button on /agents/<name> renders as `<form method="post" action=
	 * "{plink Agents:start, name => $agent->name}">`. We proxy the call to
	 * the bearer-protected API endpoint so the bearer token never touches
	 * the browser HTML / fetch headers (and the bearer-from-token-row
	 * audit lineage stays uniform with Pulse / webhook triggers).
	 *
	 * Auth flow:
	 *   1. Authentik forward-auth gates this presenter (see BasePresenter)
	 *      and stamps X-Authentik-Username on every request.
	 *   2. We forward via cURL to http://127.0.0.1:9000/api/v1/agents/<name>/sessions
	 *      with `Authorization: Bearer ${WING_API_TOKEN}`.
	 *   3. The API endpoint generates session_uuid, spawns the runner via
	 *      proc_open array form, returns 202 with session_uuid.
	 *   4. We redirect to /agents/<name>/sessions/<uuid> so the operator
	 *      lands on the live session deep-dive view.
	 */
	public function actionStart(string $name): void
	{
		$this->requirePostMethod();

		$prompt = $this->getHttpRequest()->getPost('prompt');
		$vault  = $this->getHttpRequest()->getPost('vault');
		$body = [];
		if (is_string($prompt) && $prompt !== '') {
			$body['prompt'] = $prompt;
		}
		if (is_string($vault) && $vault !== '') {
			$body['vault'] = $vault;
		}

		$token = (string) (getenv('WING_API_TOKEN') ?: '');
		if ($token === '') {
			$this->flashMessage(
				'Cannot start agent: WING_API_TOKEN not set in wing daemon environment. ' .
					'Run a playbook pass or `php bin/provision-token.php` to bootstrap.',
				'error',
			);
			$this->redirect('Agents:detail', ['name' => $name]);
			return;
		}

		$ch = curl_init('http://127.0.0.1:9000/api/v1/agents/' . urlencode($name) . '/sessions');
		curl_setopt_array($ch, [
			CURLOPT_RETURNTRANSFER => true,
			CURLOPT_POST           => true,
			CURLOPT_POSTFIELDS     => json_encode($body) ?: '{}',
			CURLOPT_HTTPHEADER     => [
				'Content-Type: application/json',
				'Authorization: Bearer ' . $token,
			],
			CURLOPT_TIMEOUT        => 10,
		]);
		$raw = curl_exec($ch);
		$httpCode = (int) curl_getinfo($ch, CURLINFO_HTTP_CODE);
		$curlError = curl_error($ch);

		// API returns 202 Accepted on successful spawn (the agent_sessions
		// row will exist once the child boots; no 201 because the resource
		// isn't created yet at response time). Treat any 2xx as success
		// to be tolerant of upstream code-tightening.
		if ($raw === false || $httpCode < 200 || $httpCode >= 300) {
			$this->flashMessage(
				'Failed to start agent: ' .
					($curlError !== '' ? $curlError : "HTTP {$httpCode}: " . substr((string) $raw, 0, 200)),
				'error',
			);
			$this->redirect('Agents:detail', ['name' => $name]);
			return;
		}

		$decoded = json_decode((string) $raw, true);
		$sessionUuid = is_array($decoded) ? ($decoded['session_uuid'] ?? null) : null;
		if (!is_string($sessionUuid) || $sessionUuid === '') {
			$this->flashMessage('Agent runner spawned but session_uuid missing from API response.', 'error');
			$this->redirect('Agents:detail', ['name' => $name]);
			return;
		}

		$this->flashMessage("Agent run started — session {$sessionUuid}.", 'success');
		$this->redirect('Agents:session', ['name' => $name, 'id' => $sessionUuid]);
	}

	/**
	 * @return array<int, array{name: string, version: int, description: string, model_primary: string, multiagent_type: string, has_outcome: bool, sessions_recent: int, error: ?string}>
	 */
	private function buildCatalog(): array
	{
		$out = [];
		foreach ($this->loader->listAvailable() as $name) {
			try {
				$agent = $this->loader->load($name);
				$recent = count($this->sessions->listRecent(100, $name));
				$out[] = [
					'name' => $agent->name,
					'version' => $agent->version,
					'description' => $agent->description,
					'model_primary' => $agent->modelPrimaryUri,
					'multiagent_type' => $agent->multiagentType,
					'has_outcome' => $agent->hasOutcome(),
					'sessions_recent' => $recent,
					'error' => null,
				];
			} catch (AgentLoadException $exc) {
				$out[] = [
					'name' => $name,
					'version' => 0,
					'description' => '(failed to load)',
					'model_primary' => '?',
					'multiagent_type' => '?',
					'has_outcome' => false,
					'sessions_recent' => 0,
					'error' => $exc->getMessage(),
				];
			}
		}
		return $out;
	}
}
