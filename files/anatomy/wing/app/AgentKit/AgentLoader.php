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
	 * The gate sets an agent may name. Read from the committed registry — the
	 * same file the judges read — so a typo is refused at the door instead of
	 * surfacing as an unrunnable outcome loop three hours into a session.
	 *
	 * An unreadable registry is a REFUSAL, not an empty allow-list: absence of
	 * an oracle is UNKNOWN, and UNKNOWN must not resolve to satisfied.
	 *
	 * @return array<int, string>
	 * @throws AgentLoadException
	 */
	private static function knownGateSets(): array
	{
		$root = (string) getenv('NOS_REPO_ROOT');
		$path = $root . '/state/judge-sets.yml';
		if ($root === '' || !is_file($path)) {
			throw new AgentLoadException(
				"outcomes.gateset cannot be checked: state/judge-sets.yml not readable "
				. "(NOS_REPO_ROOT=" . var_export($root, true) . ")"
			);
		}
		try {
			$registry = Yaml::parseFile($path);
		} catch (\Throwable $exc) {
			throw new AgentLoadException("state/judge-sets.yml parse failed: " . $exc->getMessage(), previous: $exc);
		}
		return array_keys((array) ($registry['gate_sets'] ?? []));
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
		// A grader that IS the proposer is not a second opinion — a model asked
		// to judge its own output agrees with itself (arXiv:2510.16657), so the
		// same-model arrangement is refused rather than tolerated. `backend` is
		// where the primary's traffic is pointed; naming it here would route the
		// grader to the very endpoint that produced the work.
		$grader = $raw['model']['grader'] ?? null;
		if ($grader !== null) {
			if (!is_string($grader) || !$this->isValidModelUri($grader)) {
				throw new AgentLoadException("agent.yml model.grader invalid: " . var_export($grader, true));
			}
			$backend = $raw['model']['backend'] ?? null;
			if ($grader === $primary || ($backend !== null && $grader === $backend)) {
				throw new AgentLoadException(
					"agent.yml model.grader must differ from model.primary and model.backend; got '{$grader}'"
				);
			}
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

		// Outcomes
		$rubric = null;
		// Per-agent output cap for one model call. Absent -> the old
		// interface default; a writing ceremony declares its own, because
		// 4096 truncated the librarian mid-brief and it never reached the
		// POST that the batch exists to make.
		$maxOutputTokens = (int) ($raw['model']['max_output_tokens'] ?? 4096);
		if ($maxOutputTokens < 256 || $maxOutputTokens > 200000) {
			throw new AgentLoadException(
				"agent.yml model.max_output_tokens out of range (256..200000): {$maxOutputTokens}"
			);
		}
		$maxIterations = 3;
		$gateset = null;
		$deliverableEvent = null;
		if (!empty($raw['outcomes'])) {
			// THE ORACLE IS MANDATORY. An outcome loop with no gate set has
			// nothing to ask but the model that produced the work.
			$gateset = $raw['outcomes']['gateset'] ?? null;
			if (!is_string($gateset) || $gateset === '') {
				throw new AgentLoadException(
					'agent.yml outcomes.gateset is required — name a gate set from state/judge-sets.yml'
				);
			}
			$known = self::knownGateSets();
			if (!in_array($gateset, $known, true)) {
				throw new AgentLoadException(
					"agent.yml outcomes.gateset '{$gateset}' is not in state/judge-sets.yml "
					. '(known: ' . implode(', ', $known) . ')'
				);
			}
			if (!empty($raw['outcomes']['rubric_path'])) {
				$rubricPath = $dir . '/' . $raw['outcomes']['rubric_path'];
				if (!is_file($rubricPath)) {
					throw new AgentLoadException("outcomes.rubric_path missing: {$rubricPath}");
				}
				$rubric = new Rubric((string) file_get_contents($rubricPath), $rubricPath);
			}
			// The deliverable, if the ceremony's work is an ARTIFACT rather
			// than the tree. Validated here so a typo is a load error, not a
			// ceremony that can never be satisfied and never says why.
			$deliverable = $raw['outcomes']['deliverable'] ?? null;
			if ($deliverable !== null) {
				$deliverableEvent = is_array($deliverable) ? ($deliverable['event'] ?? null) : null;
				if (!is_string($deliverableEvent) || $deliverableEvent === '') {
					throw new AgentLoadException(
						'agent.yml outcomes.deliverable must be {event: <type>} — the event '
						. 'type this ceremony has to file before a gate set may certify it'
					);
				}
			}
			$maxIterations = (int) ($raw['outcomes']['max_iterations'] ?? 3);
			if ($maxIterations < 1 || $maxIterations > 10) {
				throw new AgentLoadException("outcomes.max_iterations must be 1..10; got {$maxIterations}");
			}
		}

		// mode: one_shot is the ops plane's measurement shape — ONE call, no
		// loop of any kind. Declaring a loop's apparatus alongside it is a
		// contradiction, not a preference, so both are refused here.
		$mode = $raw['mode'] ?? 'loop';
		$oneShotSchema = [];
		if (!in_array($mode, ['loop', 'one_shot'], true)) {
			throw new AgentLoadException("agent.yml mode must be loop|one_shot; got " . var_export($mode, true));
		}
		if ($mode === 'one_shot') {
			if ($tools !== []) {
				throw new AgentLoadException('agent.yml mode: one_shot cannot declare tools — one call, no tool-use loop');
			}
			if ($gateset !== null) {
				throw new AgentLoadException('agent.yml mode: one_shot cannot declare outcomes — one call, no outcome loop');
			}
			$schemaPath = $raw['one_shot']['schema_path'] ?? null;
			if (!is_string($schemaPath) || $schemaPath === '') {
				throw new AgentLoadException('agent.yml mode: one_shot requires one_shot.schema_path — an unvalidated chain records nothing');
			}
			$schemaFile = $dir . '/' . $schemaPath;
			if (!is_file($schemaFile)) {
				throw new AgentLoadException("one_shot.schema_path missing: {$schemaFile}");
			}
			$decoded = json_decode((string) file_get_contents($schemaFile), true);
			if (!is_array($decoded) || $decoded === []) {
				throw new AgentLoadException("one_shot.schema_path is not a non-empty JSON object: {$schemaFile}");
			}
			$oneShotSchema = $decoded;
		} elseif (isset($raw['one_shot'])) {
			throw new AgentLoadException('agent.yml one_shot declared without mode: one_shot');
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
			modelGraderUri: isset($raw['model']['grader']) ? (string) $raw['model']['grader'] : null,
			systemPrompt: $systemPrompt,
			tools: $tools,
			rubric: $rubric,
			maxIterations: $maxIterations,
			capabilityScopes: array_values($capabilityScopes),
			piiClassification: $piiClass,
			requiredCredentials: $requiredCreds,
			subscriptions: $subscriptions,
			metadata: (array) ($raw['metadata'] ?? []),
			sourceDir: $dir,
			backendName: isset($raw['model']['backend'])
				? (string) $raw['model']['backend'] : null,
			gdpr: (array) ($raw['gdpr'] ?? []),
			maxOutputTokens: $maxOutputTokens,
			gateset: $gateset,
			deliverableEvent: $deliverableEvent,
			mode: (string) $mode,
			oneShotSchema: $oneShotSchema,
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

	/**
	 * THE DELIMITER WAS INSIDE THE CHARACTER CLASS (fixed 2026-08-16).
	 *
	 * The pattern was `/…[A-Za-z0-9._:/-]{1,96}$/` — a `/`-delimited regex
	 * with an unescaped `/` in the class. PCRE ended the pattern at that
	 * slash and read `-]{1,96}$/` as modifiers:
	 *
	 *     preg_match(): Unknown modifier '-'
	 *
	 * `preg_match` returns FALSE on a compile error, and `(bool) false` is
	 * indistinguishable here from "this URI is invalid". So this method had
	 * never once returned true — measured against every shape the estate
	 * uses, and against the literal string "garbage", which was rejected for
	 * the same non-reason:
	 *
	 *     claude-sonnet                 => false
	 *     anthropic-claude-sonnet-4-5   => false
	 *     openclaw-qwen2.5-coder:32b    => false
	 *     garbage                       => false
	 *
	 * Which means `AgentLoader::load()` threw `model.primary invalid` for
	 * EVERY agent, and AgentKit has never successfully loaded one. The four
	 * rows in `agent_sessions` were written by the shell bridge, which does
	 * not use this class — so the whole runtime above it (bindings, session
	 * ceilings, fallback attribution) had been built on a floor nothing had
	 * ever stood on. Nothing reported it because nothing ever called it.
	 *
	 * `#` as the delimiter, so the class needs no escaping and the next
	 * person to add a character to it cannot re-open this.
	 */
	private function isValidModelUri(string $uri): bool
	{
		return (bool) preg_match('#^(anthropic|claude|openai|openclaw)-[A-Za-z0-9._:/-]{1,96}$#', $uri);
	}
}

final class AgentLoadException extends \RuntimeException
{
}
