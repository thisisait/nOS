<?php

declare(strict_types=1);

namespace App\AgentKit;

use App\AgentKit\Outcome\Rubric;
use App\AgentKit\Webhook\SubscriptionRegistrar;
use Symfony\Component\Yaml\Yaml;

/**
 * Loads + validates files/anatomy/agents/<name>/agent.yml into Agent value
 * objects. Validation rules mirror state/schema/agent.schema.yaml; the YAML
 * schema is the source of truth and the CI gate
 * tests/anatomy/test_agent_schema.py asserts that every agent.yml on disk
 * passes both the YAML schema and this loader's checks.
 *
 * Throws AgentLoadException on any structural problem. The runner converts
 * that to a terminal session error with status='terminated'.
 *
 * Side effect on load: if a SubscriptionRegistrar collaborator is wired
 * (production Nette DI does this; unit tests typically don't), every
 * subscribe: entry parsed out of agent.yml is upserted into
 * agent_subscriptions. The upsert is idempotent — re-loading the same
 * agent does not duplicate rows, and operator-modified rows are kept.
 */
final class AgentLoader
{
	public function __construct(
		private readonly string $agentsRoot,
		private readonly ?SubscriptionRegistrar $subscriptionRegistrar = null,
	) {
	}

	/**
	 * @throws AgentLoadException
	 */
	public function load(string $name): Agent
	{
		$this->validateName($name);
		$dir = $this->agentsRoot . '/' . $name;
		$yamlPath = $dir . '/agent.yml';
		if (!is_file($yamlPath)) {
			throw new AgentLoadException("agent.yml not found at {$yamlPath}");
		}

		try {
			$raw = Yaml::parseFile($yamlPath);
		} catch (\Throwable $exc) {
			throw new AgentLoadException("agent.yml YAML parse failed: " . $exc->getMessage(), previous: $exc);
		}
		if (!is_array($raw)) {
			throw new AgentLoadException("agent.yml must be a YAML mapping; got " . gettype($raw));
		}

		// Required top-level fields
		foreach (['name', 'version', 'description', 'model', 'audit'] as $required) {
			if (!array_key_exists($required, $raw)) {
				throw new AgentLoadException("agent.yml missing required field: {$required}");
			}
		}

		if ($raw['name'] !== $name) {
			throw new AgentLoadException("agent.yml name '{$raw['name']}' does not match directory '{$name}'");
		}

		// Model
		$primary = $raw['model']['primary'] ?? null;
		if (!is_string($primary) || !$this->isValidModelUri($primary)) {
			throw new AgentLoadException("agent.yml model.primary invalid: " . var_export($primary, true));
		}
		$fallback = $raw['model']['fallback'] ?? null;
		if ($fallback !== null && (!is_string($fallback) || !$this->isValidModelUri($fallback))) {
			throw new AgentLoadException("agent.yml model.fallback invalid: " . var_export($fallback, true));
		}

		// System prompt (optional)
		$systemPrompt = null;
		if (!empty($raw['system_prompt_path'])) {
			$promptPath = $dir . '/' . $raw['system_prompt_path'];
			if (!is_file($promptPath)) {
				throw new AgentLoadException("system_prompt_path missing: {$promptPath}");
			}
			$systemPrompt = file_get_contents($promptPath) ?: null;
		}

		// Tools
		$tools = [];
		foreach (($raw['tools'] ?? []) as $i => $toolRaw) {
			if (!isset($toolRaw['id']) || !is_string($toolRaw['id'])) {
				throw new AgentLoadException("agent.yml tools[{$i}].id missing or not a string");
			}
			$tools[] = new ToolSpec($toolRaw['id'], (array) ($toolRaw['config'] ?? []));
		}

		// Multiagent
		$mType = $raw['multiagent']['type'] ?? 'solo';
		if (!in_array($mType, ['solo', 'coordinator'], true)) {
			throw new AgentLoadException("agent.yml multiagent.type must be solo|coordinator; got {$mType}");
		}
		$roster = [];
		foreach (($raw['multiagent']['roster'] ?? []) as $i => $rosterRaw) {
			if (!isset($rosterRaw['name']) || !is_string($rosterRaw['name'])) {
				throw new AgentLoadException("agent.yml multiagent.roster[{$i}].name missing");
			}
			$roster[] = new RosterEntry(
				$rosterRaw['name'],
				isset($rosterRaw['version']) ? (int) $rosterRaw['version'] : null,
			);
		}
		// Default 4 (A14 multi-agent-followup baseline). Hard cap 16 — beyond
		// that you want a queue runner (Pulse), not in-process parallelism.
		// ProcessPool clamps silently as a defense-in-depth, but the loader
		// still rejects out-of-range values so agent.yml authors get a clear
		// error message instead of a silent clamp.
		$maxThreads = (int) ($raw['multiagent']['max_concurrent_threads'] ?? 4);
		if ($maxThreads < 1 || $maxThreads > 16) {
			throw new AgentLoadException("max_concurrent_threads must be 1..16; got {$maxThreads}");
		}

		// Outcomes
		$rubric = null;
		$maxIterations = 3;
		if (!empty($raw['outcomes'])) {
			if (!empty($raw['outcomes']['rubric_path'])) {
				$rubricPath = $dir . '/' . $raw['outcomes']['rubric_path'];
				if (!is_file($rubricPath)) {
					throw new AgentLoadException("outcomes.rubric_path missing: {$rubricPath}");
				}
				$rubric = new Rubric((string) file_get_contents($rubricPath), $rubricPath);
			}
			$maxIterations = (int) ($raw['outcomes']['max_iterations'] ?? 3);
			if ($maxIterations < 1 || $maxIterations > 10) {
				throw new AgentLoadException("outcomes.max_iterations must be 1..10; got {$maxIterations}");
			}
		}

		// Audit
		$capabilityScopes = $raw['audit']['capability_scopes'] ?? null;
		if (!is_array($capabilityScopes) || $capabilityScopes === []) {
			throw new AgentLoadException("agent.yml audit.capability_scopes must be a non-empty array");
		}
		$piiClass = $raw['audit']['pii_classification'] ?? null;
		if (!in_array($piiClass, ['none', 'low', 'high'], true)) {
			throw new AgentLoadException("audit.pii_classification must be none|low|high; got " . var_export($piiClass, true));
		}

		// Vault requirements
		$requiredCreds = [];
		foreach (($raw['vault']['required_credentials'] ?? []) as $i => $credRaw) {
			if (!isset($credRaw['scope']) || !is_string($credRaw['scope'])) {
				throw new AgentLoadException("agent.yml vault.required_credentials[{$i}].scope missing");
			}
			$requiredCreds[] = new VaultRequirement(
				$credRaw['scope'],
				(bool) ($credRaw['optional'] ?? false),
			);
		}

		// subscribe: per-agent webhook auto-fan-out. Optional. SubscriptionRegistrar
		// turns each spec into an idempotent agent_subscriptions row at boot time;
		// WebhookDispatcher evaluates the filter map at fire time.
		$subscriptions = [];
		foreach (($raw['subscribe'] ?? []) as $i => $subRaw) {
			if (!is_array($subRaw)) {
				throw new AgentLoadException("agent.yml subscribe[{$i}] must be a mapping");
			}
			$eventType = $subRaw['event_type'] ?? null;
			if (!is_string($eventType) || $eventType === '') {
				throw new AgentLoadException("agent.yml subscribe[{$i}].event_type missing or not a string");
			}
			$filterRaw = $subRaw['filter'] ?? [];
			if (!is_array($filterRaw)) {
				throw new AgentLoadException("agent.yml subscribe[{$i}].filter must be a mapping");
			}
			// Exact-string equality only. Reject anything that isn't a string.
			$filter = [];
			foreach ($filterRaw as $k => $v) {
				if (!is_string($k) || !is_string($v)) {
					throw new AgentLoadException(
						"agent.yml subscribe[{$i}].filter must map string => string "
						. "(no regex/glob/eval — got " . gettype($v) . ")"
					);
				}
				$filter[$k] = $v;
			}
			$triggerArg = $subRaw['trigger_arg'] ?? 'prompt';
			if (!in_array($triggerArg, ['prompt', 'vault'], true)) {
				throw new AgentLoadException(
					"agent.yml subscribe[{$i}].trigger_arg must be prompt|vault; got "
					. var_export($triggerArg, true)
				);
			}
			$subscriptions[] = new SubscriptionSpec($eventType, $filter, $triggerArg);
		}

		$agent = new Agent(
			name: $raw['name'],
			version: (int) $raw['version'],
			description: (string) $raw['description'],
			modelPrimaryUri: $primary,
			modelFallbackUri: $fallback,
			systemPrompt: $systemPrompt,
			tools: $tools,
			multiagentType: $mType,
			roster: $roster,
			maxConcurrentThreads: $maxThreads,
			rubric: $rubric,
			maxIterations: $maxIterations,
			capabilityScopes: array_values($capabilityScopes),
			piiClassification: $piiClass,
			requiredCredentials: $requiredCreds,
			subscriptions: $subscriptions,
			metadata: (array) ($raw['metadata'] ?? []),
			sourceDir: $dir,
		);

		// Idempotent webhook registration — only when wired in production.
		// Tests that load Agent value objects without a DB collaborator
		// stay pure; operator-running Wing converges agent_subscriptions
		// rows on every AgentLoader::load().
		if ($this->subscriptionRegistrar !== null && $subscriptions !== []) {
			$this->subscriptionRegistrar->registerForAgent($agent);
		}

		return $agent;
	}

	/**
	 * @return array<int, string> agent names available on disk (sorted)
	 */
	public function listAvailable(): array
	{
		if (!is_dir($this->agentsRoot)) {
			return [];
		}
		$names = [];
		foreach (scandir($this->agentsRoot) ?: [] as $entry) {
			if ($entry === '.' || $entry === '..') {
				continue;
			}
			$dir = $this->agentsRoot . '/' . $entry;
			if (is_dir($dir) && is_file($dir . '/agent.yml')) {
				$names[] = $entry;
			}
		}
		sort($names);
		return $names;
	}

	private function validateName(string $name): void
	{
		if (!preg_match('/^[a-z][a-z0-9-]{1,38}[a-z0-9]$/', $name)) {
			throw new AgentLoadException("agent name '{$name}' does not match ^[a-z][a-z0-9-]{1,38}[a-z0-9]$");
		}
	}

	private function isValidModelUri(string $uri): bool
	{
		return (bool) preg_match('/^(anthropic|openclaw|openai|local)-[a-z0-9.-]+$/', $uri);
	}
}

final class AgentLoadException extends \RuntimeException
{
}
