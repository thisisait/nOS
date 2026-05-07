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
 * Three views:
 *   /agents                       — list of all agents on disk + recent sessions
 *   /agents/<name>                — agent detail (config + last 50 sessions)
 *   /agents/<name>/sessions/<id>  — single session deep-dive (threads, iterations, OTel link)
 *
 * Read-only browser. Operator-only (no Tier-1 super-admin gate yet — agents
 * write nothing back through this presenter; for triggering an agent run
 * use bin/run-agent.php or POST /api/v1/agents/<name>/sessions which will
 * land in a follow-up alongside the operator-trigger button).
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
